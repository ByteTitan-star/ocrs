"""环境预检测试：装错版本的警告规则、引擎报告结构、doctor CLI（mock 模式）。"""
import json
import os
import subprocess
import sys
from pathlib import Path

from app.engines.base import OcrEngine
from app.env_check import engine_report, gpu_warnings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_env.py"


class FakeEngine(OcrEngine):
    name = "fake"
    label = "Fake Engine"

    def availability(self):
        return True, "一切正常"

    def device_detail(self):
        return "device=cpu"

    def _load(self):
        pass

    def _run(self, pdf_path, work_dir, progress, page_range=None):
        return ""


def test_gpu_warnings_rules(monkeypatch):
    assert gpu_warnings(None, None) == []
    # 有 NVIDIA GPU 但 paddle 是 CPU 版 → 提示换 paddlepaddle-gpu（平台无关规则）
    w = gpu_warnings({"cuda": True, "mps": False}, {"cuda": False})
    assert len(w) == 1 and "paddlepaddle-gpu" in w[0]
    assert gpu_warnings({"cuda": True, "mps": False}, {"cuda": True}) == []

    # Windows/Linux 上 torch 无 GPU：区分「CPU 构建」与「CUDA 构建但驱动不可用」
    monkeypatch.setattr(sys, "platform", "win32")
    assert any("CPU 构建" in x for x in gpu_warnings({"cuda": False, "mps": False, "cuda_build": None}, None))
    assert any("驱动" in x for x in gpu_warnings({"cuda": False, "mps": False, "cuda_build": "12.4"}, None))


def test_gpu_warnings_quiet_on_mac(monkeypatch):
    """macOS 上 torch 落到 MPS/CPU 属正常路径，不应刷 CPU 构建警告。"""
    monkeypatch.setattr(sys, "platform", "darwin")
    assert gpu_warnings({"cuda": False, "mps": True, "cuda_build": None}, None) == []
    assert gpu_warnings({"cuda": False, "mps": False, "cuda_build": None}, None) == []


def test_engine_report_structure():
    report = engine_report(FakeEngine())
    assert report == {"name": "fake", "label": "Fake Engine", "available": True,
                      "detail": "一切正常", "device": "device=cpu", "setup_hint": ""}


def test_check_env_cli_mock(tmp_path):
    env = {**os.environ, "OCRS_MOCK": "1", "OCRS_ENGINES": "digital,dots,paddle",
           "OCRS_DATA_DIR": str(tmp_path)}
    proc = subprocess.run([sys.executable, str(SCRIPT), "--json"],
                          capture_output=True, text=True, timeout=120, env=env)
    assert proc.returncode == 0, proc.stderr
    # 第三方库在导入期可能向 stdout 打日志：从首个 "{" 行起解析 JSON
    payload = proc.stdout[proc.stdout.index("{"):]
    data = json.loads(payload)
    assert "Darwin" in data["system"] or data["system"]  # 系统摘要非空
    assert len(data["engines"]) == 3
    assert all(e["available"] for e in data["engines"])
