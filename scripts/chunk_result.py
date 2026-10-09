#!/usr/bin/env python
"""任务结果切块：任务工作目录 → chunks.jsonl（向量库入库的直接输入）。

优先消费布局 JSON（dots 的 pages/page_*.json，带 bbox/类别/标题上下文），
无布局存档时兜底按 result.md 切分。

用法：
  python scripts/chunk_result.py data/tasks/<task_id>/dots --doc-id paper-42
  python scripts/chunk_result.py data/tasks/<task_id>/paddle --doc-id paper-42
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.chunker import chunk_dots_pages, chunk_markdown  # noqa: E402


def chunk_work_dir(work_dir: Path, doc_id: str, max_chars: int) -> list[dict]:
    pages_dir = work_dir / "pages"
    if pages_dir.is_dir() and list(pages_dir.glob("page_*.json")):
        return list(chunk_dots_pages(pages_dir, doc_id=doc_id, max_chars=max_chars))
    result_md = work_dir / "result.md"
    if result_md.is_file():
        return chunk_markdown(result_md.read_text(encoding="utf-8"), doc_id=doc_id,
                              max_chars=max_chars)
    raise SystemExit(f"未找到可切块的产物：{work_dir}/pages/page_*.json 或 {work_dir}/result.md")


def main() -> int:
    parser = argparse.ArgumentParser(description="把任务识别结果切成带溯源元数据的 chunk")
    parser.add_argument("work_dir", type=Path, help="任务引擎工作目录，如 data/tasks/<id>/dots")
    parser.add_argument("--doc-id", default="", help="文档标识，写入每个 chunk 的 doc_id")
    parser.add_argument("--max-chars", type=int, default=1200, help="单块字符上限")
    parser.add_argument("-o", "--out", type=Path, default=None, help="输出 jsonl（默认工作目录下 chunks.jsonl）")
    args = parser.parse_args()

    chunks = chunk_work_dir(args.work_dir, args.doc_id, args.max_chars)
    out = args.out or args.work_dir / "chunks.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    categories: dict[str, int] = {}
    for c in chunks:
        categories[c["category"]] = categories.get(c["category"], 0) + 1
    print(f"[chunk] {len(chunks)} 块 → {out}（类别分布：{categories}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
