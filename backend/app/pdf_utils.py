"""PDF 基础工具：页数统计、页图渲染、结果 Markdown 中相对图片链接的重写。"""
import re
from pathlib import Path
from typing import List
from urllib.parse import quote

import fitz  # PyMuPDF
from PIL import Image

PAGE_SEPARATOR = "\n\n---\n\n"


def count_pages(pdf_path: Path) -> int:
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def render_pages(pdf_path: Path, dpi: int = 150) -> List[Image.Image]:
    """把 PDF 每页渲染为 RGB PIL 图像。"""
    images: List[Image.Image] = []
    with fitz.open(pdf_path) as doc:
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return images


# ---- Markdown 相对图片链接重写 ----------------------------------------------
# PP-StructureV3 输出 <img src="images/xx.png">；也兼容 markdown 图片语法 ![](...)
_IMG_TAG_RE = re.compile(r'(<img\b[^>]*?\bsrc=")(?!https?://|/|data:)([^"]+)(")', re.IGNORECASE)
_MD_IMG_RE = re.compile(r'(!\[[^\]]*\]\()\s*(?!https?://|/|data:)([^)\s]+)\s*([)])')


def rewrite_relative_images(markdown: str, file_base_url: str) -> str:
    """把 Markdown 里的相对图片路径改写为可通过 /files 静态路由访问的绝对 URL。"""
    def _abs_url(rel: str) -> str:
        return f"{file_base_url.rstrip('/')}/{quote(rel.lstrip('./'))}"

    markdown = _IMG_TAG_RE.sub(lambda m: m.group(1) + _abs_url(m.group(2)) + m.group(3), markdown)
    markdown = _MD_IMG_RE.sub(lambda m: m.group(1) + _abs_url(m.group(2)) + m.group(3), markdown)
    return markdown
