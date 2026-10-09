# ocrs · PDF 多引擎识别与生产化解析工具链

上传一份 PDF，**文字层直提**、**dots.ocr** 与 **PaddleOCR (PP-StructureV3)** 多引擎识别，网页上并排对比 Markdown 提取效果（渲染预览 / 源码 / 行级差异），并可分别下载 `.md` 文件。所有处理均在本机完成。

除对比台外，本项目内置一套**大规模解析工具链**：页面路由（文字层/扫描页分流）、PDF 分片并行、懒渲染省内存、布局 JSON 切块入库（带溯源元数据）、金标 CER 回归——见下方[「大规模解析（生产部署）」](#大规模解析生产部署)。

```
┌──────────┐   PDF    ┌──────────────────────────────────────────┐
│  浏览器   │ ───────► │  FastAPI 后端                             │
│ 上传/对比 │ ◄─────── │  ├─ digital 文字层直提 (PyMuPDF) ────────► digital/result.md + route.json
└──────────┘  轮询    │  ├─ dots.ocr 引擎 (transformers) ────────► dots/result.md + pages/*.json
                      │  └─ PaddleOCR PP-StructureV3 ────────────► paddle/result.md
                      └──────────────────────────────────────────┘
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

- **上传 PDF**（拖拽 / 点击），自动统计页数，多引擎识别，逐页进度实时展示
- **文字层直提引擎（digital）**：有文字层的页零误差直接抽取（毫秒级/页），扫描页标记「需 OCR」并输出 `route.json` 路由清单
- **双栏对比**：dots.ocr、PaddleOCR（及 digital）渲染预览与 Markdown 源码两种视图，可同步滚动
- **差异对比**：行级双栏 diff（红色 = 左侧独有，绿色 = 右侧独有）
- **下载**：分别下载各引擎的完整 `.md`；PP-StructureV3 提取的图片也会保存并可在预览中显示
- **分片任务**：`POST /api/tasks?page_start=&page_end=` 只识别指定页区间，配合 `scripts/shard_pdf.py` 支撑大文档并行
- **切块入库**：`scripts/chunk_result.py` 把布局 JSON 切成带 `doc/page/bbox/category/heading` 溯源的 `chunks.jsonl`
- **金标回归**：`scripts/eval_golden.py` 逐页 CER 评测，管线改动前后对比精度
- **容错**：单个引擎失败（未装依赖 / 缺权重 / 推理报错）不影响其他引擎，错误详情直接展示在页面上
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

## 模型下载（fork 后从这里开始）

本项目涉及的全部模型/权重只有三处，均无需手动找链接，按表格执行即可：

| # | 组件 | 体积 | 你需要做什么 |
| --- | --- | --- | --- |
| 1 | **dots.ocr 模型权重**（`dots-studio/dots.ocr`，约 3B 参数，含视觉编码器） | **6.08 GB** | 执行一键脚本（见下），下载到 `weights/DotsOCR`，支持断点续传 |
| 2 | **dots_ocr 推理代码**（prompt / 后处理 / JSON→Markdown 工具链） | 约 1 MB | 无需手动操作，`scripts/setup.sh --dots` 自动 `git clone` 到 `vendor/dots.ocr` 并安装 |
| 3 | **PaddleOCR PP-StructureV3 子模型**（14 个，含版面/检测/识别/表格/公式，合计约 1.7 GB） | 1.7 GB | 无需手动操作，首次识别自动下载缓存到 `~/.paddlex/official_models`（国内自动切百度 BOS 源） |

**一键下载命令（组件 1）**：

```bash
cd backend
uv run python ../scripts/download_dots_weights.py              # 自动测速选择 HuggingFace / hf-mirror / ModelScope 最快源
uv run python ../scripts/download_dots_weights.py --source modelscope   # 也可强制指定源
```

组件 1 的**官方发布页**（如需手动浏览器下载，下载全部 20 个文件放入 `weights/DotsOCR/`，注意目录名不能带点）：

| 渠道 | 直链 | 说明 |
| --- | --- | --- |
| HuggingFace 官方 | <https://huggingface.co/dots-studio/dots.ocr> | 原 `rednote-hilab/dots.ocr`，组织已更名 `dots-studio` |
| 国内镜像 hf-mirror | <https://hf-mirror.com/dots-studio/dots.ocr> | HuggingFace 全量镜像，无需科学上网 |
| ModelScope 魔搭 | <https://modelscope.cn/models/dots-studio/dots.ocr> | 国内 CDN，实测约 3.4 MB/s |
| 代码仓库（组件 2） | <https://github.com/rednote-hilab/dots.ocr> | master 分支，setup.sh 自动克隆 |

> 只想用 PaddleOCR 引擎？组件 1、2 都可以跳过：`scripts/setup.sh --paddle` 后直接启动即可（`OCRS_ENGINES=paddle`）。

**fork 后完整跑通的三条命令**：

```bash
scripts/setup.sh --all                                            # 依赖 + dots_ocr 代码
cd backend && uv run python ../scripts/download_dots_weights.py   # dots.ocr 权重（6GB，断点续传）
uv run uvicorn app.main:app --port 8000                           # 启动，Paddle 子模型首跑自动下载
```

## 配置

所有配置通过环境变量（或项目根目录 `.env` 文件，见 `.env.example`）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `OCRS_ENGINES` | `digital,dots,paddle` | 启用的引擎，逗号分隔 |
| `OCRS_MOCK` | `0` | `1` = mock 模式（假结果，联调用） |
| `OCRS_PARALLEL` | `auto` | 引擎执行方式：按当前可用内存自动判定（多引擎工作集装得下就并行、装不下就串行）；`1` 强制并行；`0` 强制串行 |
| `OCRS_DATA_DIR` | `./data` | 任务与结果存放目录 |
| `OCRS_MAX_PAGES` | `100` | 单任务（或分片）页数上限 |
| `OCRS_MAX_UPLOAD_MB` | `200` | 上传大小上限 |
| `OCRS_DOTS_MODEL_PATH` | `./weights/DotsOCR` | dots.ocr 权重目录 |
| `OCRS_DOTS_DEVICE` | `auto` | `auto`/`mps`/`cuda`/`cpu`；auto 在 Mac 上选 mps |
| `OCRS_DOTS_DTYPE` | `auto` | `auto`（mps/cuda→bfloat16，cpu→float32）/`bfloat16`/`float16`/`float32` |
| `OCRS_DOTS_ATTN` | `auto` | 注意力实现；auto→`sdpa`，报错可试 `eager` |
| `OCRS_DOTS_MAX_NEW_TOKENS` | `16384` | 单页最大生成长度；内存紧张可调小 |
| `OCRS_DOTS_DPI` / `OCRS_DOTS_MAX_PIXELS` | `200` / 不限 | PDF 渲染 DPI 与输入像素上限（省内存） |
| `OCRS_PADDLE_DEVICE` | 空 | 空=自动探测（有 CUDA 用 `gpu:0`，否则 `cpu`；Mac 必然 cpu） |
| `OCRS_PADDLE_PROFILE` | `accurate` | PaddleOCR 精度/速度三档：`accurate` 官方默认全开；`balanced` 关方向分类/矫正/文本行方向（保留公式，推荐清晰电子 PDF）；`fast` 用 mobile 检测识别并关闭公式识别（CPU 数秒/页） |
| `OCRS_PADDLE_FAST` | `0` | `1` 关闭文档方向分类/矫正/文本行方向，提速 |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/tasks?page_start=0&page_end=100` | multipart 上传 PDF；可选分片页码区间（左闭右开绝对页码，省略=整本），返回 `{task_id, pages, engines, page_start, page_end}` |
| `GET` | `/api/tasks/{id}` | 任务状态（每引擎 status/进度/耗时/错误） |
| `GET` | `/api/tasks/{id}/markdown/{engine}` | Markdown 文本（图片相对路径已重写为 `/files/...`） |
| `GET` | `/api/tasks/{id}/download/{engine}` | 下载 `.md` 文件 |
| `GET` | `/api/engines` | 引擎可用性（顶栏徽章数据源） |
| 静态 | `/files/...` | 任务产物（引擎提取的图片、route.json 等） |

## 跨平台运行（Mac / Windows / Linux · 有无 GPU）

代码不绑定任何平台：路径全部 `pathlib`、worker 用 `sys.executable` 拉起、设备自动探测（CUDA → MPS → CPU）、内存调度探测覆盖三平台（macOS `memory_pressure` / Windows `GlobalMemoryStatusEx` / Linux `/proc/meminfo`）。各组合的开箱行为：

| 环境 | digital | dots.ocr | paddle |
| --- | --- | --- | --- |
| macOS（Apple 芯片） | ✅ | ✅ MPS + bf16（自动） | ✅ CPU（**Mac 轮子无 MKLDNN/GPU**，慢，见 FAQ） |
| Windows / Linux + NVIDIA GPU | ✅ | ✅ CUDA（需 CUDA 版 torch） | ✅ `gpu:0`（需 `paddlepaddle-gpu`） |
| Windows / Linux 无 GPU | ✅ | ✅ CPU（慢） | ✅ CPU |

**跑之前先预检（不要等跑起来才发现装错）**：

```bash
python scripts/check_env.py          # 秒级静态检查：依赖/权重/每个引擎实际将使用的设备/装错版本警告
python scripts/check_env.py --smoke  # 深度自检：每引擎真跑一页（加载模型，dots 较慢）
```

典型输出（Mac）：`torch 2.14.0 · CUDA构建=无 · mps`、`dots · device=mps dtype=bfloat16 attn=sdpa`、`paddle · device=cpu`。
典型「装错」警告（Windows/Linux）：**「检测到 NVIDIA GPU，但 paddlepaddle 为 CPU 版：请改装 paddlepaddle-gpu」**、**「torch 为 CPU 构建；若本机有 NVIDIA 显卡，请安装 CUDA 版 torch」**。退出码非零可挂 CI 或部署前检查。启动后 `/api/engines` 与 worker 日志也带同样的设备信息。

**Windows + NVIDIA GPU 安装**（PowerShell，用 `uv` 或 `pip` 均可）：

```powershell
git clone <repo> ; cd ocrs/backend
uv venv ; .venv\Scripts\activate
uv pip install -e ".[dots,paddle]"                # 基础依赖（与 setup.sh 等价）
uv pip install torch --index-url https://download.pytorch.org/whl/cu121   # CUDA 版 torch（按 CUDA 版本选 cu121/cu124）
uv pip install paddlepaddle-gpu==3.0.0            # GPU 版 paddle（版本需与本机 CUDA 匹配，见 paddle 官网)
uv run python ..\scripts\download_dots_weights.py # dots 权重
uv run python ..\scripts\check_env.py             # 预检应显示 dots · device=cuda、paddle · device=gpu:0
uv run uvicorn app.main:app --port 8000
```

Linux GPU 服务器同理（`uv sync --extra dots` 的 torch 默认含 CUDA；Paddle 换装 `paddlepaddle-gpu` 并设 `OCRS_PADDLE_DEVICE=gpu:0`）。

## 大规模解析（生产部署）

单机逐页串行跑千万页需要百年量级；生产做法是**让每页只花它需要的算力，让贵的算力永远满载**。本项目已内置可在本机验证的部分，其余为部署指引：

```
大 PDF ──① 切分片──► 分片文件/分片任务 ──② 路由──► 有文字层 ──► digital 直提（毫秒/页，零误差）
                                        └─► 扫描页 ──► dots/paddle 分片任务（GPU 批处理）
                                                  ──► 布局 JSON ──③ 切块──► chunks.jsonl ──► 向量库
                                                  ──► 金标集 ──④ CER 回归（改管线必跑）
```

**① 切分与并行**（本机可用）：`scripts/shard_pdf.py` 把大 PDF 切成 ≤100 页的分片文件（含 manifest.json），或直接 `POST /api/tasks?page_start=&page_end=` 发分片任务；分片失败只需重跑该分片。引擎侧 dots 已改懒渲染（内存同时只保留一页，原先整本渲染约 11.6MB/页会在千页级 OOM）。

**② 路由分流**（本机可用，最大的提速杠杆）：digital 引擎先跑整本（秒级），产出 `route.json` 列出全部扫描页；只有这些页才值得发 dots/paddle 任务。企业语料中文字层页通常占 50–90%，OCR 负载等比下降，且文字层抽取精度高于任何 OCR。

**③ 切块入库**（本机可用）：`python scripts/chunk_result.py data/tasks/<id>/dots --doc-id xxx` 产出 `chunks.jsonl`，每块带 `doc_id/page/bbox/category/heading` 溯源；表格/公式保持结构化不拆散，标题上下文注入每个 chunk。**不要走「OCR→Markdown→再切 Markdown」的二次解析弯路**。

**④ 金标回归**（本机可用）：人工校对 200–500 页金标（`data/golden/<doc>/golden.md`，页间 `---` 分隔），`python scripts/eval_golden.py result.md golden.md --cer 0.05 --verbose` 输出逐页 CER、超阈值退出码 1，可挂 CI。任何换引擎/换 profile/改 DPI 的改动先过金标。

**生产部署升级点**（本机无法验证，按此映射扩容）：

| 环节 | 本项目现状 | 生产替换 |
| --- | --- | --- |
| 任务分发 | 任务目录文件协议（`.job`/`.state.json`） | Kafka/SQS + 对象存储；worker 消费分片消息，文件协议语义不变 |
| dots 推理 | transformers 单流（M5 约 50–110 秒/页） | **vLLM 连续批处理**（`weights/DotsOCR/modeling_dots_ocr_vllm.py` 官方自带）：单张 A100/H100 有效 3–8 页/秒，8 卡节点约 30–60 页/秒 |
| paddle 推理 | 单进程 CPU（accurate 约 140 秒/页） | `paddlepaddle-gpu` + `OCRS_PADDLE_DEVICE=gpu:0`（约 1–2 秒/页/卡），多 worker 分片并行 |
| 并行度 | 每引擎一个 worker | worker 无状态水平扩容，按分片幂等重跑 |

容量测算参考：3000 万页、70% 有文字层 → digital 直提数小时（CPU 节点），剩 900 万扫描页走 8×A100 vLLM 约 2–4 天，切块入库约 1 天——**周级完成，且留有重跑余量**。

## 项目结构

```
backend/
  app/
    config.py            # 环境变量配置
    router.py            # 页面路由：文字层检测 + 质量打分（digital/scanned）
    pdf_utils.py         # 页数/懒渲染（iter_page_images）/图片链接重写
    engines/             # base 抽象 + digital / dots / paddle / mock 实现（支持分片 page_range）
    tasks.py             # 任务存储、多引擎调度（同引擎串行）
    worker.py            # 引擎 worker 子进程：消费 .job、写 .state.json、支持分片 spec
    chunker.py           # 布局 JSON → 带溯源元数据的 chunk（表格/公式不拆散）
    eval_cer.py          # CER 指标：normalize / 编辑距离 / 按页对齐报告
    main.py              # FastAPI 路由与静态托管
  tests/                 # mock 模式端到端 + 路由/分片/切块/CER 单元测试
frontend/                # 无构建步骤的原生 HTML/CSS/JS（marked + DOMPurify + jsdiff 本地化）
scripts/                 # setup.sh / download_dots_weights.py / make_sample_pdf.py / shard_pdf.py / chunk_result.py / eval_golden.py
vendor/dots.ocr/         # dots_ocr 代码库（setup.sh 克隆，--no-deps 安装）
data/tasks/{task}/       # 每任务：input.pdf + 各引擎 result.md、pages/、route.json、chunks.jsonl
```

## 测试

```bash
cd backend
uv run pytest          # mock 模式端到端（无需模型）
```

## 常见问题

- **dots.ocr 引擎报「未找到模型权重」**：先运行 `scripts/download_dots_weights.py`。
- **MPS 内存不足（16GB 机型同时跑两个引擎紧张）**：可先只启用一个引擎（`OCRS_ENGINES=dots`），或调小 `OCRS_DOTS_MAX_PIXELS`（如 `10035200`）与 `OCRS_DOTS_MAX_NEW_TOKENS`（如 `8192`），或 `OCRS_DOTS_DEVICE=cpu`。
- **Mac 实测参考（M5 / 16GB）**：dots.ocr 约 50–110 秒/页（MPS bf16，视觉塔已打 SDPA 补丁避免 OOM）；PaddleOCR 约 1–3 秒/页（CPU）；两引擎并行约需 7GB + 2GB 内存，16GB 机型可同时跑。GPU 服务器上 dots.ocr 会快一个数量级。
- **dots.ocr 加载报注意力实现错误**：`OCRS_DOTS_ATTN=eager` 兜底（引擎已内置自动降级，一般无需手动设置）。
- **重新执行过 `uv sync` 后 dots 引擎报 `No module named dots_ocr`**：`uv sync` 会移除手动安装的 vendored 包，重跑 `scripts/setup.sh --dots` 或 `cd backend && uv pip install --no-deps -e ../vendor/dots.ocr`。
- **PaddleOCR 首次识别很慢**：在自动下载子模型（几百 MB）。国内网络下 huggingface.co 不可达时，本项目会在启动时自动把 PaddleX 模型源切到百度 BOS（`PADDLE_PDX_MODEL_SOURCE=bos`）；也可手动 export 该变量或 `HF_ENDPOINT=https://hf-mirror.com`。连接检测慢可设 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`。
- **Linux GPU 服务器**：`uv sync --extra dots` 安装的 torch 默认含 CUDA；dots 引擎 `OCRS_DOTS_DEVICE=cuda`；Paddle 需改装 `paddlepaddle-gpu` 并设 `OCRS_PADDLE_DEVICE=gpu:0`。
- **Mac 上 PaddleOCR 为什么慢、内存/CPU 都跑不满？** macOS ARM 版 paddlepaddle 轮子不含 oneDNN（MKLDNN），CPU 推理走单线程参考 BLAS，`cpu_threads` 参数无效；此时瓶颈是公式识别 FormulaNet-L 的自回归解码。M5 实测（学术论文首页）：balanced 带公式 **15min+/页**、balanced 关公式（`OCRS_PADDLE_FORMULA=0`）**~63s/页**、fast 档 **~23s/页**（文本输出与 server 档几乎一致，但无公式 LaTeX）。公式密集文档在 Mac 上建议用 dots.ocr（MPS 加速）；Paddle 跑公式请上 Linux GPU。

## 关于两个引擎的输出差异

两个模型的详细对比见上方「[对比的 OCR 模型](#对比的-ocr-模型)」。典型的输出差异：dots.ocr 保留页眉页脚、整页一次生成；PP-StructureV3 专为 PDF→Markdown 设计，会把文档中的图片裁出保存为文件并在 Markdown 中引用。

本项目的 dots 引擎使用 transformers 推理（官方 `DotsOCRParser` 的 HF 路径硬编码 CUDA + flash-attention），在 Mac 上默认 MPS + SDPA + bfloat16，推理流程（prompt → 布局 JSON → `post_process_output` → `layoutjson2md`）与官方一致。
