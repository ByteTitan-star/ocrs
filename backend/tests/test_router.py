"""路由层测试：文字页 / 纯图片页（扫描件）/ 劣质文字层页 三类样本的判定。"""
import fitz

from app.router import DIGITAL, SCANNED, classify_pages, printable_ratio, route_report

# 模拟老扫描件内嵌的劣质 OCR 文字层：私有区字符 + 控制字符
GARBAGE = "\uf062\uf063" + chr(0) + chr(1) + chr(2)


def make_pdf(pages: list) -> bytes:
    """按页生成 PDF：字符串为该页文字层内容，None 表示纯图片页（无文字层）。"""
    doc = fitz.open()
    img = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 80))  # 纯色位图，模拟扫描图片
    for content in pages:
        page = doc.new_page()
        if content is not None:
            page.insert_text((48, 72), content, fontname="helv", fontsize=11)
        else:
            page.insert_image(page.rect, pixmap=img)
    data = doc.tobytes()
    doc.close()
    return data


def write_pdf(tmp_path, pages) -> object:
    path = tmp_path / "sample.pdf"
    path.write_bytes(make_pdf(pages))
    return path


def test_printable_ratio():
    assert printable_ratio("Hello 世界 123") == 1.0
    assert printable_ratio("") == 0.0
    assert printable_ratio(GARBAGE) < 0.6  # 私有区/控制字符 → 判劣质


def test_classify_mixed_pages(tmp_path):
    pdf = write_pdf(tmp_path, [
        "Selection-Aware Poisoning: Boosting Clean-Label Backdoor Attacks",  # 文字页
        None,                                                                # 扫描页
        "short",                                                             # 字符数不足 → 扫描页
    ])
    routes = classify_pages(pdf)
    assert [r.route for r in routes] == [DIGITAL, SCANNED, SCANNED]
    assert routes[0].page == 0 and routes[1].chars == 0


def test_garbage_text_layer_is_scanned(tmp_path):
    """字符数够但可打印占比过低的文字层，不应误判为 digital。

    注：fitz 会把私有区字符归一成可打印的「·」，因此这里用控制字符构造劣质样本。
    """
    garbage = chr(0) * 30 + "x" * 5  # 35 字符中仅 5 个可打印
    pdf = write_pdf(tmp_path, [garbage])
    assert classify_pages(pdf)[0].route == SCANNED


def test_classify_page_range(tmp_path):
    pdf = write_pdf(tmp_path, ["page one text", "page two text", "page three text"])
    routes = classify_pages(pdf, page_range=(1, 3))
    assert [r.page for r in routes] == [1, 2]
    assert all(r.route == DIGITAL for r in routes)


def test_route_report(tmp_path):
    pdf = write_pdf(tmp_path, ["normal text page", None])
    report = route_report(classify_pages(pdf))
    assert report["digital"] == [0]
    assert report["scanned"] == [1]
    assert report["pages"][0]["chars"] > 0
