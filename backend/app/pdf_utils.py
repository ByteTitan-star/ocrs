"""PDF 基础工具：页数统计、页图渲染、结果 Markdown 中相对图片链接的重写。"""
import re
from pathlib import Path
from typing import Iterator, List, Optional, Tuple
from urllib.parse import quote

import fitz  # PyMuPDF
from PIL import Image

PAGE_SEPARATOR = "\n\n---\n\n"

# 渲染边长上限（像素）：超过则回退 72dpi 渲染，防止超大页爆内存（与 vendor dots_ocr 一致）
MAX_RENDER_EDGE = 4500


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


def render_page_image(page: "fitz.Page", dpi: int = 200) -> Image.Image:
    """单页渲染为 RGB PIL 图像；边长超上限的巨型页降采样到 72dpi。"""
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
    if pix.width > MAX_RENDER_EDGE or pix.height > MAX_RENDER_EDGE:
        pix = page.get_pixmap(alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def iter_page_images(pdf_path: Path, dpi: int = 200,
                     page_range: Optional[Tuple[int, int]] = None) -> Iterator[Tuple[int, Image.Image]]:
    """逐页懒渲染生成器：内存中同时只保留一页，替代一次性渲染整本的 load_images_from_pdf。

    yield (绝对页码, 图像)；page_range 为 [start, end)。
    """
    with fitz.open(pdf_path) as doc:
        start, end = page_range or (0, doc.page_count)
        for i in range(start, min(end, doc.page_count)):
            yield i, render_page_image(doc[i], dpi)


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
