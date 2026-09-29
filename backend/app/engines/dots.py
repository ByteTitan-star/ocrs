"""dots.ocr 引擎：基于 vendored dots_ocr 包 + transformers 推理。

与官方 DotsOCRParser 的区别：官方 HF 路径硬编码 CUDA + flash-attention，
这里改为设备/精度/注意力实现可配置（Mac 上默认 MPS + SDPA + bfloat16），
推理流程（prompt → 布局 JSON → post_process_output → layoutjson2md）与官方一致。
"""
import json
import time
from pathlib import Path

from .. import config as cfg
from ..pdf_utils import PAGE_SEPARATOR
from .base import OcrEngine, ProgressFn

PROMPT_MODE = cfg.DOTS_PROMPT_MODE


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
        self.processor = AutoProcessor.from_pretrained(str(cfg.DOTS_MODEL_PATH), trust_remote_code=True)
        self.process_vision_info = process_vision_info
        print(f"[dots] 模型已加载：device={device} dtype={dtype_name} attn={attn}")

    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn) -> str:
        import torch
        from dots_ocr.utils.doc_utils import load_images_from_pdf
        from dots_ocr.utils.format_transformer import layoutjson2md
        from dots_ocr.utils.image_utils import fetch_image
        from dots_ocr.utils.layout_utils import post_process_output
        from dots_ocr.utils.prompts import dict_promptmode_to_prompt

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

            with torch.inference_mode():
                generated = self.model.generate(
                    **inputs,
                    max_new_tokens=cfg.DOTS_MAX_NEW_TOKENS,
                    do_sample=False,
                )
            trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, generated)]
            response = self.processor.batch_decode(
                trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False,
            )[0]

            cells, filtered = post_process_output(
                response, PROMPT_MODE, origin_image, image,
                min_pixels=None, max_pixels=max_pixels,
            )
            page_md = layoutjson2md(origin_image, cells, text_key="text") if cells else response
            parts.append(page_md)

            # 存档每页原始输出，便于调试与追溯
            (pages_dir / f"page_{i + 1:04d}.json").write_text(
                json.dumps(cells, ensure_ascii=False, indent=1), encoding="utf-8")
            (pages_dir / f"page_{i + 1:04d}.md").write_text(page_md, encoding="utf-8")

            progress(i + 1, total, f"第 {i + 1}/{total} 页完成，用时 {time.time() - started:.1f}s")
        return PAGE_SEPARATOR.join(parts)
