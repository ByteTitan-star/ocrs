"""dots.ocr 引擎：基于 vendored dots_ocr 包 + transformers 推理。

与官方 DotsOCRParser 的区别（均为 Mac/CPU 可跑性改造，推理语义不变）：
1. 设备/精度/注意力实现可配置（Mac 默认 MPS + SDPA + bfloat16，官方硬编码 CUDA + flash-attention）；
2. 视觉塔只有 flash-attn / eager 两种实现，无 flash-attn 时 eager 的 O(S²) 注意力矩阵在长序列下会
   OOM，这里用数学等价的 SDPA 版本替换 VisionAttention.forward；
3. transformers 4.56 下 dots 自定义 DotsVLProcessor 构造会报 video_processor 类型错误，提供兜底构造。
推理流程（prompt → 布局 JSON → post_process_output → layoutjson2md）与官方一致。
"""
import json
import math
import sys
import time
from pathlib import Path

from .. import config as cfg
from .base import OcrEngine, ProgressFn, append_page_markdown

PROMPT_MODE = cfg.DOTS_PROMPT_MODE


def _patch_vision_attention_sdpa(model) -> None:
    """把视觉塔的 eager 注意力替换为 SDPA 实现（等价语义，内存 O(S)）。"""
    import torch
    import torch.nn.functional as F

    vision_tower = next(
        m for m in model.modules()
        if hasattr(m, "patch_embed") and hasattr(m, "blocks") and len(m.blocks) > 0
    )
    attn_cls = type(vision_tower.blocks[0].attn)
    apply_rope = getattr(sys.modules[attn_cls.__module__], "apply_rotary_pos_emb_vision")

    def sdpa_forward(self, hidden_states, cu_seqlens, rotary_pos_emb=None):
        seq = hidden_states.shape[0]
        q, k, v = self.qkv(hidden_states).reshape(seq, 3, self.num_heads, -1).permute(1, 0, 2, 3).unbind(0)
        q = apply_rope(q.unsqueeze(0), rotary_pos_emb).squeeze(0)
        k = apply_rope(k.unsqueeze(0), rotary_pos_emb).squeeze(0)
        # [1, heads, seq, head_dim]
        q, k, v = (t.transpose(0, 1).unsqueeze(0) for t in (q, k, v))
        mask = None
        if len(cu_seqlens) > 2:  # 多段输入（理论上单图不会出现）：块对角 bool mask
            mask = torch.zeros(seq, seq, dtype=torch.bool, device=q.device)
            for i in range(1, len(cu_seqlens)):
                a, b = int(cu_seqlens[i - 1]), int(cu_seqlens[i])
                mask[a:b, a:b] = True
            mask = mask[None, None]
        out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask,
                                             scale=1.0 / math.sqrt(self.head_dim))
        out = out.squeeze(0).transpose(0, 1).reshape(seq, -1)
        return self.proj(out)

    attn_cls.forward = sdpa_forward


class DotsEngine(OcrEngine):
    name = "dots"
    label = "dots.ocr"
    setup_hint = "运行 scripts/setup.sh --dots 安装依赖，再运行 scripts/download_dots_weights.py 下载权重"

    def availability(self) -> tuple[bool, str]:
        try:
            import dots_ocr  # noqa: F401
        except ImportError:
            return False, "dots_ocr 包未安装（vendor/dots.ocr）"
        if not (cfg.DOTS_MODEL_PATH / "config.json").is_file():
            return False, f"未找到模型权重：{cfg.DOTS_MODEL_PATH}"
        return True, str(cfg.DOTS_MODEL_PATH)

    def _resolve_device(self) -> tuple[str, str, str]:
        """返回 (device, dtype, attn_implementation)。"""
        import torch

        device = cfg.DOTS_DEVICE
        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

        dtype = cfg.DOTS_DTYPE
        if dtype == "auto":
            dtype = "float32" if device == "cpu" else "bfloat16"

        attn = cfg.DOTS_ATTN
        if attn == "auto":
            attn = "sdpa" if device != "cpu" else "eager"
        return device, dtype, attn

    def _build_processor(self, model_path: str):
        """transformers 4.56 下 dots 自定义 DotsVLProcessor 会因 video_processor=None 报错，
        这里用官方 Qwen2_5_VLProcessor 手动等价构造（video_processor 单独实例化）。"""
        import json

        from transformers import (
            AutoImageProcessor,
            AutoTokenizer,
            Qwen2VLVideoProcessor,
            Qwen2_5_VLProcessor,
        )

        image_processor = AutoImageProcessor.from_pretrained(model_path, trust_remote_code=True)
        video_processor = Qwen2VLVideoProcessor.from_pretrained(model_path)
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        template_file = Path(model_path) / "chat_template.json"
        chat_template = None
        if template_file.is_file():
            chat_template = json.loads(template_file.read_text(encoding="utf-8")).get("chat_template")
        processor = Qwen2_5_VLProcessor(
            image_processor=image_processor,
            video_processor=video_processor,
            tokenizer=tokenizer,
            chat_template=chat_template,
        )
        # dots 模板的图片占位符是 <|imgpad|>，而官方处理器默认找 <|image_pad|>，必须对齐
        if getattr(tokenizer, "image_token", None) is None:
            processor.image_token = "<|imgpad|>"
            processor.image_token_id = tokenizer.convert_tokens_to_ids("<|imgpad|>")
            if processor.image_token_id is None or processor.image_token_id < 0:
                processor.image_token_id = 151665
        return processor

    def _load(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
        from qwen_vl_utils import process_vision_info

        from dots_ocr.utils.prompts import dict_promptmode_to_prompt

        if PROMPT_MODE not in dict_promptmode_to_prompt:
            raise ValueError(f"未知 prompt 模式：{PROMPT_MODE}")
        device, dtype_name, attn = self._resolve_device()
        dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[dtype_name]

        try:
            model = AutoModelForCausalLM.from_pretrained(
                str(cfg.DOTS_MODEL_PATH),
                attn_implementation=attn,
                torch_dtype=dtype,
                trust_remote_code=True,
            )
        except Exception as exc:  # SDPA 不被远程建模代码支持时降级 eager
            if attn != "eager":
                model = AutoModelForCausalLM.from_pretrained(
                    str(cfg.DOTS_MODEL_PATH), attn_implementation="eager",
                    torch_dtype=dtype, trust_remote_code=True,
                )
            else:
                raise RuntimeError(f"加载 dots.ocr 模型失败：{exc}") from exc

        self.device = device
        self.dtype = dtype
        self.model = model.to(device).eval()
        try:
            self.processor = AutoProcessor.from_pretrained(str(cfg.DOTS_MODEL_PATH), trust_remote_code=True)
        except TypeError:  # 见 _build_processor 注释
            self.processor = self._build_processor(str(cfg.DOTS_MODEL_PATH))
        self.process_vision_info = process_vision_info
        if attn != "flash_attention_2":  # flash-attn 本身就是低内存实现，无需补丁
            _patch_vision_attention_sdpa(self.model)
        print(f"[dots] 模型已加载：device={device} dtype={dtype_name} attn={attn}")

    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn) -> str:
        import threading

        import torch
        from dots_ocr.utils.doc_utils import load_images_from_pdf
        from dots_ocr.utils.format_transformer import layoutjson2md
        from dots_ocr.utils.image_utils import fetch_image
        from dots_ocr.utils.layout_utils import post_process_output
        from dots_ocr.utils.prompts import dict_promptmode_to_prompt
        from transformers import TextIteratorStreamer

        max_pixels = cfg.DOTS_MAX_PIXELS or None
        prompt = dict_promptmode_to_prompt[PROMPT_MODE]
        pages_dir = work_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        images = load_images_from_pdf(str(pdf_path), dpi=cfg.DOTS_DPI)
        total = len(images)
        parts: list[str] = []
        for i, origin_image in enumerate(images):
            started = time.time()
            image = fetch_image(origin_image, min_pixels=None, max_pixels=max_pixels)
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }]
            text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            image_inputs, video_inputs = self.process_vision_info(messages)
            inputs = self.processor(
                text=[text], images=image_inputs, videos=video_inputs,
                padding=True, return_tensors="pt",
            )
            # 远程建模代码不转换 pixel_values 的 dtype（fp32 输入 × bf16 权重会报错），这里显式对齐
            inputs = {
                k: (v.to(self.device, self.dtype) if v.is_floating_point() else v.to(self.device))
                for k, v in inputs.items()
            }

            # token 级进度：流式读取生成内容，让前端能看到"正在输出第 X 页、已输出 N 字"
            streamer = TextIteratorStreamer(
                self.processor.tokenizer, skip_prompt=True, skip_special_tokens=True)

            def _consume_chars(streamer=streamer, page=i + 1, total_pages=total):
                emitted = 0
                for chunk in streamer:
                    emitted += len(chunk)
                    if emitted % 600 < len(chunk):  # 约每 600 字上报一次
                        progress(page - 1, total_pages, f"第 {page} 页生成中，已输出约 {emitted} 字")

            threading.Thread(target=_consume_chars, daemon=True).start()

            with torch.inference_mode():
                generated = self.model.generate(
                    **inputs,
                    max_new_tokens=cfg.DOTS_MAX_NEW_TOKENS,
                    do_sample=False,
                    streamer=streamer,
                )
            trimmed = [out[len(inp):] for inp, out in zip(inputs["input_ids"], generated)]
            response = self.processor.batch_decode(
                trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False,
            )[0]

            cells, filtered = post_process_output(
                response, PROMPT_MODE, origin_image, image,
                min_pixels=None, max_pixels=max_pixels,
            )
            page_md = layoutjson2md(origin_image, cells, text_key="text") if cells else response
            parts.append(page_md)
            append_page_markdown(work_dir, page_md, i)

            # 存档每页原始输出，便于调试与追溯
            (pages_dir / f"page_{i + 1:04d}.json").write_text(
                json.dumps(cells, ensure_ascii=False, indent=1), encoding="utf-8")
            (pages_dir / f"page_{i + 1:04d}.md").write_text(page_md, encoding="utf-8")

            progress(i + 1, total, f"第 {i + 1}/{total} 页完成，用时 {time.time() - started:.1f}s")
        return PAGE_SEPARATOR.join(parts)
