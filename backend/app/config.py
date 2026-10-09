"""全局配置：所有配置项均为 OCRS_ 前缀环境变量，支持项目根目录 .env 文件。"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载：KEY=VALUE 每行一条，# 开头为注释，不覆盖已有环境变量。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# ===== 通用 =====
DATA_DIR = Path(os.getenv("OCRS_DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
TASKS_DIR = DATA_DIR / "tasks"
ENGINES = [s.strip() for s in os.getenv("OCRS_ENGINES", "digital,dots,paddle").split(",") if s.strip()]
MOCK = _bool("OCRS_MOCK", False)
# 引擎执行方式：auto（默认，按当前可用内存自动判定串行/并行）/ 1 强制并行 / 0 强制串行
PARALLEL = os.getenv("OCRS_PARALLEL", "auto").strip().lower()
if PARALLEL in ("true", "yes", "on"):
    PARALLEL = "1"
elif PARALLEL in ("false", "no", "off"):
    PARALLEL = "0"
MAX_PAGES = _int("OCRS_MAX_PAGES", 100)
MAX_UPLOAD_MB = _int("OCRS_MAX_UPLOAD_MB", 200)

# ===== dots.ocr =====
DOTS_MODEL_PATH = Path(os.getenv("OCRS_DOTS_MODEL_PATH", str(PROJECT_ROOT / "weights/DotsOCR")))
DOTS_DEVICE = os.getenv("OCRS_DOTS_DEVICE", "auto").strip().lower()
DOTS_DTYPE = os.getenv("OCRS_DOTS_DTYPE", "auto").strip().lower()
DOTS_ATTN = os.getenv("OCRS_DOTS_ATTN", "auto").strip().lower()
DOTS_MAX_NEW_TOKENS = _int("OCRS_DOTS_MAX_NEW_TOKENS", 16384)
DOTS_DPI = _int("OCRS_DOTS_DPI", 200)
DOTS_MAX_PIXELS = _int("OCRS_DOTS_MAX_PIXELS", 0)
DOTS_PROMPT_MODE = os.getenv("OCRS_DOTS_PROMPT_MODE", "prompt_layout_all_en")

# ===== PaddleOCR =====
# 设备：留空自动探测（有 CUDA 用 gpu:0，否则 cpu；Mac 上必然 cpu）；也可手动指定如 gpu:0
PADDLE_DEVICE = os.getenv("OCRS_PADDLE_DEVICE", "").strip()
# 精度/速度三档：accurate（官方默认全开）| balanced（关方向/矫正/文本行方向，保留公式）| fast（mobile 检测识别+关公式，CPU 数秒/页）
PADDLE_PROFILE = os.getenv("OCRS_PADDLE_PROFILE", "accurate").strip().lower()
# 公式识别开关：留空跟随 profile（accurate/balanced 开、fast 关）；0 强制关闭；1 强制开启。
# M5 CPU 实测：FormulaNet-L 自回归解码占单页耗时 90% 以上（63s/页 → 15min+/页），纯 CPU 建议关闭。
PADDLE_FORMULA = os.getenv("OCRS_PADDLE_FORMULA", "").strip()
# 旧提速开关（等价 balanced 的三个关闭），保留兼容；建议改用 OCRS_PADDLE_PROFILE
PADDLE_FAST = _bool("OCRS_PADDLE_FAST", False)

# PaddleX 3.4 默认从 huggingface 下载子模型，国内网络会卡死；
# hf.co 不可达且用户未显式配置时自动切换到百度 BOS 源（免登录、全量模型）。
if "PADDLE_PDX_MODEL_SOURCE" not in os.environ and "HF_ENDPOINT" not in os.environ:
    import urllib.request

    def _hf_reachable(timeout: float = 3.0) -> bool:
        try:
            req = urllib.request.Request(
                "https://huggingface.co/PaddlePaddle/PP-OCRv5_server/config.json",
                method="HEAD")
            urllib.request.urlopen(req, timeout=timeout)
            return True
        except Exception:
            return False

    if not _hf_reachable():
        os.environ["PADDLE_PDX_MODEL_SOURCE"] = "bos"
        print("[config] huggingface.co 不可达，PaddleOCR 子模型改用 BOS 源下载", file=sys.stderr)


def ensure_dirs() -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
