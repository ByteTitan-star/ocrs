#!/usr/bin/env python
"""把大 PDF 按页区间切成小分片文件，并生成 manifest.json 供批量任务编排。

千万页级 PDF 的并行前提：先切分片，才能多 worker 并行、失败重试、断点续跑。
分片大小建议不超过服务的 OCRS_MAX_PAGES（默认 100），否则分片文件上传仍会被拒。

用法：
  python scripts/shard_pdf.py data/huge.pdf --size 100 -o data/shards/
  # 产出 huge.shard000000-000100.pdf … + manifest.json（含每片的绝对页码区间）
"""
import argparse
import json
from pathlib import Path

import fitz


def shard_pdf(pdf_path: Path, out_dir: Path, size: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    shards = []
    with fitz.open(pdf_path) as doc:
        total = doc.page_count
        for start in range(0, total, size):
            end = min(start + size, total)
            out_path = out_dir / f"{stem}.shard{start:06d}-{end:06d}.pdf"
            with fitz.open(pdf_path) as shard:
                shard.select(range(start, end))  # select 为破坏性操作，独立打开副本
                shard.save(out_path, garbage=3, deflate=True)
            shards.append({"file": str(out_path), "page_start": start, "page_end": end,
                           "pages": end - start})
            print(f"[shard] {out_path.name}：第 {start + 1}-{end} 页")
    manifest = {
        "source": str(pdf_path), "pages": total, "shard_size": size, "shards": shards,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[shard] 共 {len(shards)} 片 / {total} 页，清单：{manifest_path}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="按页区间切分大 PDF 为分片文件")
    parser.add_argument("pdf", type=Path, help="源 PDF 路径")
    parser.add_argument("--size", type=int, default=100, help="每片页数（默认 100）")
    parser.add_argument("-o", "--outdir", type=Path, default=None,
                        help="输出目录（默认源文件同目录下 shards/）")
    args = parser.parse_args()

    if args.size < 1:
        parser.error("--size 必须 ≥ 1")
    out_dir = args.outdir or args.pdf.parent / "shards"
    shard_pdf(args.pdf, out_dir, args.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
