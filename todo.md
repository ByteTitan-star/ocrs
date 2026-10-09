# ocrs 生产化改造 TODO

> 目标：把「单机演示级」的双引擎对比工具，改造成支撑千万页级 PDF 解析与切块入库的生产架构骨架。
> 原则：精度由「文字层优先 + 分片可回归」保证，速度由「路由分流 + 懒渲染 + 分片并行」保证。
> 每项完成后勾选并在「验证」处记录实际证据（测试命令/输出）。

## P1 路由层：文字层检测 + 质量打分

- [x] 新增 `backend/app/router.py`：`classify_pages(pdf_path)` 逐页判定 `digital`（有文字层且质量达标）/ `scanned`（需 OCR）
- [x] 质量分：有效字符数 + 可打印字符占比，防止老扫描件内嵌的劣质 OCR 文字层误判
- 验证：`pytest tests/test_router.py` ✅ 5 passed（文字页/扫描页/劣质文字层/分页区间/汇总报告）

## P2 digital 引擎：文字层直接结构化抽取

- [x] 新增 `backend/app/engines/digital.py`：PyMuPDF 按块抽取 → Markdown（字号启发式标标题），扫描页输出「需 OCR」占位符
- [x] 同时落盘 `route.json`（每页路由判定），作为后续只对扫描页发起 OCR 任务的依据
- [x] 注册进引擎表（含 mock），worker 调度表加入 digital（优先级最高、内存最低）
- 验证：`pytest tests/test_digital_engine.py` ✅ 3 passed；`/api/engines` 默认含 digital（config 默认引擎改为 digital,dots,paddle）

## P3 dots 引擎：懒渲染 + 去全量内存拼接

- [x] `pdf_utils.py` 新增 `iter_page_images()`：逐页渲染生成器（保留 >4500px 降采样逻辑），替换整本 `load_images_from_pdf`
- [x] 去掉 `parts` 全量内存拼接（result.md 已逐页增量写，返回值无人消费）
- 验证：`pytest tests/test_pdf_utils.py` ✅ 3 passed（全量/分片页码、DPI 缩放、巨型页降采样、惰性）

## P4 引擎协议支持分片（page_range）

- [x] `base.py` 的 `run/_run` 增加 `page_range: tuple[int, int] | None`，各引擎适配
- [x] paddle：`page_range` → `predict(page_indexes=...)` 透传（已核实 paddlex 支持）
- [x] dots：`iter_page_images` 按 `page_range` 截取
- [x] worker：从 job spec 读取 `page_start/page_end` 传给引擎，进度显示绝对页码；`append_page_markdown` 以文件存在性决定分隔线（分片起点正确）
- 验证：`pytest tests/test_page_range.py` ✅ 4 passed（spec 解析、mock 分片、paddle 假管线断言 page_indexes 透传与增量写入、整本不传参）

## P5 分片任务模型 + 切分工具

- [x] `POST /api/tasks` 支持 `page_start/page_end` 查询参数，分片大小仍受 `OCRS_MAX_PAGES` 约束（page_end 超出文档页数时收敛到末页）
- [x] 新增 `scripts/shard_pdf.py`：大 PDF 按页区间切成分片文件 + manifest.json（生产侧再换消息队列，文件协议保留）
- 验证：`pytest tests/test_shard_api.py` ✅ 3 passed（mock 全流程分片上传→只含分片页、参数校验、脚本切分与页序一致性）；`shard_pdf.py` 对 data/sample.pdf 冒烟 ✅

## P6 切块器：布局 JSON → chunk + 溯源

- [x] 新增 `backend/app/chunker.py`：dots 的 cells JSON（bbox/category/text）→ chunk（doc/page/bbox/category/heading 元数据），相邻同类小块合并、表格/公式不拆散、超长块按段落切
- [x] markdown 兜底路径：result.md 按 `---` 分页 + 标题切
- [x] 新增 `scripts/chunk_result.py`：任务工作目录 → `chunks.jsonl`（优先 pages/page_*.json，兜底 result.md）
- 验证：`pytest tests/test_chunker.py` ✅ 6 passed（合并与 bbox 联合、结构块隔离、超长切分、标题跨页传递、坏页容错、markdown 兜底、脚本冒烟）

## P7 金标回归：CER 评测

- [x] 新增 `backend/app/eval_cer.py`：normalize / edit_distance / cer / 按页对齐 report（页数不齐时缺失页计满分错误）
- [x] 新增 `scripts/eval_golden.py`：result.md vs golden.md 逐页 CER，`--cer` 阈值退出码非零（可挂 CI）
- 验证：`pytest tests/test_eval_cer.py` ✅ 5 passed（经典编辑距离用例、空白归一、按页对齐/缺失页、脚本 PASS/FAIL 退出码）

## P8 文档：生产部署指引

- [x] README 新增「大规模解析（生产部署）」：路由 → 切分 → 队列（文件协议的替换点）→ vLLM 批处理部署 dots → 切块入库的全链路映射，含容量测算
- [x] README 更新分片/切块/评测用法示例；同步更新 .env.example、前端三引擎兼容（弹性列宽 + diff 固定对比 dots/paddle）
- 验证：README 中新命令逐一冒烟通过（shard_pdf ✅ / chunk_result ✅ 真实任务 10 块 / eval_golden ✅ 自比对 PASS）；真实模式 e2e（非 mock）：digital 分片任务 2 页 12ms 完成，route.json 正确；全量回归 `pytest` ✅ 34 passed

## 完成状态汇总（2026-10-09）

| 阶段 | 关键产物 | 验证 |
| --- | --- | --- |
| P1 路由 | `app/router.py` | 5 tests |
| P2 digital 引擎 | `engines/digital.py`（+route.json） | 3 tests + 真实 e2e |
| P3 懒渲染 | `pdf_utils.iter_page_images` | 3 tests |
| P4 分片协议 | base/dots/paddle/worker page_range | 4 tests |
| P5 分片模型 | API page_start/end + `scripts/shard_pdf.py` | 3 tests + 冒烟 |
| P6 切块器 | `app/chunker.py` + `scripts/chunk_result.py` | 6 tests + 真实数据 10 块 |
| P7 金标回归 | `app/eval_cer.py` + `scripts/eval_golden.py` | 5 tests + 自比对 PASS |
| P8 文档 | README 生产部署节 + .env.example + 前端兼容 | 命令逐一可执行 |

单机演示到生产架构的差距（消息队列、vLLM serving、GPU 集群）已在 README「生产部署升级点」表格中给出映射，部署时按表替换即可。

## P9 进度可视化：页码进度 + 预估完成时间

- [x] 前端：进度卡片新增醒目计数行——`63% · 第 38/60 页 · 已用时 0:17 · 平均 0.5s/页 · 预计剩余 0:10`；排队态说明串行调度原因；完成态显示总用时
- [x] 后端：修复引擎加载完成首报 `progress(0,0)` 把 total 覆盖为 0 的 bug（total=0 不再写入状态）
- [x] 前端兜底：total 未上报时回退到任务页数
- 验证：mock 服务（8001）+ 浏览器实测截图确认三卡片进度条/页码/ETA 渲染正常；全量回归 34 passed

## P11 跨平台兼容：环境预检（doctor）+ Windows 支持

- [x] `app/env_check.py`：三平台内存探测（macOS/Windows/Linux）、torch/paddle 设备指纹（CUDA 构建/MPS/设备名/显存）、「装错版本」静态警告（有 NVIDIA 卡但 paddle/torch 是 CPU 版等）
- [x] 引擎新增 `device_detail()`（不加载权重）：dots/paddle/digital 报告实际将使用的设备；`/api/engines` 与 worker 启动日志均携带
- [x] `scripts/check_env.py` doctor：静态检查秒级、`--smoke` 深度自检（真跑一页）、`--json`、退出码可挂 CI
- [x] README「跨平台运行」：平台×GPU 矩阵、Windows GPU 安装步骤、doctor 用法
- 验证：`pytest` ✅ 39 passed（警告规则/报告结构/CLI）；本机 doctor 实跑输出正确（torch mps / paddle cpu / 三引擎 OK）

## P12 公式识别平台默认：macOS 自动关闭

- [x] `config.py`：`OCRS_PADDLE_FORMULA` 未显式设置时取平台默认——darwin=0（关），其他平台=空（跟随 profile 开）；显式设置永远优先
- [x] paddle 引擎 availability 详情显示公式开关状态（/api/engines 徽章可见「公式开/关」）
- 验证：`pytest` ✅ 41 passed（平台默认函数、Mac 默认落到引擎参数）；本机实测无环境变量时 `PADDLE_FORMULA='0'`、`use_formula_recognition=False`、徽章显示「公式关」

## P13 平台默认再进一档：macOS 默认 fast profile

- [x] `config.py`：`OCRS_PADDLE_PROFILE` 未显式设置时取平台默认——darwin=fast（mobile 模型 ~23s/页，抗内存饥饿），其他平台=accurate；显式设置永远优先
- [x] .env 不再固定 balanced，交由平台默认
- 验证：`pytest` ✅ 42 passed；`/api/engines` 显示 profile=fast · 公式关（Mac 两级平台默认叠加生效）

## P14 前端设备徽章：系统 + GPU 状态展示

- [x] `/api/engines` 新增 `system` 字段（`env_check.system_overview`，进程内缓存一次）：OS/GPU 类型与有无/可用内存/装错警告
- [x] 前端顶栏第一个徽章显示 `macOS 25.4.0 · GPU: MPS · Apple 统一内存 · 可用内存 12GB`，悬停显示完整摘要与警告（只读展示，不影响任何逻辑）
- 验证：`pytest` ✅ 43 passed（system 字段结构）；本机实测徽章数据显示正确

## P15 dots.ocr 图片落地：base64 内联改文件引用

- [x] 定位：vendor `layoutjson2md` 把 Picture 块裁剪后内联为 `![](data:image/...;base64,...)`
- [x] `engines/dots.py` 新增 `extract_data_uri_images`：解码落盘 `images/dots_p{页码}_{序号}.png`，改写相对路径引用（与 paddle 行为对齐；result.md 瘦身、前端 /files 直出、切块不携带 base64）
- 验证：`pytest` ✅ 45 passed（解码正确性、绝对页码命名、多图递增、纯文本不受影响）

## 明确不做（YAGNI，留待生产环境）

- Redis/Kafka 队列接入：文件 job 协议已是可替换边界，部署时换传输层即可
- vLLM serving 客户端：M5 无 CUDA 无法验证，README 记录部署方式
- 自动混合编排（digital 结果自动触发 dots 只跑扫描页）：由路由产物 route.json + 分片参数组合实现，不引入调度器
