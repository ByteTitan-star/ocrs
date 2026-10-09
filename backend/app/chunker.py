"""切块器：把版面解析结果切成带溯源元数据的 chunk，供向量库入库。

切块在布局 JSON（dots cells）上进行，而非二次解析 Markdown：每块携带
doc/page/bbox/category/heading 上下文；表格/公式保持结构化表达不拆散、不合并；
相邻小文本块合并到上限，超长块按段落切分。Markdown 仅为兜底路径。
"""
import json
import re
from pathlib import Path
from typing import Iterator, Optional

from .pdf_utils import PAGE_SEPARATOR

# dots.ocr 布局类别
HEADING_CATEGORIES = {"Title", "Section-header"}
STRUCTURAL_CATEGORIES = {"Table", "Formula", "Picture"}  # 不拆散、不合并
MERGEABLE_CATEGORIES = {"Text", "Caption", "List-item", "Footnote", "Page-header", "Page-footer"}

DEFAULT_MAX_CHARS = 1200
HEADING_CONTEXT_LIMIT = 120  # 标题作为 chunk 上下文的最大长度


def _union_bbox(a: Optional[list], b: Optional[list]) -> Optional[list]:
    if a is None:
        return b
    if b is None:
        return a
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _split_long_text(text: str, max_chars: int) -> list[str]:
    """超长文本按空行段落聚合切分；单个无空行段落硬切。"""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    buf = ""
    for para in (p for p in re.split(r"\n\s*\n", text) if p.strip()):
        if buf and len(buf) + len(para) + 2 > max_chars:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    hard_split: list[str] = []
    for chunk in chunks:
        while len(chunk) > max_chars:
            hard_split.append(chunk[:max_chars])
            chunk = chunk[max_chars:]
        if chunk:
            hard_split.append(chunk)
    return hard_split


def _chunk(doc_id: str, page: int, category: str, heading: str, bbox, text: str) -> dict:
    return {"doc_id": doc_id, "page": page, "category": category,
            "heading": heading, "bbox": bbox, "text": text}


def chunk_cells(cells: list[dict], *, page: int, doc_id: str = "",
                max_chars: int = DEFAULT_MAX_CHARS, heading: str = "") -> tuple[list[dict], str]:
    """单页布局 cells → chunks。返回 (chunks, 最新标题)，heading 跨块/跨页传递标题上下文。"""
    results: list[dict] = []
    buf_text = ""
    buf_bbox: Optional[list] = None

    def flush() -> None:
        nonlocal buf_text, buf_bbox
        if buf_text.strip():
            for piece in _split_long_text(buf_text.strip(), max_chars):
                results.append(_chunk(doc_id, page, "Text", heading, buf_bbox, piece))
        buf_text, buf_bbox = "", None

    for cell in cells:
        category = cell.get("category") or "Other"
        text = (cell.get("text") or "").strip()
        bbox = cell.get("bbox")
        if not text:
            continue
        if category in HEADING_CATEGORIES:
            flush()
            heading = text.replace("\n", " ")[:HEADING_CONTEXT_LIMIT]
            results.append(_chunk(doc_id, page, category, "", bbox, text))
        elif category in STRUCTURAL_CATEGORIES:
            flush()  # 表格/公式/图片自成一块，不被文本吸收或拆散
            results.append(_chunk(doc_id, page, category, heading, bbox, text))
        elif category in MERGEABLE_CATEGORIES:
            if buf_text and len(buf_text) + len(text) + 2 > max_chars:
                flush()
            buf_text = f"{buf_text}\n\n{text}" if buf_text else text
            buf_bbox = _union_bbox(buf_bbox, bbox)
        else:  # Unknown/Other：不合并，单独成块
            flush()
            results.append(_chunk(doc_id, page, category, heading, bbox, text))
    flush()
    return results, heading


def chunk_dots_pages(pages_dir: Path, doc_id: str = "",
                     max_chars: int = DEFAULT_MAX_CHARS) -> Iterator[dict]:
    """消费 dots 引擎的 pages/page_XXXX.json 存档，逐页切块（标题上下文跨页传递）。"""
    heading = ""
    for page_json in sorted(pages_dir.glob("page_*.json")):
        page_no = int(page_json.stem.split("_")[-1]) - 1
        try:
            cells = json.loads(page_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # 损坏的单页存档跳过，不阻塞整批入库
        chunks, heading = chunk_cells(cells, page=page_no, doc_id=doc_id,
                                      max_chars=max_chars, heading=heading)
        yield from chunks


_HEADING_RE = re.compile(r"(?m)^(#{1,6} .+)$")


def chunk_markdown(markdown: str, doc_id: str = "",
                   max_chars: int = DEFAULT_MAX_CHARS) -> list[dict]:
    """兜底路径：无布局 JSON 时按页分隔线 + 标题切分 Markdown，无 bbox/粗粒度类别。"""
    chunks: list[dict] = []
    for page_no, page_md in enumerate(markdown.split(PAGE_SEPARATOR)):
        heading = ""
        for section in _HEADING_RE.split(page_md):
            if _HEADING_RE.fullmatch(section.strip()):
                heading = section.lstrip("# ").strip()[:HEADING_CONTEXT_LIMIT]
            elif section.strip():
                for piece in _split_long_text(section.strip(), max_chars):
                    chunks.append(_chunk(doc_id, page_no, "Markdown", heading, None, piece))
    return chunks
