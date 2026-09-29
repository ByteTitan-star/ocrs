"""API 端到端测试（mock 引擎）：上传 → 轮询 → Markdown 获取/下载、错误处理。"""
import io
import time

import fitz
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def make_pdf(pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def wait_finished(task_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task.get("finished"):
            return task
        time.sleep(0.2)
    raise TimeoutError(f"任务未在 {timeout}s 内完成：{task}")


def test_engines_catalog_is_mock():
    data = client.get("/api/engines").json()
    names = {e["name"] for e in data["engines"]}
    assert names == {"dots", "paddle"}
    assert all(e["available"] for e in data["engines"])
    assert data["engines"][0]["mock"] is True


def test_upload_flow_to_markdown():
    files = {"file": ("样例.pdf", make_pdf(2), "application/pdf")}
    created = client.post("/api/tasks", files=files)
    assert created.status_code == 200
    task_id = created.json()["task_id"]
    assert created.json()["pages"] == 2

    task = wait_finished(task_id)
    assert task["engines"]["dots"]["status"] == "done"
    assert task["engines"]["paddle"]["status"] == "done"
    assert task["engines"]["dots"]["done"] == 2

    for engine in ("dots", "paddle"):
        md = client.get(f"/api/tasks/{task_id}/markdown/{engine}")
        assert md.status_code == 200
        assert "mock" in md.text
        assert "第 1 页" in md.text and "第 2 页" in md.text
        # 相对图片路径应被重写为 /files/ 绝对地址
        assert f"/files/{task_id}/{engine}/images/demo.png" in md.text
        # 重写后的图片确实可以被静态路由访问到
        img = client.get(f"/files/{task_id}/{engine}/images/demo.png")
        assert img.status_code == 200

    dl = client.get(f"/api/tasks/{task_id}/download/paddle")
    assert dl.status_code == 200
    assert "attachment" in dl.headers["content-disposition"]

    missing = client.get(f"/api/tasks/does-not-exist")
    assert missing.status_code == 404


def test_rejects_non_pdf():
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    assert client.post("/api/tasks", files=files).status_code == 400


def test_rejects_corrupt_pdf():
    files = {"file": ("broken.pdf", b"this is not a pdf", "application/pdf")}
    assert client.post("/api/tasks", files=files).status_code == 400


def test_markdown_not_ready_conflict():
    created = client.post("/api/tasks", files={"file": ("t.pdf", make_pdf(1), "application/pdf")})
    task_id = created.json()["task_id"]
    resp = client.get(f"/api/tasks/{task_id}/markdown/dots")
    assert resp.status_code in (200, 409)  # mock 很快，两者都合法
    wait_finished(task_id)
