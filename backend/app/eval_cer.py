"""字符错误率（CER）与按页对比：识别结果对金标的回归评测指标。

任何管线改动（换引擎/换 profile/换 DPI）都应先跑金标集对比，CER 超阈值即回归失败。
"""
import re
from dataclasses import dataclass

from .pdf_utils import PAGE_SEPARATOR


def normalize(text: str) -> str:
    """空白归一：连续空白折叠为单空格（Markdown 换行/缩进差异不应计为错误）。"""
    return re.sub(r"\s+", " ", text).strip()


def edit_distance(a: str, b: str) -> int:
    """Levenshtein 距离（两行 DP）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(hyp: str, ref: str) -> float:
    """字符错误率：编辑距离 / 金标字符数。"""
    hyp, ref = normalize(hyp), normalize(ref)
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(hyp, ref) / len(ref)


@dataclass
class PageCer:
    page: int
    cer: float
    ref_chars: int
    hyp_chars: int


def page_cer_report(hyp_markdown: str, ref_markdown: str) -> dict:
    """按页分隔线对齐对比，返回逐页 CER 与全文加权 CER。页数不齐时缺失页计满分错误。"""
    hyp_pages = hyp_markdown.split(PAGE_SEPARATOR)
    ref_pages = ref_markdown.split(PAGE_SEPARATOR)
    total = max(len(hyp_pages), len(ref_pages))
    pages: list[PageCer] = []
    total_dist = total_ref = 0
    for i in range(total):
        hyp = hyp_pages[i] if i < len(hyp_pages) else ""
        ref = ref_pages[i] if i < len(ref_pages) else ""
        dist = edit_distance(normalize(hyp), normalize(ref))
        ref_len = len(normalize(ref))
        total_dist += dist
        total_ref += ref_len
        pages.append(PageCer(page=i, cer=dist / ref_len if ref_len else (0.0 if not hyp else 1.0),
                             ref_chars=ref_len, hyp_chars=len(normalize(hyp))))
    return {
        "pages": [vars(p) for p in pages],
        "cer": total_dist / total_ref if total_ref else 0.0,
        "page_count": total,
    }
