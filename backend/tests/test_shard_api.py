"""分片 API 与切分脚本测试。"""
import json
import subprocess
import sys
import time
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/shard_pdf.py"


def make_pdf(pages: int = 5) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((48, 72), f"Page {i + 1} body text here.", fontname="helv", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def wait_finished(task_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task.get("finished"):
            return task
        time.sleep(0.2)
    raise TimeoutError(f"任务未在 {timeout}s 内完成：{task}")


def test_shard_upload_flow():
    files = {"file": ("doc.pdf", make_pdf(5), "application/pdf")}
    created = client.post("/api/tasks?page_start=2&page_end=4", files=files)
    assert created.status_code == 200
    data = created.json()
    assert data["pages"] == 2 and data["page_start"] == 2 and data["page_end"] == 4

    task = wait_finished(data["task_id"])
    for engine in ("dots", "paddle"):
        assert task["engines"][engine]["status"] == "done"
        assert task["engines"][engine]["total"] == 2  # 状态里的 total 为分片页数
        md = client.get(f"/api/tasks/{data['task_id']}/markdown/{engine}").text
        assert "第 3 页" in md and "第 4 页" in md
        assert "第 1 页" not in md and "第 2 页" not in md


def test_shard_validation():
    files = {"file": ("doc.pdf", make_pdf(3), "application/pdf")}
    assert client.post("/api/tasks?page_start=3", files=files).status_code == 400  # 越界
    assert client.post("/api/tasks?page_start=2&page_end=1", files=files).status_code == 400  # 空
    # page_end 超出文档页数时收敛到末页（支持「从第 X 页到结尾」的用法）
    clamped = client.post("/api/tasks?page_start=1&page_end=999", files=files)
    assert clamped.status_code == 200
    assert clamped.json()["page_end"] == 3


def test_shard_pdf_script(tmp_path):
    pdf = tmp_path / "huge.pdf"
    pdf.write_bytes(make_pdf(5))
    out = tmp_path / "shards"
    proc = subprocess.run([sys.executable, str(SCRIPT), str(pdf), "--size", "2", "-o", str(out)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["pages"] == 5
    assert [s["pages"] for s in manifest["shards"]] == [2, 2, 1]
    for shard in manifest["shards"]:
        with fitz.open(shard["file"]) as doc:
            assert doc.page_count == shard["pages"]
    # 分片内容与源文件页序一致：第 2 片首页是源第 3 页
    with fitz.open(manifest["shards"][1]["file"]) as doc:
        assert "Page 3" in doc[0].get_text()
