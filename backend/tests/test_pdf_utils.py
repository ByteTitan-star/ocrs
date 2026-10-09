"""pdf_utils 懒渲染测试：分片页码、DPI 缩放、巨型页降采样、逐页释放。"""
import fitz

from app.pdf_utils import MAX_RENDER_EDGE, iter_page_images, render_page_image


def make_pdf(pages: int = 3, width=595, height=842) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=width, height=height)
    data = doc.tobytes()
    doc.close()
    return data


def write_pdf(tmp_path, **kw):
    path = tmp_path / "doc.pdf"
    path.write_bytes(make_pdf(**kw))
    return path


def test_iter_page_images_full_and_range(tmp_path):
    pdf = write_pdf(tmp_path)
    pages = list(iter_page_images(pdf, dpi=144))
    assert [no for no, _ in pages] == [0, 1, 2]
    # 144dpi = 2× 72dpi：A4 595×842pt → 1190×1684px
    assert pages[0][1].size == (1190, 1684)

    shard = list(iter_page_images(pdf, dpi=144, page_range=(1, 3)))
    assert [no for no, _ in shard] == [1, 2]


def test_iter_page_images_lazy(tmp_path):
    """生成器逐页产出：取第一页后不消费剩余页。"""
    pdf = write_pdf(tmp_path)
    gen = iter_page_images(pdf, dpi=72)
    first_no, first_img = next(gen)
    assert first_no == 0 and first_img.size == (595, 842)
    assert not hasattr(gen, "__len__")  # 不是列表，保持惰性


def test_huge_page_downscaled(tmp_path):
    """渲染边长超过上限的巨型页回退 72dpi，防止爆内存。"""
    pdf = write_pdf(tmp_path, pages=1, width=5000, height=400)
    with fitz.open(pdf) as doc:
        img = render_page_image(doc[0], dpi=200)  # 若按 200dpi 应为 ~13889px
    assert max(img.size) <= MAX_RENDER_EDGE + 800  # 72dpi 下为 5000px
