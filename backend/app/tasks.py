"""任务存储与调度：每个上传的 PDF 一个任务；两个引擎并行跑，同一引擎串行（模型非线程安全）。"""
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfg
from .engines import create_engine
from .engines.base import OcrEngine, format_exception


@dataclass
class EngineState:
    status: str = "pending"  # pending | loading | running | done | error
    done: int = 0
    total: int = 0
    note: str = ""
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    md_path: str | None = None
    md_chars: int = 0

    def elapsed_ms(self) -> int:
        if self.started_at is None:
            return 0
        end = self.finished_at if self.finished_at is not None else time.time()
        return int((end - self.started_at) * 1000)

    def to_dict(self) -> dict:
        return {
            "status": self.status, "done": self.done, "total": self.total,
            "note": self.note, "error": self.error,
            "elapsed_ms": self.elapsed_ms(),
            "md_path": self.md_path, "md_chars": self.md_chars,
        }


@dataclass
class Task:
    id: str
    filename: str
    pages: int
    created_at: float = field(default_factory=time.time)
    engines: dict[str, EngineState] = field(default_factory=dict)

    def to_dict(self) -> dict:
        finished = all(
            s.status in ("done", "error") for s in self.engines.values()
        ) if self.engines else False
        return {
            "id": self.id,
            "filename": self.filename,
            "pages": self.pages,
            "created_at": self.created_at,
            "finished": finished,
            "engines": {name: state.to_dict() for name, state in self.engines.items()},
        }


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._engine_locks: dict[str, threading.Lock] = {}
        self._engines: dict[str, OcrEngine] = {}

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def create(self, filename: str, pdf_path: Path, pages: int, engine_names: list[str],
               task_id: str | None = None) -> Task:
        task_id = task_id or self.new_id()
        task = Task(id=task_id, filename=filename, pages=pages)
        for name in engine_names:
            task.engines[name] = EngineState(total=pages)
            work_dir = self.work_dir(task_id, name)
            work_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._tasks[task_id] = task
        for name in engine_names:
            threading.Thread(
                target=self._run_engine, args=(task, name, pdf_path), daemon=True,
                name=f"ocr-{task_id}-{name}",
            ).start()
        return task

    def work_dir(self, task_id: str, engine_name: str) -> Path:
        return cfg.TASKS_DIR / task_id / engine_name

    def _update(self, task: Task, engine_name: str, **fields) -> None:
        with self._lock:
            state = task.engines[engine_name]
            for key, value in fields.items():
                setattr(state, key, value)

    def _run_engine(self, task: Task, engine_name: str, pdf_path: Path) -> None:
        state = task.engines[engine_name]
        lock = self._engine_locks.setdefault(engine_name, threading.Lock())
        try:
            engine = self._engines.get(engine_name)
            if engine is None:
                engine = self._engines.setdefault(engine_name, create_engine(engine_name))

            self._update(task, engine_name, status="loading", started_at=time.time(),
                         note="加载模型中…")
            with lock:  # 同一引擎全局串行，避免模型并发推理
                self._update(task, engine_name, status="running", note="识别中…")

                def progress(done: int, total: int, note: str) -> None:
                    self._update(task, engine_name, done=done, total=total, note=note)

                markdown = engine.run(pdf_path, self.work_dir(task.id, engine_name), progress)

            md_path = self.work_dir(task.id, engine_name) / "result.md"
            md_path.write_text(markdown, encoding="utf-8")
            self._update(task, engine_name, status="done", finished_at=time.time(),
                         note=f"完成，共 {len(markdown)} 字符", md_path=str(md_path),
                         md_chars=len(markdown))
        except Exception as exc:  # noqa: BLE001 —— 任意引擎错误都要落到任务状态里
            self._update(task, engine_name, status="error", finished_at=time.time(),
                         error=f"{type(exc).__name__}: {exc}",
                         note="识别失败",)
            print(f"[task {task.id}/{engine_name}] error:\n{format_exception(exc)}")


store = TaskStore()
