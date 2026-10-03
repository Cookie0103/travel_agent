# 旅行规划 Agent

从攻略出发，通过对话比较酒店、生成并修改京都 2–3 天行程，确认后模拟预订。模型负责理解需求和编排工具，后端负责事实校验、约束检查和失败恢复。

目标技术栈：Python / FastAPI / PostgreSQL / Next.js；Claude Agent SDK 负责 runtime，自写旅行 tools 与业务规则；DeepSeek 兼容线路与 Claude 原生线路分别验证；MCP；OpenTelemetry + Langfuse。

**现在可以运行网页工作台、旅行工具和模拟预订。** 默认离线演示使用固定脚本与真实业务数据库；真实模式使用 Claude Agent SDK。真实模型完整规划效果、完整多次评测及部分外部验收仍未通过，不能把免费演示当模型能力证明。
当前进度只看 [长程执行计划](docs/execution/travel-agent.md)；阶段性验证自动继续，用户最终集中运行与学习。开发顺序见 [M0 规格](docs/tasks/M0.md)，历史记录从 [文档目录](docs/README.md) 进入。

CLI默认仍用人工 fixtures。数据库已导入 [Wikivoyage](https://en.wikivoyage.org/)（CC BY-SA 4.0）20段攻略与 [OpenStreetMap](https://www.openstreetmap.org/copyright)（© OpenStreetMap contributors, ODbL）146个地点对象；快照有历史和缺失信息，不能当实时事实。酒店与预订均为模拟。

## 运行最小查询

```text
uv run python -m backend.cli "京都有哪些室内景点？"
```

默认不联网、不产生模型费用。完成授权且 .env 配好后，才使用真实模式：

```text
uv run --env-file .env python -m backend.cli --live "京都有哪些室内景点？"
```

真实模式遵守最新授权：DeepSeek 每日最多15 CNY，同时取`.env`更低日预算，无累计金额/次数上限；每run HTTP/工具/修复次数仍有限。其他计费线路未授权。旧 CLI 暂拒绝 @/行首斜杠输入，避免文件展开。

每次查询默认保存本地 OTel Trace：离线在 `.cache/traces/`，真实模式在私有 `.cache/sessions/`。
配置 Langfuse 的 BASE_URL、PUBLIC_KEY、SECRET_KEY 后，可显式追加 `--trace-cloud` 导出摘要；不上传完整对话或工具结果。当前Japan项目已实际通过认证/上传/读回核对，页面需登录查看；见[真实接入证据](docs/evidence/m05-langfuse-cloud-2026-10-04.json)。
网页/API也支持：`uv run --env-file .env python -m backend.server --trace-cloud`。该开关只上传观测摘要，不启用真实模型；默认仍离线。OpenTelemetry无需独立API key，Langfuse的三项配置来自你自己的项目。云导出失败保留本地Trace和已提交业务结果，详细说明见[观测配置](docs/blocked/langfuse.md)。

## 目录放什么

下表是计划职责；建好了目录不代表功能已经实现。

| 目录 | 用途 |
| --- | --- |
| apps/web | 前端页面：聊天、酒店卡片、行程展示和确认按钮 |
| backend | 整个后端：HTTP 接口、Agent、工具、业务规则、模型连接和数据库访问 |
| data | 景点和攻略数据文件、测试样本、导入程序；数据库表定义和读写放 backend/persistence |
| scripts | 开发辅助命令：安装环境、检查代码、启动测试、下载参考代码 |
| tests| 自动测试代码；scripts/dev.py 只是帮你启动这些测试 |
| mock_supplier | 模拟酒店供应商：正常查询/下单，以及超时、重复请求等故障 |
| eval | 评测 Agent 工具选择和结果，保存改编用例；私有运行结果在.cache/eval |
| docs | 实际工作的说明、报告和操作日志 |
| plan | 设计方案、架构和任务计划 |
| vendor | 下载的上游参考代码，不属于我们实现的业务代码，也不提交到 Git |

backend 中只有 api 负责 HTTP；agent 负责旅行上下文与执行策略，providers 接 Claude Agent SDK 承担循环，domain 放业务对象和规则，persistence 放数据库访问。见 [后端目录说明](backend/README.md)。

## 根目录的配置为什么保留

- pyproject.toml、uv.lock、.python-version：Python 版本、依赖和检查规则。
- .pre-commit-config.yaml：提交前检查的配置，工具默认从根目录读取；它不是报告。
- .gitignore、.gitattributes：Git 忽略规则和文本换行方式。
- .env.example：本地配置的空模板；docker-compose.yml：启动数据库的配置。
- AGENTS.md：AI 在本仓库的执行规则；LICENSE：仓库许可。

点开头的本地目录可以隐藏，但不是都可以删除：.git 保存版本历史；本机 .cache/python 装有 Python，.venv 引用了它。隐藏不会影响运行。

## 现在能运行的开发命令

使用 uv 与 Python 3.12，在项目根目录运行（PowerShell / macOS / Linux 通用）：

```text
uv run python scripts/dev.py setup
uv run python scripts/dev.py check
uv run python scripts/dev.py test
uv run python scripts/fetch_upstream.py
```

这些命令用于开发准备，不是启动旅行助手。setup 按 uv.lock 安装依赖并安装本地提交钩子；每次提交执行同一套 check 与离线 test。
默认测试排除 live，不需要 API key。SDK 接入证据见 docs/protocol-agent-sdk.md。
`dev eval-dev` 跑30条历史用例并输出规则分；默认固定工具脚本，分数不代表模型能力。真实基线需显式 `--live`，入口及结果说明见 [eval](eval/README.md)。

本机的 Python 3.12 已装入被忽略的 .cache/python，.venv 已绑定该解释器。
普通新环境由 uv 根据 .python-version 准备解释器；不要把本机 .venv 复制到其他电脑。
uv 缓存放 .cache/uv；dev 脚本统一设置 UTF-8 与子进程缓存，不要求手工设置 shell 环境变量。
dev test 每次使用新的 .cache/pytest-runs/run-* 保存临时文件和缓存，避免终端与 AI 沙箱共用无权限的 pytest 目录；不需要先激活虚拟环境。M1 起集成测试需要下述项目 PostgreSQL，测试自动创建和清理本次专用随机库，不清空开发库。

## 工作台启动

在项目PostgreSQL已启动/迁移/导入快照后，分别运行`uv run python scripts/dev.py api`与`uv run python scripts/dev.py web`，打开http://127.0.0.1:3000。首次需`dev web-setup`安装前端依赖；完整命令见[工作台说明](apps/web/README.md)。默认免费离线演示，真实模式必须显式启用并通过预算。

也可以使用独立容器演示，需 uv 和已启动的 Docker Desktop：

```text
uv run python scripts/dev.py stack-up
uv run python scripts/dev.py stack-status
uv run python -m scripts.smoke_demo
uv run python scripts/dev.py stack-down
```

打开 http://127.0.0.1:3100，创建演示会话、保存条件，再比较酒店或生成行程。专用 API/供应商/PG 端口为8100/8101/5544，均仅本机；与原开发数据库隔离。首次构建需下载锁定依赖；自动迁移/导入快照。停止保留演示数据，再次启动后可运行 `uv run python -m scripts.smoke_demo --verify` 只读检查上次烟测结果。
专用密码在忽略的.cache/demo.env生成，不需要配置模型key；镜像没有启用真实模型或安装Claude CLI。当前容器用于离线业务演示，真实SDK走已核定宿主入口与原预算账本。不要删除专用密码后继续复用原卷。Langfuse沿用Cloud方案，真实上传/读回已验，宿主API显式启用；容器默认不传密钥，浏览器UI验收仍待登录。详见[容器交付记录](docs/review/M4.md)。

## 模型预算配置

在本地 .env 配置密钥与预算；.env.example 只保留空变量名，不填写真实密钥。
现有 Messages 探针通过 DEEPSEEK_MODEL 明确选择模型，当前支持 deepseek-flash 或 deepseek-v4-pro；这次最小实测选 deepseek-flash。换模型时按该模型人民币单价计费，未知模型拒绝调用，不会偷偷使用默认模型或 claude-* 映射。

| 配置 | 用途 | 单位 |
| --- | --- | --- |
| DAILY_BUDGET_CNY | DeepSeek 每日预算 | 人民币元 |
| DAILY_BUDGET_USD | Anthropic每日预算；当前无美元调用授权 | 美元 |

两条线路独立记账，不自动换汇或借用余额；兼容 API 的 SDK 名称不改变计费来源。
0 表示禁用该线路；空白、非法或缺少预算时拒绝真实调用。预算不能替代用户授权，最新DeepSeek每日15 CNY硬限及未授权USD0见执行计划；未结预占与旧费继续计入，日界沿用UTC。
`uv --env-file .env`加载配置；`LLM_PROVIDER`默认deepseek，也可显式anthropic。DeepSeek使用DEEPSEEK_MODEL；Claude使用ANTHROPIC_MODEL，当前仅核定固定claude-haiku-4-5-20251001。共用Claude Agent SDK、旅行工具与费用守卫；原币种报告和账本隔离，USD累计授权0金额/0次数会在SDK启动前拦截。真实SDK/CLI本地脚本已验证，Anthropic真实服务与最新Sonnet协议未验，不因填key/每日预算自动调用。
旧Messages探针的最小实测与有限授权记录保留；不要删除.cache账本重复获得额度。当前SDK接入与业务验证见[SDK实测](docs/protocol-agent-sdk.md)，旧探针[实测矩阵](docs/protocol-deepseek.md)不能代替当前runtime验收。
旧探针两请求授权已用完；本轮长程开发的 DeepSeek 整体额度见执行计划，同时遵守 .env 每日预算。SDK 美元估算不能代替人民币预算。新接入验收与费用边界见 [ADR-003](docs/adr/003-claude-agent-sdk-runtime.md)。
历史批次限制见 [M0.2 准备记录](docs/operations/2026-10-03-m02-preparation.md)。

## PostgreSQL 配置

项目使用 Docker PostgreSQL 17，默认仅绑定 127.0.0.1:5434；不占用本机已安装服务的 5432/5433。
新环境复制 .env.example 为 .env，填写 POSTGRES_PASSWORD；POSTGRES_USER / POSTGRES_DB 默认 travel_agent。
DATABASE_URL 可留空，由这些字段安全组合；如果填写则优先使用，需为 PostgreSQL psycopg 连接。
本机已填写数据库配置并启动容器；密码只存本地 .env。启动 Docker Desktop 后执行：

```text
uv run python scripts/dev.py db-up
uv run python scripts/dev.py db-migrate
uv run python -m data.import_catalog
uv run python -m backend.server
```

API 在 http://127.0.0.1:8000/docs 展示接口；/health 检查数据库。
本地 .env 的 DEMO_MODE=true 启用 POST /demo/login，返回一次性展示的演示令牌；后续 /sessions 请求带 Authorization: Bearer <token>。
演示身份用于本机开发，不是生产登录。令牌仅保存摘要，24 小时过期；不能指定他人的 user_id 登录。
Windows 服务入口使用兼容 psycopg 的事件循环。数据库迁移在 backend/persistence/migrations，当前包含身份、会话、目录、旅行条件、Evidence和TaskRun/事件。
check 不连接数据库；test 会检查真实事务和用户隔离。CI 已配置 PostgreSQL 服务，尚未推送或远端运行。

发消息：`POST /sessions/{id}/messages`，传 `client_message_id`（UUID）、`text`；默认 `mode=offline`。
查询 `/runs/{id}`，进度读 `/runs/{id}/events`（SSE，可带 `Last-Event-ID`），取消用 `POST /runs/{id}/cancel`。
重复消息ID返回原执行；新一轮需新UUID。离线固定流程用于检查工具和数据，不代表模型自主规划。
需要真实模型时，显式用 `uv run --env-file .env python -m backend.server --live` 启动，并把该条消息的mode设为live；DeepSeek遵守每日15 CNY/更低配置及每run保护，USD仍未授权，不自动切换供应商。

## 审阅与中断恢复

从[源码学习索引](docs/review/learning.md)顺着入口理解关键模块，再按[三段演示](docs/review/demos.md)复现业务与失败恢复。真实模型规划和外部验收缺口仍以执行计划为准。

- [SDK 路线调整与恢复点](docs/operations/2026-10-03-agent-sdk-docs.md)：本轮文档修改、核查和验证。
- [修复与环境核对记录](docs/operations/2026-10-03-development-errors.md)：从这里判断现在的检查结果。
- [M0.1 审阅材料](docs/review/M0.1.md)：阅读顺序、失败证据和理解问题。
- [修复批次总结](docs/review/batch/2026-10-03-m0-repair.md)、[首次批次记录](docs/review/batch/2026-10-02-m0-core.md)。
- [文档汇总](docs/README.md)、[阻塞记录汇总](docs/blocked/README.md)、[待审阅决定](docs/decisions-pending.md)、[上游复用清单](docs/reuse.md)。

恢复前先检查 Git 状态；日志“开始”不代表成功。工程修复与旧探针增量已由 batch/2026-10-03-travel-autonomous 承接，按执行计划持续推进；旧批次和审阅记录保留作历史证据。
