"""OCR 引擎抽象基类：统一「可用性检查 → 懒加载 → 逐页推理」生命周期。"""
import threading
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

# 进度回调：(已完成页数, 总页数, 说明)
ProgressFn = Callable[[int, int, str], None]


class OcrEngine(ABC):
    """单个 OCR 引擎。实现者只需提供 _load / _run；线程安全由 TaskStore 的引擎级锁保证。"""

    name: str = ""
    label: str = ""
    #: 引擎的安装/使用说明，用于前端提示
    setup_hint: str = ""

    _load_lock = threading.Lock()
    _loaded: bool = False

    @abstractmethod
    def availability(self) -> tuple[bool, str]:
        """检查依赖与模型是否就绪，返回 (是否可用, 说明)。"""

    def load(self) -> None:
        """幂等加载模型（线程安全）。"""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            self._load()
            self._loaded = True

    @abstractmethod
    def _load(self) -> None:
        """加载模型/管线，耗时操作。失败应抛出带清晰信息的异常。"""

    @abstractmethod
    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn) -> str:
        """对整本 PDF 推理，返回整份 Markdown（页间以 --- 分隔），并通过 progress 上报进度。"""

    def run(self, pdf_path: Path, work_dir: Path, progress: Optional[ProgressFn] = None) -> str:
        noop: ProgressFn = lambda *_: None
        self.load()
        return self._run(pdf_path, work_dir, progress or noop)


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
