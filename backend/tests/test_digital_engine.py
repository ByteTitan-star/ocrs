"""digital 引擎测试：文字页抽取（标题启发式）、扫描页占位、route.json 落盘、分片。"""
import json

import fitz

from app.engines.digital import DigitalEngine


def make_mixed_pdf() -> bytes:
    """第 1 页：大字号标题 + 正文；第 2 页：纯图片（无文字层）。"""
    doc = fitz.open()
    img = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 80))
    page = doc.new_page()
    page.insert_text((48, 60), "Big Title Here", fontname="helv", fontsize=22)
    page.insert_text((48, 110), "Normal body text line one.", fontname="helv", fontsize=11)
    page.insert_text((48, 130), "Normal body text line two.", fontname="helv", fontsize=11)
    doc.new_page().insert_image(doc[1].rect, pixmap=img)
    data = doc.tobytes()
    doc.close()
    return data


def run_engine(tmp_path, pdf_bytes, page_range=None):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(pdf_bytes)
    work = tmp_path / "work"
    work.mkdir()
    notes = []
    engine = DigitalEngine()
    assert engine.availability()[0] is True
    engine.run(pdf, work, progress=lambda d, t, n: notes.append((d, t, n)),
               page_range=page_range)
    result = (work / "result.md").read_text(encoding="utf-8")
    return work, result, notes


def test_extracts_text_layer_with_heading(tmp_path):
    work, result, notes = run_engine(tmp_path, make_mixed_pdf())
    assert "## Big Title Here" in result  # 大字号块被标为标题
    assert "Normal body text line one." in result
    assert "需 OCR" in result  # 第 2 页（纯图片）输出占位标记
    assert "---" in result  # 页间分隔线
    assert notes[-1] == (2, 2, "第 2 页无文字层，已标记待 OCR")

    route = json.loads((work / "route.json").read_text(encoding="utf-8"))
    assert route["digital"] == [0]
    assert route["scanned"] == [1]


def test_page_range_only_processes_shard(tmp_path):
    _, result, notes = run_engine(tmp_path, make_mixed_pdf(), page_range=(1, 2))
    assert "Big Title" not in result  # 第 1 页不在分片内
    assert "需 OCR" in result
    assert notes[-1][1] == 1  # 分片内共 1 页
    assert "第 1 页" not in str(notes)  # 进度用绝对页码


def test_result_md_separator_not_duplicated(tmp_path):
    _, result, _ = run_engine(tmp_path, make_mixed_pdf())
    assert result.count("---") == 1  # 恰好一条页分隔线
