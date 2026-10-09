"""OCR 引擎抽象基类：统一「可用性检查 → 懒加载 → 逐页推理」生命周期。"""
import threading
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

# 进度回调：(已完成页数, 总页数, 说明)
ProgressFn = Callable[[int, int, str], None]

# 页与页之间的分隔线（与最终 Markdown 拼接格式一致）
PAGE_SEPARATOR = "\n\n---\n\n"

# 分片页码区间 [start, end)，None 表示整本；页码为 PDF 内的绝对页码
PageRange = Optional[tuple[int, int]]


def append_page_markdown(work_dir: Path, page_md: str) -> None:
    """把一页的 Markdown 增量写入 work_dir/result.md，识别完一页即可被前端拉取预览。

    以文件是否已存在决定是否加页分隔线——分片任务首页不从第 0 页开始时同样正确。
    """
    if not page_md:
        return
    result = work_dir / "result.md"
    prefix = "" if not result.exists() else PAGE_SEPARATOR
    with open(result, "a", encoding="utf-8") as f:
        f.write(prefix + page_md)


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

    def device_detail(self) -> str:
        """引擎实际将使用的设备描述（不加载权重，用于环境预检）。默认空=无设备概念。"""
        return ""

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
    def _run(self, pdf_path: Path, work_dir: Path, progress: ProgressFn,
             page_range: PageRange = None) -> str:
        """对 PDF（可按 page_range 分片）推理，逐页增量写入 result.md。"""

    def run(self, pdf_path: Path, work_dir: Path, progress: Optional[ProgressFn] = None,
            page_range: PageRange = None) -> str:
        noop: ProgressFn = lambda *_: None
        progress = progress or noop
        self.load()
        progress(0, 0, "模型加载完成，开始识别…")  # 首页可能耗时数分钟，先让状态进入"识别中"
        return self._run(pdf_path, work_dir, progress, page_range=page_range)


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
