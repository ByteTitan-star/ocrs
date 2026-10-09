"""切块器测试：cells 切块（合并/拆散/标题上下文）、dots pages 目录消费、markdown 兜底、脚本冒烟。"""
import json
import subprocess
import sys
from pathlib import Path

from app.chunker import (DEFAULT_MAX_CHARS, chunk_cells, chunk_dots_pages,
                         chunk_markdown, _split_long_text)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/chunk_result.py"


def cell(category, text, bbox=(0, 0, 100, 20)):
    return {"category": category, "text": text, "bbox": list(bbox)}


def test_merge_adjacent_text_blocks():
    cells = [
        cell("Title", "第一章 概述"),
        cell("Text", "第一段内容。", (0, 30, 100, 50)),
        cell("Text", "第二段内容。", (0, 60, 100, 80)),
    ]
    chunks, _ = chunk_cells(cells, page=0, doc_id="doc1")
    assert len(chunks) == 2  # 标题 1 块 + 合并后的文本 1 块
    assert chunks[0]["category"] == "Title"
    merged = chunks[1]
    assert "第一段内容。" in merged["text"] and "第二段内容。" in merged["text"]
    assert merged["heading"] == "第一章 概述"  # 标题上下文注入
    assert merged["bbox"] == [0, 30, 100, 80]  # bbox 联合


def test_structural_blocks_not_merged_or_split():
    table_md = "| a | b |\n| --- | --- |\n| 1 | 2 |" * 10
    cells = [cell("Text", "前文。"), cell("Table", table_md), cell("Formula", "$E=mc^2$")]
    chunks, _ = chunk_cells(cells, page=3, doc_id="d")
    categories = [c["category"] for c in chunks]
    assert categories == ["Text", "Table", "Formula"]
    assert all(c["page"] == 3 for c in chunks)


def test_long_text_split_by_paragraph():
    para = "甲" * 300
    text = "\n\n".join([para, para, para, para, para])  # 1500+ 字符，段落 300
    pieces = _split_long_text(text, DEFAULT_MAX_CHARS)
    assert all(len(p) <= DEFAULT_MAX_CHARS for p in pieces)
    assert sum(len(p) for p in pieces) >= 1500

    cells = [cell("Text", text)]
    chunks, _ = chunk_cells(cells, page=0)
    assert len(chunks) > 1
    assert all(c["category"] == "Text" for c in chunks)


def test_chunk_dots_pages_with_heading_carry(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "page_0001.json").write_text(json.dumps([
        cell("Title", "第二章 方法"), cell("Text", "方法正文第一页。")], ensure_ascii=False),
        encoding="utf-8")
    (pages / "page_0002.json").write_text(json.dumps([
        cell("Text", "方法正文第二页。")], ensure_ascii=False), encoding="utf-8")
    (pages / "page_0003.json").write_text("{ 坏掉的 JSON", encoding="utf-8")  # 容错：跳过

    chunks = list(chunk_dots_pages(pages, doc_id="paper"))
    assert len(chunks) == 3  # 第 1 页标题+正文两块，第 2 页正文一块，第 3 页损坏跳过
    assert chunks[0]["page"] == 0 and chunks[1]["page"] == 0 and chunks[2]["page"] == 1
    assert chunks[2]["heading"] == "第二章 方法"  # 标题上下文跨页传递


def test_chunk_markdown_fallback():
    md = "# 大标题\n\n第一段。\n\n---\n\n## 第二节\n\n第二页正文。"
    chunks = chunk_markdown(md, doc_id="m")
    assert [(c["page"], c["heading"]) for c in chunks] == [(0, "大标题"), (1, "第二节")]
    assert chunks[0]["bbox"] is None


def test_chunk_result_script(tmp_path):
    work = tmp_path / "dots"
    (work / "pages").mkdir(parents=True)
    (work / "pages/page_0001.json").write_text(
        json.dumps([cell("Title", "标题"), cell("Text", "正文。")], ensure_ascii=False),
        encoding="utf-8")
    (work / "result.md").write_text("# 标题\n\n正文。", encoding="utf-8")

    out = tmp_path / "chunks.jsonl"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(work), "--doc-id", "smoke", "-o", str(out)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert all(c["doc_id"] == "smoke" for c in lines)
