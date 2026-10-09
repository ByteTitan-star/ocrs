#!/usr/bin/env python
"""跨平台环境预检（doctor）：在任何新机器上跑任务之前，一条命令确认
「每个引擎将以什么设备运行、依赖与权重是否就绪、有没有装错版本的组合」。

用法：
  python scripts/check_env.py            # 静态检查（秒级，不加载模型权重）
  python scripts/check_env.py --smoke    # 深度自检：每个引擎真跑一页（会加载模型，较慢）
  python scripts/check_env.py --json     # 机器可读输出

退出码：所有启用引擎可用为 0，否则 1（可挂 CI/部署前检查）。
"""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config as cfg  # noqa: E402
from app.engines import create_engine  # noqa: E402
from app.env_check import (engine_report, gpu_warnings, paddle_info,  # noqa: E402
                           system_summary, torch_info)


def smoke_test(engine, tmp: Path) -> tuple[bool, str]:
    """深度自检：生成 1 页微型 PDF 真跑一遍（加载模型、完整推理）。"""
    import fitz

    pdf = tmp / "smoke.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((48, 72), "smoke test 123", fontname="helv", fontsize=12)
    doc.save(pdf)
    doc.close()
    work = tmp / f"work_{engine.name}"
    work.mkdir()
    started = time.time()
    engine.run(pdf, work, page_range=(0, 1))
    md = work / "result.md"
    ok = md.is_file()
    return ok, f"{time.time() - started:.0f}s 出稿 {md.stat().st_size if ok else 0} 字符"


def main() -> int:
    parser = argparse.ArgumentParser(description="ocrs 跨平台环境预检")
    parser.add_argument("--smoke", action="store_true",
                        help="深度自检：每引擎真跑一页（加载模型，dots 可能需要数分钟）")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON 输出")
    args = parser.parse_args()

    torch_i, paddle_i = torch_info(), paddle_info()
    warnings = gpu_warnings(torch_i, paddle_i)
    reports = []
    for name in cfg.ENGINES:
        try:
            engine = create_engine(name)
        except ValueError as exc:  # 未注册引擎
            reports.append({"name": name, "available": False, "detail": str(exc), "device": ""})
            continue
        reports.append(engine_report(engine))
        if args.smoke and reports[-1]["available"]:
            try:
                ok, note = smoke_test(engine, Path(tempfile.mkdtemp(prefix="ocrs-smoke-")))
                reports[-1]["smoke"] = "PASS · " + note if ok else "FAIL · " + note
            except Exception as exc:  # noqa: BLE001
                reports[-1]["smoke"] = f"FAIL · {type(exc).__name__}: {exc}"

    if args.as_json:
        print(json.dumps({"system": system_summary(), "torch": torch_i, "paddle": paddle_i,
                          "warnings": warnings, "engines": reports,
                          "smoke": args.smoke}, ensure_ascii=False, indent=1))
    else:
        print(f"[env] {system_summary()}")
        if torch_i:
            gpu = torch_i["name"] or ("MPS" if torch_i["mps"] else "-")
            print(f"[env] torch {torch_i['version']} · CUDA构建={torch_i['cuda_build'] or '无'} · "
                  f"{torch_i['device']}" + (f"（{gpu} {torch_i['vram_gb']}GB）" if torch_i["cuda"] else f"（{gpu}）"))
        if paddle_i:
            print(f"[env] paddle {paddle_i['version']} · CUDA构建={paddle_i['cuda_build']} · {paddle_i['device']}"
                  + (f"（{paddle_i['name']}）" if paddle_i["cuda"] else ""))
        for w in warnings:
            print(f"[warn] {w}")
        for r in reports:
            mark = "OK " if r["available"] else "BAD"
            line = f"[{mark}] {r['name']:8} {r['detail']}"
            if r.get("device"):
                line += f" · {r['device']}"
            if r.get("smoke"):
                line += f" · 自检: {r['smoke']}"
            print(line)

    return 0 if all(r["available"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
