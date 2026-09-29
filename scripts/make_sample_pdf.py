#!/usr/bin/env python
"""生成一份 3 页的样例 PDF（中文 + 英文 + 表格 + 页眉页脚），用于快速验证两个 OCR 引擎。"""
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/sample.pdf"


def page_chinese(doc: fitz.Document) -> None:
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(60, 60, 535, 110), "多模态文档识别技术综述\n",
                        fontname="china-s", fontsize=20, align=fitz.TEXT_ALIGN_CENTER)
    body = (
        "光学字符识别（OCR）是文档数字化的核心技术。传统的两阶段流水线需要分别完成"
        "版面分析、文本检测与文本识别，各模块误差会不断累积。\n"
        "近年来，视觉语言模型将上述流程统一到单个端到端模型中，直接输出结构化的 Markdown，"
        "显著降低了系统复杂度，并在表格、公式等复杂版面元素上取得了更好的效果。\n"
    )
    page.insert_textbox(fitz.Rect(60, 130, 535, 300), body, fontname="china-s", fontsize=12, lineheight=1.8)
    page.insert_textbox(fitz.Rect(60, 310, 535, 430),
                        "本文的主要贡献如下：\n"
                        "1. 提出统一的多语种文档版面解析方法；\n"
                        "2. 在 100 种语言上验证了模型效果；\n"
                        "3. 开源了全部训练代码与模型权重。",
                        fontname="china-s", fontsize=12, lineheight=1.8)


def page_english_table(doc: fitz.Document) -> None:
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(60, 55, 535, 90), "Benchmark Results\n",
                        fontname="helv", fontsize=18, align=fitz.TEXT_ALIGN_CENTER)
    rows = [
        ["Model", "Params", "Avg Score", "Languages"],
        ["dots.ocr", "3B", "92.4", "100"],
        ["PP-StructureV3", "-", "90.1", "10+"],
        ["Baseline", "7B", "89.7", "20"],
    ]
    x0, y0, col_w, row_h = 70, 120, [150, 90, 110, 130], 26
    for r, row in enumerate(rows):
        x = x0
        for c, cell in enumerate(row):
            rect = fitz.Rect(x, y0 + r * row_h, x + col_w[c], y0 + (r + 1) * row_h)
            page.draw_rect(rect, color=(0.2, 0.2, 0.2), width=0.7)
            page.insert_textbox(fitz.Rect(x + 6, y0 + r * row_h + 6, x + col_w[c] - 4, y0 + (r + 1) * row_h),
                                cell, fontname="helv", fontsize=11)
            x += col_w[c]
    page.insert_textbox(fitz.Rect(60, 250, 535, 400),
                        "Table 1: Evaluation on the multilingual document parsing benchmark. "
                        "Higher is better. The unified model achieves the best trade-off "
                        "between accuracy and inference cost.",
                        fontname="helv", fontsize=11, lineheight=1.6)


def page_header_footer(doc: fitz.Document) -> None:
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(60, 35, 535, 55), "arXiv:2507.00000v1  [cs.CV]  1 Jul 2025",
                        fontname="helv", fontsize=9)
    page.insert_textbox(fitz.Rect(60, 70, 535, 105), "3 Related Work\n", fontname="helv", fontsize=15)
    page.insert_textbox(fitz.Rect(60, 115, 535, 320),
                        "Document parsing has long been formulated as a pipeline of independent "
                        "modules. Early systems relied on hand-crafted features and template "
                        "matching, while modern approaches adopt deep neural networks for each "
                        "sub-task. However, cascaded systems suffer from error propagation and "
                        "require careful engineering to combine.\n\n"
                        "Given a query image q and support set S, few-shot classification "
                        "computes p(y | q, S) = softmax(sim(q, s_i)).",
                        fontname="helv", fontsize=11, lineheight=1.7)
    page.insert_textbox(fitz.Rect(60, 750, 535, 775), "Proceedings of OCR Comparison, 2025    3",
                        fontname="helv", fontsize=9)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page_chinese(doc)
    page_english_table(doc)
    page_header_footer(doc)
    doc.save(str(OUT))
    print(f"样例 PDF 已生成：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
