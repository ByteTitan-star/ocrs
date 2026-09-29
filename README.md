# ocrs · PDF 双 OCR 引擎 Markdown 对比台

上传一份 PDF，**dots.ocr** 与 **PaddleOCR (PP-StructureV3)** 两个引擎并行识别，网页上并排对比两份 Markdown 提取效果（渲染预览 / 源码 / 行级差异），并可分别下载 `.md` 文件。所有处理均在本机完成。

```
┌──────────┐   PDF    ┌─────────────────────────────┐
│  浏览器   │ ───────► │  FastAPI 后端                │
│ 上传/对比 │ ◄─────── │  ├─ dots.ocr 引擎 (transformers) ──► dots/result.md
└──────────┘  轮询    │  └─ PaddleOCR PP-StructureV3 ────► paddle/result.md
                      └─────────────────────────────┘
```

## 对比的 OCR 模型

本项目选取了当前文档解析两条主流技术路线的代表模型进行对比——**端到端视觉语言模型（VLM）** vs **传统多模块流水线**：

| | **dots.ocr** | **PaddleOCR PP-StructureV3** |
| --- | --- | --- |
| 开发方 | rednote（小红书）hi lab | 百度 PaddlePaddle |
| 技术路线 | 单一视觉语言模型（VLM），端到端生成 | 多模块流水线（版面分析 + 表格识别 + 公式识别 + 文本检测/识别） |
| 模型规模 | 约 3B 参数（1.7B LLM 底座 + 视觉编码器） | 多个子模型组成管线（PP-LCNet / PP-DocLayout 等，按需自动下载） |
| 工作方式 | 整页图像 → 一次性生成布局 JSON（bbox + 类别 + 文本）→ 转 Markdown | 各模块分别检测/识别，再拼装为 Markdown |
| 表格 / 公式 | 表格输出 HTML，公式输出 LaTeX | 表格输出 HTML，公式输出 LaTeX |
| 图片处理 | 不单独裁剪图片 | 自动裁出文档中的图片保存为文件并在 Markdown 中引用 |
| 权重来源 | HuggingFace/ModelScope `dots-studio/dots.ocr`（原 `rednote-hilab/dots.ocr`，MIT 协议，约 6GB） | `paddleocr` 3.x 内置子模型（首次运行自动下载，几百 MB） |
| 推理框架 | transformers（本项目自实现加载与推理，兼容 MPS/CUDA/CPU） | paddleocr 官方 `PPStructureV3` API |
| 项目内引擎名 | `dots` | `paddle` |

选这两个模型对比的意义：dots.ocr 代表「一个大模型直接吃整页图像、端到端输出结构化结果」的新路线；PP-StructureV3 代表「多个专用小模型各司其职、流水线拼装结果」的传统路线。两者在版面还原、表格/公式识别、图片处理、速度与资源占用上各有取舍，本项目把同一份 PDF 分别交给两者，在网页上直观对比 Markdown 提取效果。

## 功能

- **上传 PDF**（拖拽 / 点击），自动统计页数，两个引擎并行识别，逐页进度实时展示
- **双栏对比**：左 dots.ocr、右 PaddleOCR，支持渲染预览与 Markdown 源码两种视图，可同步滚动
- **差异对比**：行级双栏 diff（红色 = dots.ocr 独有，绿色 = PaddleOCR 独有）
- **下载**：分别下载两个引擎的完整 `.md`；PP-StructureV3 提取的图片也会保存并可在预览中显示
- **容错**：单个引擎失败（未装依赖 / 缺权重 / 推理报错）不影响另一个引擎，错误详情直接展示在页面上
- **mock 模式**：`OCRS_MOCK=1` 不加载真实模型即可体验完整界面与流程

## 快速开始

前置要求：Python 3.10+（建议 3.12）、[uv](https://docs.astral.sh/uv/)、网络（首次需下载依赖与模型）。

```bash
# 1. 安装依赖（三选一或组合）
scripts/setup.sh            # 仅核心（FastAPI/PyMuPDF，秒装，只能跑 mock）
scripts/setup.sh --all      # dots.ocr + PaddleOCR 全量安装
scripts/setup.sh --paddle   # 只装 PaddleOCR

# 2. 下载 dots.ocr 权重（约 6GB，仅使用 dots 引擎时需要；断点续传）
cd backend
uv run python ../scripts/download_dots_weights.py

# 3. 启动（PaddleOCR 首次识别会自动下载子模型，几百 MB）
uv run uvicorn app.main:app --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。没有 PDF 可先生成样例：`uv run python ../scripts/make_sample_pdf.py`（生成 `data/sample.pdf`，含中文、英文、表格、页眉页脚 3 页）。

> **huggingface.co 无法访问？** 下载脚本会自动探测并切换到 `hf-mirror.com` 镜像，也可 `export HF_ENDPOINT=...` 自行指定。

## 配置

所有配置通过环境变量（或项目根目录 `.env` 文件，见 `.env.example`）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `OCRS_ENGINES` | `dots,paddle` | 启用的引擎，逗号分隔 |
| `OCRS_MOCK` | `0` | `1` = mock 模式（假结果，联调用） |
| `OCRS_DATA_DIR` | `./data` | 任务与结果存放目录 |
| `OCRS_MAX_PAGES` | `100` | 单个 PDF 页数上限 |
| `OCRS_MAX_UPLOAD_MB` | `200` | 上传大小上限 |
| `OCRS_DOTS_MODEL_PATH` | `./weights/DotsOCR` | dots.ocr 权重目录 |
| `OCRS_DOTS_DEVICE` | `auto` | `auto`/`mps`/`cuda`/`cpu`；auto 在 Mac 上选 mps |
| `OCRS_DOTS_DTYPE` | `auto` | `auto`（mps/cuda→bfloat16，cpu→float32）/`bfloat16`/`float16`/`float32` |
| `OCRS_DOTS_ATTN` | `auto` | 注意力实现；auto→`sdpa`，报错可试 `eager` |
| `OCRS_DOTS_MAX_NEW_TOKENS` | `16384` | 单页最大生成长度；内存紧张可调小 |
| `OCRS_DOTS_DPI` / `OCRS_DOTS_MAX_PIXELS` | `200` / 不限 | PDF 渲染 DPI 与输入像素上限（省内存） |
| `OCRS_PADDLE_DEVICE` | 空 | 空=自动；Linux GPU 可设 `gpu:0`（Mac 仅 cpu） |
| `OCRS_PADDLE_FAST` | `0` | `1` 关闭文档方向分类/矫正/文本行方向，提速 |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/tasks` | multipart 上传 PDF，返回 `{task_id, pages, engines}` |
| `GET` | `/api/tasks/{id}` | 任务状态（每引擎 status/进度/耗时/错误） |
| `GET` | `/api/tasks/{id}/markdown/{engine}` | Markdown 文本（图片相对路径已重写为 `/files/...`） |
| `GET` | `/api/tasks/{id}/download/{engine}` | 下载 `.md` 文件 |
| `GET` | `/api/engines` | 引擎可用性（顶栏徽章数据源） |
| 静态 | `/files/...` | 任务产物（引擎提取的图片等） |

## 项目结构

```
backend/
  app/
    config.py            # 环境变量配置
    pdf_utils.py         # 页数/渲染/图片链接重写
    engines/             # base 抽象 + dots / paddle / mock 三个实现
    tasks.py             # 任务存储、双引擎并行调度（同引擎串行）
    main.py              # FastAPI 路由与静态托管
  tests/                 # mock 模式端到端测试
frontend/                # 无构建步骤的原生 HTML/CSS/JS（marked + DOMPurify + jsdiff 本地化）
scripts/                 # setup.sh / download_dots_weights.py / make_sample_pdf.py
vendor/dots.ocr/         # dots_ocr 代码库（setup.sh 克隆，--no-deps 安装）
data/tasks/{task}/       # 每任务：input.pdf + 各引擎 result.md、pages/、images/
```

## 测试

```bash
cd backend
uv run pytest          # mock 模式端到端（无需模型）
```

## 常见问题

- **dots.ocr 引擎报「未找到模型权重」**：先运行 `scripts/download_dots_weights.py`。
- **MPS 内存不足（16GB 机型同时跑两个引擎紧张）**：可先只启用一个引擎（`OCRS_ENGINES=dots`），或调小 `OCRS_DOTS_MAX_PIXELS`（如 `10035200`）与 `OCRS_DOTS_MAX_NEW_TOKENS`（如 `8192`），或 `OCRS_DOTS_DEVICE=cpu`。
- **dots.ocr 加载报注意力实现错误**：`OCRS_DOTS_ATTN=eager` 兜底（引擎已内置自动降级，一般无需手动设置）。
- **重新执行过 `uv sync` 后 dots 引擎报 `No module named dots_ocr`**：`uv sync` 会移除手动安装的 vendored 包，重跑 `scripts/setup.sh --dots` 或 `cd backend && uv pip install --no-deps -e ../vendor/dots.ocr`。
- **PaddleOCR 首次识别很慢**：在自动下载子模型（几百 MB）。国内网络下 huggingface.co 不可达时，本项目会在启动时自动把 PaddleX 模型源切到百度 BOS（`PADDLE_PDX_MODEL_SOURCE=bos`）；也可手动 export 该变量或 `HF_ENDPOINT=https://hf-mirror.com`。连接检测慢可设 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`。
- **Linux GPU 服务器**：`uv sync --extra dots` 安装的 torch 默认含 CUDA；dots 引擎 `OCRS_DOTS_DEVICE=cuda`；Paddle 需改装 `paddlepaddle-gpu` 并设 `OCRS_PADDLE_DEVICE=gpu:0`。

## 关于两个引擎的输出差异

两个模型的详细对比见上方「[对比的 OCR 模型](#对比的-ocr-模型)」。典型的输出差异：dots.ocr 保留页眉页脚、整页一次生成；PP-StructureV3 专为 PDF→Markdown 设计，会把文档中的图片裁出保存为文件并在 Markdown 中引用。

本项目的 dots 引擎使用 transformers 推理（官方 `DotsOCRParser` 的 HF 路径硬编码 CUDA + flash-attention），在 Mac 上默认 MPS + SDPA + bfloat16，推理流程（prompt → 布局 JSON → `post_process_output` → `layoutjson2md`）与官方一致。
