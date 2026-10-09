"""分片协议测试：worker spec 解析、paddle page_indexes 透传、mock 引擎分片行为、
result.md 分片起点不带多余分隔线。"""
import fitz

from app.engines.mock import MockDotsEngine
from app.engines.paddle import PaddleEngine
from app.worker import _spec_page_range


def make_pdf(pages: int = 3) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def test_spec_page_range():
    assert _spec_page_range({"pdf": "x", "pages": 10}) is None
    assert _spec_page_range({"pdf": "x", "page_start": 5, "page_end": 9}) == (5, 9)


def test_mock_engine_honors_page_range(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(make_pdf(3))
    work = tmp_path / "work"
    work.mkdir()
    notes = []
    MockDotsEngine().run(pdf, work, lambda d, t, n: notes.append((d, t)),
                         page_range=(1, 3))
    result = (work / "result.md").read_text(encoding="utf-8")
    assert "第 2 页" in result and "第 3 页" in result
    assert "第 1 页" not in result
    assert notes[-1] == (2, 2)  # 分片内 2 页


class FakeResult:
    def __init__(self, page_no: int):
        self.markdown = {"markdown_texts": f"第{page_no}页内容", "markdown_images": {}}


class FakePipeline:
    def __init__(self, total_pages: int):
        self.total_pages = total_pages
        self.calls = []

    def predict(self, path, **kwargs):
        self.calls.append(kwargs)
        indexes = kwargs.get("page_indexes") or list(range(self.total_pages))
        return iter([FakeResult(i) for i in indexes])


def test_paddle_forwards_page_indexes(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(make_pdf(3))
    work = tmp_path / "work"
    work.mkdir()

    engine = PaddleEngine()
    engine.pipeline = FakePipeline(3)  # 绕过真实模型加载
    engine._loaded = True
    notes = []
    engine.run(pdf, work, lambda d, t, n: notes.append((d, t, n)), page_range=(1, 3))

    assert engine.pipeline.calls == [{"page_indexes": [1, 2]}]
    result = (work / "result.md").read_text(encoding="utf-8")
    # FakeResult 以页索引为内容：分片 [1,2) 的两页依序写入，首页无分隔线前缀
    assert result == "第1页内容\n\n---\n\n第2页内容"
    assert notes[-1][:2] == (2, 2)
    assert "第 3 页完成" in notes[-1][2]  # 进度说明用绝对页码


def test_paddle_whole_doc_no_page_indexes(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(make_pdf(2))
    work = tmp_path / "work"
    work.mkdir()

    engine = PaddleEngine()
    engine.pipeline = FakePipeline(2)
    engine._loaded = True
    engine.run(pdf, work, lambda *_: None)

    assert engine.pipeline.calls == [{}]  # 整本时不传 page_indexes
    result = (work / "result.md").read_text(encoding="utf-8")
    assert result == "第0页内容\n\n---\n\n第1页内容"
