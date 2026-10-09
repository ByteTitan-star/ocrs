"""Mock 引擎：不加载真实模型，生成可区分的假 Markdown，用于跑通全流程与联调前端。

两个 mock 输出刻意有差异（错字/顺序），便于检验 Diff 视图效果。
digital 引擎本身无模型，mock 模式下直接复用真实实现，仅改标签。
"""
import time
from pathlib import Path

from ..pdf_utils import count_pages
from .base import OcrEngine, PageRange, ProgressFn, append_page_markdown
from .digital import DigitalEngine


def _page_numbers(pdf_path: Path, page_range: PageRange) -> list[int]:
    """分片感知的页码序列（绝对页码）。"""
    total = count_pages(pdf_path)
    start, end = page_range or (0, total)
    return list(range(start, min(end, total)))


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


class MockDigitalEngine(DigitalEngine):
    label = "文字层直提 (mock)"


class MockDotsEngine(OcrEngine):
    name = "dots"
    label = "dots.ocr (mock)"

    def availability(self) -> tuple[bool, str]:
        return True, "mock 模式"

    def _load(self) -> None:
        time.sleep(0.3)

    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn,
             page_range: PageRange = None) -> str:
        rel_img = _write_demo_image(work_dir)
        pages = _page_numbers(pdf_path, page_range)
        for done, i in enumerate(pages):
            time.sleep(0.4)
            page_md = (
                f"# dots.ocr 识别结果 · 第 {i + 1} 页\n\n"
                f"这是 **mock 模式**下的 dots.ocr 输出，用于演示对比界面。\n\n"
                f"- 引擎：dots.ocr（假数据）\n"
                f"- 本页共识别 3 个版面块\n\n"
                f"| 字段 | 值 |\n| --- | --- |\n| 引擎 | dots.ocr |\n| 模式 | mock |\n\n"
                f"示例图片：![]({rel_img})\n"
            )
            append_page_markdown(work_dir, page_md)
            progress(done + 1, len(pages), f"第 {i + 1} 页完成")
        return ""


class MockPaddleEngine(OcrEngine):
    name = "paddle"
    label = "PaddleOCR (mock)"

    def availability(self) -> tuple[bool, str]:
        return True, "mock 模式"

    def _load(self) -> None:
        time.sleep(0.2)

    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn,
             page_range: PageRange = None) -> str:
        rel_img = _write_demo_image(work_dir)
        pages = _page_numbers(pdf_path, page_range)
        for done, i in enumerate(pages):
            time.sleep(0.3)
            page_md = (
                f"# PaddleOCR 识别结果 · 第 {i + 1} 页\n\n"
                f"这是 **mock 模式**下的 PaddleOCR 输出。\n\n"
                f"- 引擎：PaddleOCR PP-StructureV3（假数据）\n"
                f"- 本页共识别 3 个版面块\n\n"
                f"| 字段 | 值 |\n| --- | --- |\n| 引擎 | PaddleOCR |\n| 模式 | mock |\n\n"
                f"示例图片：<img src=\"{rel_img}\" />\n"
            )
            append_page_markdown(work_dir, page_md)
            progress(done + 1, len(pages), f"第 {i + 1} 页完成")
        return ""
