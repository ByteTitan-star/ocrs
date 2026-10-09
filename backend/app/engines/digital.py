"""digital 引擎：文字层直接结构化抽取（PyMuPDF），生产管线中的「零成本快路径」。

有文字层的页不 OCR——快几个数量级且零识别误差；扫描页输出占位标记，
路由判定汇总落盘 route.json，据此可只对扫描页发起 dots/paddle 分片任务。
阅读顺序按文本块坐标（先 y 后 x）排序，多栏版面为启发式近似。
"""
import json
from pathlib import Path

import fitz

from .. import router
from .base import OcrEngine, PageRange, ProgressFn, append_page_markdown

# 与正文中位数字号之比达到该值的文本块视为标题
HEADING_SIZE_RATIO = 1.3


def _page_markdown(page: "fitz.Page") -> str:
    """按块抽取文字层：中位数字号为正文基准，大字号短块标为二级标题。"""
    doc_dict = page.get_text("dict")
    blocks = [b for b in doc_dict["blocks"] if b["type"] == 0]
    sizes = sorted(
        s["size"] for b in blocks for l in b["lines"] for s in l["spans"] if s["text"].strip())
    if not sizes:
        return ""
    body_size = sizes[len(sizes) // 2]

    parts: list[str] = []
    for block in sorted(blocks, key=lambda b: (round(b["bbox"][1]), b["bbox"][0])):
        text = "\n".join(
            "".join(s["text"] for s in line["spans"]) for line in block["lines"]).strip()
        if not text:
            continue
        block_sizes = [s["size"] for l in block["lines"] for s in l["spans"] if s["text"].strip()]
        if block_sizes and max(block_sizes) >= body_size * HEADING_SIZE_RATIO:
            parts.append("## " + text.replace("\n", " "))
        else:
            parts.append(text)
    return "\n\n".join(parts)


class DigitalEngine(OcrEngine):
    name = "digital"
    label = "文字层直提 (PyMuPDF)"
    setup_hint = "无需安装，PyMuPDF 随主依赖提供"

    def availability(self) -> tuple[bool, str]:
        return True, "文字层直提 · 无需模型加载"

    def _load(self) -> None:
        pass  # 无模型

    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn,
             page_range: PageRange = None) -> str:
        routes = router.classify_pages(pdf_path, page_range=page_range)
        report = router.route_report(routes)
        (work_dir / "route.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

        total = len(routes)
        with fitz.open(pdf_path) as doc:
            for done, r in enumerate(routes):
                if r.route == router.DIGITAL:
                    page_md = _page_markdown(doc[r.page])
                    note = "抽取完成"
                else:
                    page_md = (f"<!-- 第 {r.page + 1} 页无文字层"
                               f"（{r.chars} 字符，可打印 {r.printable:.0%}），需 OCR -->")
                    note = "无文字层，已标记待 OCR"
                append_page_markdown(work_dir, page_md)
                progress(done + 1, total, f"第 {r.page + 1} 页{note}")
        return ""
