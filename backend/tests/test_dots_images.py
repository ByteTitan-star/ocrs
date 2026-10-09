"""dots.ocr 图片提取测试：base64 内联图片解码落盘并改写为相对路径。"""
import base64

from app.engines.dots import extract_data_uri_images

# 1x1 红色像素 PNG
_PNG_1PX = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082"
)).decode()


def test_extract_data_uri_images(tmp_path):
    md = (f"前文段落。\n\n![](data:image/png;base64,{_PNG_1PX})\n\n"
          f"![](data:image/png;base64,{_PNG_1PX})\n\n后文段落。")
    out = extract_data_uri_images(tmp_path, md, page_no=4)  # 第 5 页
    assert "base64" not in out
    assert out.count("images/dots_p0005_") == 2  # 绝对页码命名 + 递增序号
    files = sorted(p.name for p in (tmp_path / "images").glob("dots_p0005_*.png"))
    assert files == ["dots_p0005_01.png", "dots_p0005_02.png"]
    assert (tmp_path / "images" / files[0]).stat().st_size > 0  # 解码出真实文件
    assert "前文段落。" in out and "后文段落。" in out  # 其余 markdown 原样保留


def test_extract_keeps_plain_markdown(tmp_path):
    md = "没有图片的页面。\n\n![](images/已有引用.png)"
    assert extract_data_uri_images(tmp_path, md, page_no=0) == md
    assert not (tmp_path / "images").exists()
