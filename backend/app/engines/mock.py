"""Mock 引擎：不加载真实模型，生成可区分的假 Markdown，用于跑通全流程与联调前端。

两个 mock 输出刻意有差异（错字/顺序），便于检验 Diff 视图效果。
"""
import io
import time
from pathlib import Path

from ..pdf_utils import PAGE_SEPARATOR, count_pages
from .base import OcrEngine, ProgressFn


def _write_demo_image(work_dir: Path) -> str:
    from PIL import Image, ImageDraw

    img_dir = work_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (320, 80), "#eef2ff")
    ImageDraw.Draw(img).rectangle([4, 4, 316, 76], outline="#6366f1", width=2)
    ImageDraw.Draw(img).text((24, 30), "demo picture", fill="#4338ca")
    path = img_dir / "demo.png"
    img.save(path)
    return "images/demo.png"


class MockDotsEngine(OcrEngine):
    name = "dots"
    label = "dots.ocr (mock)"

    def availability(self) -> tuple[bool, str]:
        return True, "mock 模式"

    def _load(self) -> None:
        time.sleep(0.3)

    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn) -> str:
        total = count_pages(pdf_path)
        rel_img = _write_demo_image(work_dir)
        parts = []
        for i in range(total):
            time.sleep(0.4)
            parts.append(
                f"# dots.ocr 识别结果 · 第 {i + 1} 页\n\n"
                f"这是 **mock 模式**下的 dots.ocr 输出，用于演示对比界面。\n\n"
                f"- 引擎：dots.ocr（假数据）\n"
                f"- 本页共识别 3 个版面块\n\n"
                f"| 字段 | 值 |\n| --- | --- |\n| 引擎 | dots.ocr |\n| 模式 | mock |\n\n"
                f"示例图片：![]({rel_img})\n"
            )
            progress(i + 1, total, f"第 {i + 1}/{total} 页完成")
        return PAGE_SEPARATOR.join(parts)


class MockPaddleEngine(OcrEngine):
    name = "paddle"
    label = "PaddleOCR (mock)"

    def availability(self) -> tuple[bool, str]:
        return True, "mock 模式"

    def _load(self) -> None:
        time.sleep(0.2)

    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn) -> str:
        total = count_pages(pdf_path)
        rel_img = _write_demo_image(work_dir)
        parts = []
        for i in range(total):
            time.sleep(0.3)
            parts.append(
                f"# PaddleOCR 识别结果 · 第 {i + 1} 页\n\n"
                f"这是 **mock 模式**下的 PaddleOCR 输出。\n\n"
                f"- 引擎：PaddleOCR PP-StructureV3（假数据）\n"
                f"- 本页共识别 3 个版面块\n\n"
                f"| 字段 | 值 |\n| --- | --- |\n| 引擎 | PaddleOCR |\n| 模式 | mock |\n\n"
                f"示例图片：<img src=\"{rel_img}\" />\n"
            )
            progress(i + 1, total, f"第 {i + 1}/{total} 页完成")
        return PAGE_SEPARATOR.join(parts)
