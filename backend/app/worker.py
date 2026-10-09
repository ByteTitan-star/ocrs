"""引擎 worker：独立子进程运行单个 OCR 引擎。

主服务进程只负责上传/查询，不再承载模型推理——避免重型引擎（torch/MPS、paddle）
与 API 争抢 GIL 和内存，保证进度接口始终流畅。

协议（全部通过任务目录内的文件，无 IPC）：
  data/tasks/{id}/{engine}.job          主进程写入，表示待处理
  data/tasks/{id}/{engine}.state.json   worker 原子写入的实时状态
  data/tasks/{id}/{engine}/result.md    worker 逐页增量写入的识别结果

启动：python -m app.worker <engine_name>
"""
import json
import os
import sys
import time
from pathlib import Path

from . import config as cfg
from .engines import create_engine

STATE_FILENAME = "{engine}.state.json"
JOB_FILENAME = "{engine}.job"
# 串行调度下的执行顺序：优先级小的先跑（digital 无模型最快，paddle 次之，dots 最重）
ENGINE_PRIORITY = {"digital": 0, "paddle": 1, "dots": 2}
# 各引擎满载工作集的粗略估计（GB），用于 auto 模式判定能否并行
ENGINE_MEMORY_GB = {"digital": 0.3, "dots": 9.0, "paddle": 6.0}
SYSTEM_RESERVE_GB = 3.0  # 系统/浏览器等基础开销余量


def available_memory_gb() -> float:
    """当前可用内存（GB）。失败时返回 0（保守视为内存紧张）。"""
    try:
        if sys.platform == "darwin":
            import re
            import subprocess
            out = subprocess.run(["memory_pressure"], capture_output=True, text=True,
                                 timeout=5).stdout
            m = re.search(r"free percentage:\s*(\d+(?:\.\d+)?)", out)
            total_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
            return total_gb * float(m.group(1)) / 100 if m else 0.0
        with open("/proc/meminfo", encoding="utf-8") as f:
            info = {}
            for line in f:
                key, _, value = line.partition(":")
                info[key] = int(value.strip().split()[0])  # kB
        return info.get("MemAvailable", 0) / 1e6
    except Exception:
        return 0.0


def pending_task_memory_gb(task_dir: Path, engine: str) -> float:
    """同一任务里其他引擎（含自己在内）尚未完成部分的内存需求总和。"""
    total = ENGINE_MEMORY_GB.get(engine, 0.5)
    for other, priority in ENGINE_PRIORITY.items():
        if other == engine or priority >= ENGINE_PRIORITY.get(engine, 99):
            continue
        if not job_path(task_dir, other).is_file():
            continue
        st = read_state(task_dir, other)
        if st and st.get("status") in ("done", "error"):
            continue
        total += ENGINE_MEMORY_GB.get(other, 0.5)
    return total


def state_path(task_dir: Path, engine: str) -> Path:
    return task_dir / STATE_FILENAME.format(engine=engine)


def job_path(task_dir: Path, engine: str) -> Path:
    return task_dir / JOB_FILENAME.format(engine=engine)


def read_state(task_dir: Path, engine: str) -> dict | None:
    path = state_path(task_dir, engine)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_state(task_dir: Path, engine: str, **fields) -> dict:
    """合并式原子写入状态文件。"""
    state = read_state(task_dir, engine) or {}
    state.update(fields)
    tmp = state_path(task_dir, engine).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(state_path(task_dir, engine))
    return state


def find_pending_job(engine: str) -> tuple[Path, dict] | None:
    """找最早创建的待处理任务（按任务目录创建时间）。"""
    candidates = []
    if not cfg.TASKS_DIR.is_dir():
        return None
    for task_dir in cfg.TASKS_DIR.iterdir():
        job = job_path(task_dir, engine)
        if not job.is_file():
            continue
        state = read_state(task_dir, engine)
        if state and state.get("status") in ("done", "error"):
            continue
        if state and state.get("status") == "running" and state.get("owner") == os.getpid():
            continue  # 自己正在跑（重启后的遗留 running 已在启动时清理）
        candidates.append((task_dir.stat().st_mtime, task_dir, job))
    if not candidates:
        return None
    _, task_dir, job = min(candidates)
    try:
        spec = json.loads(job.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        write_state(task_dir, engine, status="error", error="任务文件损坏")
        return None
    return task_dir, spec


def wait_for_higher_priority(task_dir: Path, engine: str) -> None:
    """调度：同一任务里存在未完成的高优先级引擎时，决定并行还是等待。

    OCRS_PARALLEL=1 强制并行；=0 强制串行；默认 auto——按当前可用内存判定：
    装得下双引擎工作集（dots≈9GB + paddle≈6GB + 系统余量）就并行，装不下就串行。
    """
    decided = None
    while True:
        unfinished = []
        for other, priority in ENGINE_PRIORITY.items():
            if other == engine or priority >= ENGINE_PRIORITY.get(engine, 99):
                continue
            if not job_path(task_dir, other).is_file():
                continue
            if (read_state(task_dir, other) or {}).get("status") in ("done", "error"):
                continue
            unfinished.append(other)
        if not unfinished:
            return

        if decided is None:
            if cfg.PARALLEL == "1":
                decided = "parallel"
            elif cfg.PARALLEL == "0":
                decided = "serial"
            else:
                need = pending_task_memory_gb(task_dir, engine) + SYSTEM_RESERVE_GB
                avail = available_memory_gb()
                decided = "parallel" if avail >= need else "serial"
                mode = "并行执行" if decided == "parallel" else "串行（等高优先级引擎先完成）"
                print(f"[worker/{engine}] 内存判定：可用 {avail:.0f}GB / 双引擎共需约 "
                      f"{need:.0f}GB → {mode}", flush=True)
        if decided == "parallel":
            return
        time.sleep(2)


def cleanup_stale_running(engine: str) -> None:
    """服务被杀后遗留的 running 状态标记为错误。"""
    if not cfg.TASKS_DIR.is_dir():
        return
    for task_dir in cfg.TASKS_DIR.iterdir():
        st = read_state(task_dir, engine)
        if st and st.get("status") in ("loading", "running") and st.get("owner") not in (None, os.getpid()):
            write_state(task_dir, engine, status="error", finished_at=time.time(),
                        error="服务重启导致识别中断，请重新上传该 PDF")


def _spec_page_range(spec: dict) -> tuple[int, int] | None:
    """从 job spec 解析分片页码区间 [start, end)，缺省为整本。"""
    start, end = spec.get("page_start"), spec.get("page_end")
    if start is None or end is None:
        return None
    return int(start), int(end)


def run_job(engine_obj, task_dir: Path, engine: str, spec: dict) -> None:
    pdf_path = Path(spec["pdf"])
    work_dir = task_dir / engine
    work_dir.mkdir(parents=True, exist_ok=True)
    result_md = work_dir / "result.md"
    result_md.unlink(missing_ok=True)  # 清掉可能的历史残留

    page_range = _spec_page_range(spec)
    total = (page_range[1] - page_range[0]) if page_range else spec.get("pages", 0)
    started = time.time()
    write_state(task_dir, engine, status="loading", owner=os.getpid(),
                started_at=started, done=0, total=total,
                note="加载模型中…", error=None)
    throttle = {"last_write": 0.0, "last_done": -1}

    def progress(done: int, total: int, note: str) -> None:
        now = time.time()
        page_tick = done != throttle["last_done"]
        if not page_tick and now - throttle["last_write"] < 0.4:
            return  # token 级高频上报限流（每 0.4s 至多一次）
        throttle["last_done"], throttle["last_write"] = done, now
        fields = {"status": "running", "done": done, "note": note}
        if total > 0:  # 引擎加载完成后的首报 total=0，不覆盖真实总页数
            fields["total"] = total
        write_state(task_dir, engine, **fields)

    try:
        engine_obj.run(pdf_path, work_dir, progress, page_range=page_range)
        md_chars = result_md.stat().st_size if result_md.is_file() else 0
        write_state(task_dir, engine, status="done", finished_at=time.time(),
                    note=f"完成，共 {md_chars} 字符", md_chars=md_chars,
                    md_path=str(result_md))
    except Exception as exc:  # noqa: BLE001
        from .engines.base import format_exception
        print(f"[worker/{engine}] error:\n{format_exception(exc)}", file=sys.stderr, flush=True)
        write_state(task_dir, engine, status="error", finished_at=time.time(),
                    error=f"{type(exc).__name__}: {exc}", note="识别失败")


def main() -> int:
    engine_name = sys.argv[1]
    original_ppid = os.getppid()

    cleanup_stale_running(engine_name)
    engine = create_engine(engine_name)
    available, detail = engine.availability()
    if not available:
        print(f"[worker/{engine_name}] 引擎不可用：{detail}", file=sys.stderr, flush=True)
        pending = find_pending_job(engine_name)  # 把排队任务直接标错，让前端立刻看到原因
        while pending:
            task_dir, _ = pending
            write_state(task_dir, engine_name, status="error", error=f"引擎不可用：{detail}")
            pending = find_pending_job(engine_name)
        return 1

    print(f"[worker/{engine_name}] 就绪：{detail}", flush=True)
    while True:
        if os.getppid() != original_ppid:  # 主进程已退出，避免孤儿进程
            print(f"[worker/{engine_name}] 主进程已退出，worker 结束", flush=True)
            return 0
        pending = find_pending_job(engine_name)
        if not pending:
            time.sleep(1.5)
            continue
        task_dir, spec = pending
        wait_for_higher_priority(task_dir, engine_name)
        run_job(engine, task_dir, engine_name, spec)
        job_path(task_dir, engine_name).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
