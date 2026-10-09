"""引擎注册表：根据配置（含 mock 模式）产出可用的引擎实例。"""
from .. import config as cfg
from .base import OcrEngine
from .digital import DigitalEngine
from .dots import DotsEngine
from .mock import MockDigitalEngine, MockDotsEngine, MockPaddleEngine
from .paddle import PaddleEngine

if cfg.MOCK:
    _REGISTRY = {"digital": MockDigitalEngine, "dots": MockDotsEngine, "paddle": MockPaddleEngine}
else:
    _REGISTRY = {"digital": DigitalEngine, "dots": DotsEngine, "paddle": PaddleEngine}


def available_engine_names() -> list[str]:
    return [name for name in cfg.ENGINES if name in _REGISTRY]


def create_engine(name: str) -> OcrEngine:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise ValueError(f"未知引擎：{name}（可选：{list(_REGISTRY)}）")


def engine_catalog() -> list[dict]:
    """供 /api/engines 使用：每个已启用引擎的可用性与说明。"""
    catalog = []
    for name in cfg.ENGINES:
        if name not in _REGISTRY:
            catalog.append({"name": name, "label": name, "enabled": True,
                            "available": False, "detail": "未注册的引擎", "mock": False})
            continue
        engine = create_engine(name)
        available, detail = engine.availability()
        device = engine.device_detail()
        if device:  # 预检信息：实际将使用的设备（不加载权重）
            detail = f"{detail} · {device}"
        catalog.append({
            "name": name,
            "label": engine.label,
            "enabled": True,
            "available": available,
            "detail": detail,
            "mock": cfg.MOCK,
        })
    return catalog
