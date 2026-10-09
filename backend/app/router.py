"""页面路由：逐页判定走文字层直接抽取（digital）还是 OCR（scanned）。

生产管线的第一级：有文字层的页直接抽取既快又零误差，只有扫描页才值得花 OCR 算力。
质量分用于拦截老扫描件内嵌的劣质 OCR 文字层（字符数少、不可打印字符占比高）。
"""
from dataclasses import asdict, dataclass
from pathlib import Path

import fitz

# 低于该有效字符数视为无文字层（页眉页脚噪声除外）
MIN_TEXT_CHARS = 8
# 可打印字符占比下限：私有区/控制字符占比过高的文字层视为劣质
MIN_PRINTABLE_RATIO = 0.6

DIGITAL = "digital"
SCANNED = "scanned"


@dataclass
class PageRoute:
    page: int  # 0-based 绝对页码
    route: str  # DIGITAL | SCANNED
    chars: int  # 文字层字符数
    printable: float  # 可打印字符占比 0~1


def printable_ratio(text: str) -> float:
    """字母/数字/标点/常见符号占比；私有区、控制字符等不计入。"""
    if not text:
        return 0.0
    import unicodedata
    good = sum(
        1 for ch in text
        if unicodedata.category(ch)[0] in "LNZPS"  # Letter Number Separator Punctuation Symbol
    )
    return good / len(text)


def classify_pages(pdf_path: Path, page_range: tuple[int, int] | None = None) -> list[PageRoute]:
    """逐页判定路由。page_range 为 [start, end) 绝对页码区间，None 表示整本。"""
    routes: list[PageRoute] = []
    with fitz.open(pdf_path) as doc:
        start, end = page_range or (0, doc.page_count)
        for i in range(start, min(end, doc.page_count)):
            text = doc[i].get_text("text").strip()
            ratio = printable_ratio(text)
            route = DIGITAL if len(text) >= MIN_TEXT_CHARS and ratio >= MIN_PRINTABLE_RATIO else SCANNED
            routes.append(PageRoute(page=i, route=route, chars=len(text), printable=round(ratio, 4)))
    return routes


def route_report(routes: list[PageRoute]) -> dict:
    """路由判定汇总，落盘为 route.json 供后续只对扫描页发起 OCR 任务。"""
    return {
        "pages": [asdict(r) for r in routes],
        "digital": [r.page for r in routes if r.route == DIGITAL],
        "scanned": [r.page for r in routes if r.route == SCANNED],
    }
