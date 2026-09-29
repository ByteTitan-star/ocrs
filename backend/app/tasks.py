"""任务存储与调度：目录即任务，引擎在独立 worker 子进程中执行。

主进程职责：保存上传的 PDF、写入 .job、拉起/看护 worker 进程、聚合各任务状态。
引擎状态由 worker 通过 .state.json 文件实时写入，主进程每次查询时从磁盘读取，
因此无论引擎多忙，进度接口都不会被阻塞。
"""
import atexit
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfg
from .worker import job_path, read_state

BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass
class Task:
    id: str
    filename: str
    pages: int
    created_at: float
    engines: list[str] = field(default_factory=list)


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._workers: dict[str, subprocess.Popen] = {}
        self._worker_logs: dict[str, object] = {}
        atexit.register(self.shutdown)

    # ---- 任务生命周期 ----
    def new_id(self) -> str:
        import uuid
        return uuid.uuid4().hex[:12]

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def create(self, filename: str, pdf_path: Path, pages: int, engine_names: list[str],
               task_id: str | None = None) -> Task:
        task_id = task_id or self.new_id()
        task = Task(id=task_id, filename=filename, pages=pages,
                    created_at=time.time(), engines=list(engine_names))
        task_dir = cfg.TASKS_DIR / task_id
        for name in engine_names:
            (task_dir / name).mkdir(parents=True, exist_ok=True)
            job_path(task_dir, name).write_text(json.dumps({
                "pdf": str(pdf_path), "pages": pages, "created": task.created_at,
            }, ensure_ascii=False), encoding="utf-8")
        with self._lock:
            self._tasks[task_id] = task
        for name in engine_names:
            self.ensure_worker(name)
        return task

    def work_dir(self, task_id: str, engine_name: str) -> Path:
        return cfg.TASKS_DIR / task_id / engine_name

    # ---- 状态聚合（每次从磁盘读取，天然反映 worker 最新进度）----
    def engine_states(self, task: Task) -> dict[str, dict]:
        task_dir = cfg.TASKS_DIR / task.id
        states = {}
        for name in task.engines:
            st = read_state(task_dir, name) or {}
            started_at = st.get("started_at")
            finished_at = st.get("finished_at")
            elapsed_ms = 0
            if started_at:
                elapsed_ms = int(((finished_at or time.time()) - started_at) * 1000)
            states[name] = {
                "status": st.get("status") or "pending",
                "done": st.get("done") or 0,
                "total": st.get("total") or task.pages,
                "note": st.get("note") or "",
                "error": st.get("error"),
                "elapsed_ms": elapsed_ms,
                "md_path": st.get("md_path"),
                "md_chars": st.get("md_chars") or 0,
            }
        return states

    def task_dict(self, task: Task) -> dict:
        engines = self.engine_states(task)
        finished = bool(engines) and all(
            s["status"] in ("done", "error") for s in engines.values())
        return {
            "id": task.id, "filename": task.filename, "pages": task.pages,
            "created_at": task.created_at, "finished": finished,
            "engines": engines,
        }

    # ---- worker 进程管理 ----
    def ensure_worker(self, engine_name: str) -> None:
        with self._lock:
            proc = self._workers.get(engine_name)
            if proc is not None and proc.poll() is None:
                return
            log_path = cfg.DATA_DIR / f"worker-{engine_name}.log"
            log_file = self._worker_logs.get(engine_name)
            if log_file is None or log_file.closed:
                log_file = open(log_path, "ab")
                self._worker_logs[engine_name] = log_file
            proc = subprocess.Popen(
                [sys.executable, "-m", "app.worker", engine_name],
                cwd=str(BACKEND_DIR), stdout=log_file, stderr=subprocess.STDOUT,
            )
            self._workers[engine_name] = proc

    def shutdown(self) -> None:
        with self._lock:
            for proc in self._workers.values():
                if proc.poll() is None:
                    proc.terminate()
            for f in self._worker_logs.values():
                try:
                    f.close()
                except Exception:
                    pass


store = TaskStore()
