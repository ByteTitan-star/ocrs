"""pytest 全局夹具：在导入 app 之前设置 mock 模式与临时数据目录。"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["OCRS_MOCK"] = "1"
os.environ["OCRS_DATA_DIR"] = tempfile.mkdtemp(prefix="ocrs-test-")
os.environ["OCRS_ENGINES"] = "dots,paddle"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
