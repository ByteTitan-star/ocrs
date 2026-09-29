#!/usr/bin/env bash
# 一键搭建运行环境（使用 uv 管理 Python 依赖）
# 用法：
#   scripts/setup.sh            # 仅安装后端核心依赖（FastAPI/PyMuPDF 等，较小）
#   scripts/setup.sh --dots     # 额外安装 dots.ocr 依赖（torch/transformers，较大）
#   scripts/setup.sh --paddle   # 额外安装 PaddleOCR 依赖（paddlepaddle/paddleocr）
#   scripts/setup.sh --all      # 全部安装
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

WITH_DOTS=0 WITH_PADDLE=0
for arg in "$@"; do
  case "$arg" in
    --dots)   WITH_DOTS=1 ;;
    --paddle) WITH_PADDLE=1 ;;
    --all)    WITH_DOTS=1; WITH_PADDLE=1 ;;
    *) echo "未知参数：$arg（支持 --dots / --paddle / --all）"; exit 1 ;;
  esac
done

echo "==> 创建虚拟环境（.venv）"
uv sync

if [ "$WITH_DOTS" = 1 ]; then
  echo "==> 安装 dots.ocr 依赖（torch / transformers 等，体积较大）"
  uv sync --extra dots
  if [ ! -d "$ROOT/vendor/dots.ocr" ]; then
    echo "==> 克隆 dots_ocr 代码库到 vendor/"
    mkdir -p "$ROOT/vendor"
    git clone --depth 1 -b master https://github.com/rednote-hilab/dots.ocr.git "$ROOT/vendor/dots.ocr"
  fi
  echo "==> 安装 dots_ocr 包（--no-deps，避免其 gradio/openai 等无关依赖）"
  uv pip install --no-deps -e "$ROOT/vendor/dots.ocr"
  echo "==> 提示：还需要下载模型权重（约 6GB）："
  echo "      .venv/bin/python scripts/download_dots_weights.py"
fi

if [ "$WITH_PADDLE" = 1 ]; then
  echo "==> 安装 PaddleOCR 依赖（paddlepaddle / paddleocr）"
  uv sync --extra paddle
  echo "==> 提示：PaddleOCR 首次识别时会自动下载各子模型（几百 MB）"
fi

echo ""
echo "环境就绪。启动服务："
echo "  cd backend && uv run uvicorn app.main:app --port 8000"
echo "或使用 mock 模式先体验界面：OCRS_MOCK=1 uv run uvicorn app.main:app --port 8000"
