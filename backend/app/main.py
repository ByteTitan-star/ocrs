"""FastAPI 应用：上传 PDF → 双引擎任务 → 轮询状态 → 获取/下载 Markdown。"""
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config as cfg
from .engines import available_engine_names, engine_catalog
from .pdf_utils import count_pages, rewrite_relative_images
from .tasks import store

app = FastAPI(title="ocrs", description="PDF 双 OCR 引擎 Markdown 对比")
cfg.ensure_dirs()

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@app.get("/api/engines")
def list_engines() -> dict:
    return {"engines": engine_catalog(), "max_pages": cfg.MAX_PAGES,
            "max_upload_mb": cfg.MAX_UPLOAD_MB}


@app.post("/api/tasks")
async def create_task(file: UploadFile) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "只支持 PDF 文件")
    engine_names = available_engine_names()
    if not engine_names:
        raise HTTPException(500, "没有可用引擎，请检查 OCRS_ENGINES 配置或先安装依赖")

    content = await file.read()
    if not content:
        raise HTTPException(400, "上传的文件为空")
    if len(content) > cfg.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"文件超过大小上限 {cfg.MAX_UPLOAD_MB}MB")

    task_id = store.new_id()
    pdf_path = cfg.TASKS_DIR / task_id / "input.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(content)
    try:
        pages = count_pages(pdf_path)
    except Exception as exc:
        raise HTTPException(400, f"无法解析该 PDF：{exc}") from exc
    if pages == 0:
        raise HTTPException(400, "该 PDF 没有任何页面")
    if pages > cfg.MAX_PAGES:
        raise HTTPException(400, f"页数 {pages} 超过上限 {cfg.MAX_PAGES}（可通过 OCRS_MAX_PAGES 调整）")

    task = store.create(file.filename, pdf_path, pages, engine_names, task_id=task_id)
    return {"task_id": task.id, "pages": pages, "engines": engine_names}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = store.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task.to_dict()


def _require_markdown(task_id: str, engine_name: str) -> tuple[str, Path]:
    task = store.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    state = task.engines.get(engine_name)
    if state is None:
        raise HTTPException(404, f"任务中没有引擎 {engine_name}")
    if state.status != "done" or not state.md_path:
        raise HTTPException(409, f"该引擎尚未完成（当前状态：{state.status}）")
    task_dir = (cfg.TASKS_DIR / task_id).resolve()
    md_path = Path(state.md_path).resolve()
    if not str(md_path).startswith(str(task_dir)):  # 防路径穿越
        raise HTTPException(400, "非法路径")
    return task_id, md_path


@app.get("/api/tasks/{task_id}/markdown/{engine_name}")
def get_markdown(task_id: str, engine_name: str) -> PlainTextResponse:
    _, md_path = _require_markdown(task_id, engine_name)
    markdown = md_path.read_text(encoding="utf-8")
    markdown = rewrite_relative_images(markdown, f"/files/{task_id}/{engine_name}")
    return PlainTextResponse(markdown, media_type="text/markdown; charset=utf-8")


@app.get("/api/tasks/{task_id}/download/{engine_name}")
def download_markdown(task_id: str, engine_name: str) -> FileResponse:
    _, md_path = _require_markdown(task_id, engine_name)
    stem = Path(store.get(task_id).filename).stem
    return FileResponse(md_path, media_type="text/markdown",
                        filename=f"{stem}_{engine_name}.md")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "ts": time.time()}


# 静态资源：先挂结果文件（含图片），再挂前端页面
app.mount("/files", StaticFiles(directory=cfg.TASKS_DIR), name="files")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
