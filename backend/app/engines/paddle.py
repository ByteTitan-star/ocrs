"""PaddleOCR 引擎：PP-StructureV3 版面恢复管线，直接输出 Markdown。"""
import shutil
import time
from pathlib import Path

from .. import config as cfg
from ..pdf_utils import PAGE_SEPARATOR, count_pages
from .base import OcrEngine, ProgressFn


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
        return True, f"paddleocr {ver}"

    def _load(self) -> None:
        from paddleocr import PPStructureV3

        kwargs = {}
        if cfg.PADDLE_DEVICE:
            kwargs["device"] = cfg.PADDLE_DEVICE
        if cfg.PADDLE_FAST:
            kwargs.update(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        self.pipeline = PPStructureV3(**kwargs)
        device_desc = cfg.PADDLE_DEVICE or "auto"
        print(f"[paddle] PP-StructureV3 已加载：device={device_desc}")

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
            progress(i + 1, total, f"第 {i + 1}/{total} 页完成，用时 {time.time() - started:.1f}s")
        return PAGE_SEPARATOR.join(parts)
