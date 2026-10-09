#!/usr/bin/env python
"""金标回归评测：识别结果 result.md 对金标 golden.md 按页计算 CER。

金标集约定：data/golden/<文档名>/golden.md 为人工校对结果，与引擎输出同名页对齐。
CI/管线改动前后各跑一次，CER 超阈值退出码非零。

用法：
  python scripts/eval_golden.py data/tasks/<id>/dots/result.md data/golden/<doc>/golden.md
  python scripts/eval_golden.py result.md golden.md --cer 0.05 --verbose
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.eval_cer import page_cer_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="识别结果 vs 金标的逐页 CER 评测")
    parser.add_argument("result", type=Path, help="识别结果 result.md")
    parser.add_argument("golden", type=Path, help="金标 golden.md（页间以 --- 分隔）")
    parser.add_argument("--cer", type=float, default=0.05, dest="threshold",
                        help="全文 CER 阈值，超过则退出码 1（默认 0.05）")
    parser.add_argument("--verbose", action="store_true", help="打印逐页明细")
    args = parser.parse_args()

    report = page_cer_report(
        args.result.read_text(encoding="utf-8"),
        args.golden.read_text(encoding="utf-8"),
    )
    if args.verbose:
        print(f"{'页':>4} {'CER':>8} {'金标字符':>8} {'结果字符':>8}")
        for p in report["pages"]:
            print(f"{p['page'] + 1:>4} {p['cer']:>8.4f} {p['ref_chars']:>8} {p['hyp_chars']:>8}")
    verdict = "PASS" if report["cer"] <= args.threshold else "FAIL"
    print(f"[eval] 全文 CER = {report['cer']:.4f}（阈值 {args.threshold}，共 {report['page_count']} 页）→ {verdict}")
    return 0 if report["cer"] <= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
