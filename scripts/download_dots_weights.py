#!/usr/bin/env python
"""下载 dots.ocr 模型权重到 weights/DotsOCR（约 6GB，支持断点续传）。

用法：
    python scripts/download_dots_weights.py                 # 自动选择最快的源
    python scripts/download_dots_weights.py --source hf     # HuggingFace（自动走 hf-mirror 镜像）
    python scripts/download_dots_weights.py --source modelscope
"""
import argparse
import os
import sys
import time
import urllib.request
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "weights/DotsOCR"
REPO_ID = "dots-studio/dots.ocr"  # 原 rednote-hilab/dots.ocr，组织已更名
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "").rstrip("/") or None
CHUNK = 1024 * 1024


def hf_base() -> str:
    if HF_ENDPOINT:
        return HF_ENDPOINT
    return "https://hf-mirror.com" if not hf_reachable() else "https://huggingface.co"


def hf_reachable(timeout: float = 6.0) -> bool:
    try:
        req = urllib.request.Request(
            f"https://huggingface.co/{REPO_ID}/resolve/main/config.json", method="HEAD")
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


def probe_speed(url: str, seconds: float = 6.0) -> float:
    """下载一小段测速，返回 B/s。"""
    try:
        started = time.time()
        downloaded = 0
        with requests.get(url, stream=True, timeout=seconds, headers={"Range": "bytes=0-"}) as r:
            r.raise_for_status()
            for chunk in r.iter_content(CHUNK):
                downloaded += len(chunk)
                if time.time() - started >= seconds:
                    break
        return downloaded / max(time.time() - started, 0.001)
    except Exception:
        return 0.0


def list_files(source: str) -> list[str]:
    if source == "modelscope":
        resp = requests.get(
            f"https://modelscope.cn/api/v1/models/{REPO_ID}/repo/files",
            params={"Recursive": "true"}, timeout=20)
        resp.raise_for_status()
        files = resp.json()["Data"]["Files"]
        return [f["Path"] for f in files if f["Type"] == "blob"]
    # HuggingFace
    base = hf_base()
    resp = requests.get(f"{base}/api/models/{REPO_ID}", timeout=20)
    resp.raise_for_status()
    return [s["rfilename"] for s in resp.json().get("siblings", [])]


def file_url(source: str, name: str) -> str:
    if source == "modelscope":
        return f"https://modelscope.cn/models/{REPO_ID}/resolve/master/{name}"
    return f"{hf_base()}/{REPO_ID}/resolve/main/{name}"


def download(source: str, names: list[str]) -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in names:
        dest = TARGET / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = file_url(source, name)
        headers = {}
        mode = "wb"
        part = dest.with_suffix(dest.suffix + ".part")
        if part.exists():  # 断点续传
            headers["Range"] = f"bytes={part.stat().st_size}-"
            mode = "ab"
        with requests.get(url, stream=True, timeout=60, headers=headers) as r:
            if r.status_code == 416:  # .part 已完整
                part.rename(dest)
                print(f"  ✓ {name}（续传发现已完成）")
                continue
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) + (part.stat().st_size if mode == "ab" else 0)
            done = part.stat().st_size if mode == "ab" else 0
            label = f"  {name} {done / 1e9:.2f}/{total / 1e9:.2f} GB"
            t0, shown = time.time(), -1
            with open(part, mode) as f:
                for chunk in r.iter_content(CHUNK):
                    f.write(chunk)
                    done += len(chunk)
                    if total and int(done / total * 100) != shown and time.time() - t0 > 2:
                        shown = int(done / total * 100)
                        rate = done / max(time.time() - t0, 1)
                        print(f"  {name} {shown}%（{rate / 1e6:.1f} MB/s）", flush=True)
        part.rename(dest)
        print(f"  ✓ {name} 完成", flush=True)


def pick_source() -> str:
    hf_speed = probe_speed(file_url("hf", "model-00001-of-00002.safetensors"))
    ms_speed = probe_speed(file_url("modelscope", "model-00001-of-00002.safetensors"))
    print(f"测速：huggingface={hf_speed / 1e6:.1f} MB/s，modelscope={ms_speed / 1e6:.1f} MB/s")
    return "modelscope" if ms_speed >= hf_speed else "hf"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["auto", "hf", "modelscope"], default="auto")
    args = parser.parse_args()

    source = pick_source() if args.source == "auto" else args.source
    print(f"使用源：{source} -> {TARGET}")
    names = list_files(source)
    if not names:
        print("未获取到文件列表", file=sys.stderr)
        return 1
    download(source, names)
    print(f"完成：{TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
