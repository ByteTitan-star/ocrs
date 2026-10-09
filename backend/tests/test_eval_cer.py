"""CER 评测测试：指标函数、按页对齐、页数不齐、阈值退出码。"""
import subprocess
import sys
from pathlib import Path

from app.eval_cer import cer, edit_distance, normalize, page_cer_report

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/eval_golden.py"


def test_edit_distance():
    assert edit_distance("", "") == 0
    assert edit_distance("abc", "abc") == 0
    assert edit_distance("abc", "abd") == 1  # 替换
    assert edit_distance("abc", "abcd") == 1  # 插入
    assert edit_distance("kitten", "sitting") == 3


def test_cer_basic():
    assert cer("同一份文本", "同一份文本") == 0.0
    assert abs(cer("abcdefghij", "abcxefghij")) == 0.1  # 10 字符 1 处替换
    # 空白差异不计错误
    assert cer("第一段\n\n第二段", "第一段 第二段") == 0.0
    assert cer("", "参考文本") == 1.0  # 全丢
    assert cer("有输出", "") == 1.0  # 金标为空却有输出


def test_page_cer_report_alignment():
    hyp = "第一页正确\n\n---\n\n第二页有错字\n\n---\n\n多余第三页"
    ref = "第一页正确\n\n---\n\n第二页有错入"
    report = page_cer_report(hyp, ref)
    assert report["page_count"] == 3
    assert report["pages"][0]["cer"] == 0.0
    assert 0 < report["pages"][1]["cer"] < 0.5
    assert report["pages"][2]["cer"] == 1.0  # 金标缺失页
    assert report["cer"] > 0


def test_normalize():
    assert normalize("  a\tb\n\nc  ") == "a b c"


def test_eval_golden_script(tmp_path):
    golden = tmp_path / "golden.md"
    result = tmp_path / "result.md"
    golden.write_text("完全一致的内容\n\n---\n\n第二页", encoding="utf-8")
    result.write_text("完全一致的内容\n\n---\n\n第二页", encoding="utf-8")

    ok = subprocess.run([sys.executable, str(SCRIPT), str(result), str(golden)],
                        capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0 and "PASS" in ok.stdout

    result.write_text("完全一致的内容\n\n---\n\n完全不同的第二页", encoding="utf-8")
    strict = subprocess.run([sys.executable, str(SCRIPT), str(result), str(golden),
                             "--cer", "0.05", "--verbose"],
                            capture_output=True, text=True, timeout=60)
    assert strict.returncode == 1 and "FAIL" in strict.stdout
