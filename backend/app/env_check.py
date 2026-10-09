"""跨平台环境预检：任何机器（macOS/Windows/Linux、有无 GPU）上，跑任务之前就能知道
每个引擎将以什么设备运行、依赖与权重是否就绪、有没有装错版本的组合。

原则：静态检查不加载模型权重（秒级完成）；深度自检（真跑一页）由
scripts/check_env.py --smoke 触发。
"""
import os
import platform
import sys


def available_memory_gb() -> float:
    """当前可用内存（GB），darwin / win32 / linux 三分支。失败返回 0（保守视为内存紧张）。"""
    try:
        if sys.platform == "darwin":
            import re
            import subprocess
            out = subprocess.run(["memory_pressure"], capture_output=True, text=True,
                                 timeout=5).stdout
            m = re.search(r"free percentage:\s*(\d+(?:\.\d+)?)", out)
            total_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
            return total_gb * float(m.group(1)) / 100 if m else 0.0
        if sys.platform == "win32":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]
            stat = _MemStatus()
            stat.dwLength = ctypes.sizeof(_MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullAvailPhys / 1e9
        with open("/proc/meminfo", encoding="utf-8") as f:  # Linux
            info = {}
            for line in f:
                key, _, value = line.partition(":")
                info[key] = int(value.strip().split()[0])  # kB
        return info.get("MemAvailable", 0) / 1e6
    except Exception:
        return 0.0


def torch_info() -> dict | None:
    """torch 运行环境：CUDA 构建/MPS/设备名与显存。torch 未安装返回 None。"""
    try:
        import torch
    except Exception:
        return None
    info = {"version": torch.__version__,
            "cuda_build": getattr(getattr(torch, "version", None), "cuda", None),
            "cuda": False, "mps": False, "device": "cpu", "name": "", "vram_gb": 0.0}
    try:
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            info.update(cuda=True, device="cuda:0", name=torch.cuda.get_device_name(0),
                        vram_gb=round(props.total_memory / 1e9, 1))
    except Exception:
        pass
    mps = getattr(torch.backends, "mps", None)
    if mps and mps.is_available():
        info["mps"] = True
        if not info["cuda"]:
            info["device"] = "mps"
    return info


def paddle_info() -> dict | None:
    """paddle 运行环境：是否 CUDA 构建、GPU 是否可见。未安装返回 None。"""
    try:
        import paddle
    except Exception:
        return None
    compiled = False
    try:
        compiled = bool(paddle.is_compiled_with_cuda())
    except Exception:
        pass
    info = {"version": paddle.__version__, "cuda_build": compiled,
            "cuda": False, "device": "cpu", "name": ""}
    try:
        if compiled and paddle.device.cuda.device_count() > 0:
            info.update(cuda=True, device="gpu:0",
                        name=paddle.device.cuda.get_device_name(0))
    except Exception:
        pass
    return info


def gpu_warnings(torch_i: dict | None, paddle_i: dict | None) -> list[str]:
    """「装错版本」类组合的静态警告——在跑任务之前暴露，而不是推理时才报错。"""
    warnings: list[str] = []
    if torch_i and not torch_i["cuda"] and not torch_i["mps"] and sys.platform in ("win32", "linux"):
        if torch_i["cuda_build"] is None:
            warnings.append("torch 为 CPU 构建；若本机有 NVIDIA 显卡，请安装 CUDA 版 torch 以启用 GPU")
        else:
            warnings.append("torch 为 CUDA 构建但 torch.cuda.is_available()=False，请检查显卡驱动与 CUDA 版本匹配")
    if paddle_i and torch_i and torch_i["cuda"] and not paddle_i["cuda"]:
        warnings.append("检测到 NVIDIA GPU，但 paddlepaddle 为 CPU 版：请改装 paddlepaddle-gpu（版本需匹配 CUDA）"
                        "并设置 OCRS_PADDLE_DEVICE=gpu:0")
    return warnings


def system_summary() -> str:
    mem = available_memory_gb()
    return (f"{platform.system()} {platform.release()} · {os.cpu_count() or '?'} 核 · "
            f"可用内存 {mem:.0f}GB · Python {sys.version.split()[0]}")


def engine_report(engine) -> dict:
    """单引擎预检：可用性（依赖+权重） + 实际将使用的设备 + 静态警告。不加载权重。"""
    available, detail = engine.availability()
    return {
        "name": engine.name,
        "label": engine.label,
        "available": available,
        "detail": detail,
        "device": engine.device_detail(),
        "setup_hint": engine.setup_hint,
    }
