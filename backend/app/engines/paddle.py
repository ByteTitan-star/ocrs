"""PaddleOCR 引擎：PP-StructureV3 版面恢复管线，直接输出 Markdown。

设备自动兼容：OCRS_PADDLE_DEVICE 留空时自动探测——装有 paddlepaddle-gpu 且有
CUDA 卡则用 gpu:0，否则 cpu（macOS 的 paddle 无 GPU 后端，自然落到 cpu）。
精度/速度三档：OCRS_PADDLE_PROFILE = accurate（官方默认全开）| balanced（关闭
方向分类/矫正/文本行方向，保留 server 检测识别与公式）| fast（mobile 检测识别
+ 关闭公式识别，纯 CPU 也只数秒/页）。
"""
import shutil
import time
from pathlib import Path

from .. import config as cfg
from ..pdf_utils import count_pages
from .base import PAGE_SEPARATOR, OcrEngine, ProgressFn, append_page_markdown


def _save_markdown_image(work_dir: Path, rel_path: str, image) -> None:
    """把 PP-StructureV3 markdown_images 中的图片对象落到 work_dir 下。"""
    target = work_dir / rel_path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(image, (str, Path)):  # 已是文件路径（部分版本行为）
        shutil.copyfile(image, target)
        return
    if hasattr(image, "save"):  # PIL.Image
        image.save(target)
        return
    import numpy as np
    from PIL import Image
    Image.fromarray(np.asarray(image)).save(target)


class PaddleEngine(OcrEngine):
    name = "paddle"
    label = "PaddleOCR (PP-StructureV3)"
    setup_hint = "运行 scripts/setup.sh --paddle 安装 paddlepaddle 与 paddleocr（需 3.x 版本）"

    def availability(self) -> tuple[bool, str]:
        try:
            import paddleocr
        except ImportError:
            return False, "paddleocr 未安装"
        from importlib.metadata import version
        try:
            ver = version("paddleocr")
        except Exception:
            ver = getattr(paddleocr, "__version__", "3.x")
        if not hasattr(paddleocr, "PPStructureV3"):
            return False, f"paddleocr {ver} 不包含 PPStructureV3，需要 3.x"
        return True, f"paddleocr {ver} · profile={cfg.PADDLE_PROFILE}"

    def _resolve_device(self) -> str:
        if cfg.PADDLE_DEVICE:
            return cfg.PADDLE_DEVICE
        try:
            import paddle
            if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
                return "gpu:0"
        except Exception:
            pass
        return "cpu"

    def _pipeline_kwargs(self) -> dict:
        profile = cfg.PADDLE_PROFILE if cfg.PADDLE_PROFILE in ("accurate", "balanced", "fast") else "accurate"
        kwargs: dict = {}
        if profile in ("balanced", "fast") or cfg.PADDLE_FAST:  # PADDLE_FAST 为旧开关，等价三关闭
            kwargs.update(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        if profile == "fast":
            kwargs.update(
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="PP-OCRv5_mobile_rec",
                use_formula_recognition=False,  # 跳过 698MB 的 FormulaNet-L
            )
        return kwargs

    def _load(self) -> None:
        from paddleocr import PPStructureV3

        kwargs = self._pipeline_kwargs()
        kwargs["device"] = self._resolve_device()
        self.pipeline = PPStructureV3(**kwargs)
        print(f"[paddle] PP-StructureV3 已加载：device={kwargs['device']} "
              f"profile={cfg.PADDLE_PROFILE}")

    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn) -> str:
        total = count_pages(pdf_path)
        results = self.pipeline.predict(str(pdf_path))
        parts: list[str] = []
        for i, res in enumerate(results):
            started = time.time()
            md = getattr(res, "markdown", None) or {}
            text = md.get("markdown_texts")
            if isinstance(text, list):  # 新旧版本兼容：列表或整页字符串
                text = "\n\n".join(text)
            for rel_path, image in (md.get("markdown_images") or {}).items():
                _save_markdown_image(work_dir, rel_path, image)
            parts.append(text or "")
            append_page_markdown(work_dir, text or "", i)
            progress(i + 1, total, f"第 {i + 1}/{total} 页完成，用时 {time.time() - started:.1f}s")
        return PAGE_SEPARATOR.join(parts)
