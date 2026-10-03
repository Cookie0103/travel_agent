# 旅行规划 Agent

从攻略出发，通过对话比较酒店、生成并修改京都 2–3 天行程，确认后模拟预订。模型负责理解需求和编排工具，后端负责事实校验、约束检查和失败恢复。

目标技术栈：Python / FastAPI / PostgreSQL / Next.js；Claude Agent SDK 负责 runtime，自写旅行 tools 与业务规则；DeepSeek 兼容线路与 Claude 原生线路分别验证；MCP；OpenTelemetry + Langfuse。

**目前还不能使用这个旅行助手。** 已有工程骨架和旧 M0.2 的有限 Messages 探针（70 项离线测试、2 次真实请求的最小往返），没有旅行运行时、前端、HTTP 业务或数据库业务实现。
2026-10-03 用户确认改用 Claude Agent SDK，本轮已更新文档，尚未安装/接入 SDK。当前进度只看 [长程执行计划](docs/execution/travel-agent.md)；阶段性验证自动继续，用户最终集中运行与学习。开发顺序见 [M0 规格](docs/tasks/M0.md)，历史记录从 [文档目录](docs/README.md) 进入。

数据来源：攻略来自 [Wikivoyage](https://en.wikivoyage.org/)（CC BY-SA），地点来自 [OpenStreetMap](https://www.openstreetmap.org/copyright)（© OpenStreetMap contributors, ODbL）。酒店与预订均为模拟数据。

## 目录放什么

下表是计划职责；建好了目录不代表功能已经实现。

| 目录 | 用途 |
| --- | --- |
| apps/web | 前端页面：聊天、酒店卡片、行程展示和确认按钮 |
| backend | 整个后端：HTTP 接口、Agent、工具、业务规则、模型连接和数据库访问 |
| data | 景点和攻略数据文件、测试样本、导入程序；数据库表定义和读写放 backend/persistence |
| scripts | 开发辅助命令：安装环境、检查代码、启动测试、下载参考代码 |
| tests| 自动测试代码；scripts/dev.py 只是帮你启动这些测试 |
| mock_supplier | 以后模拟酒店供应商：正常查询/下单，以及超时、重复请求等故障 |
| eval | 以后评测 Agent 回答和工具选择，保存用例与结果 |
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
默认测试排除 live，不需要 API key。另有 M0.2 有限协议探针，真实验证结果见 docs/protocol-deepseek.md；正式 SDK 适配、CLI 和 eval.run 尚未实现。
`dev eval-dev` 在 M0.6 前明确返回未实现错误。

本机的 Python 3.12 已装入被忽略的 .cache/python，.venv 已绑定该解释器。
普通新环境由 uv 根据 .python-version 准备解释器；不要把本机 .venv 复制到其他电脑。
uv 缓存放 .cache/uv；dev 脚本统一设置 UTF-8 与子进程缓存，不要求手工设置 shell 环境变量。
dev test 每次使用新的 .cache/pytest-runs/run-* 保存临时文件和缓存，避免终端与 AI 沙箱共用无权限的 pytest 目录；不需要先激活虚拟环境，也不需要数据库。

## 模型预算配置

在本地 .env 配置密钥与预算；.env.example 只保留空变量名，不填写真实密钥。
现有 Messages 探针通过 DEEPSEEK_MODEL 明确选择模型，当前支持 deepseek-flash 或 deepseek-v4-pro；这次最小实测选 deepseek-flash。换模型时按该模型人民币单价计费，未知模型拒绝调用，不会偷偷使用默认模型或 claude-* 映射。

| 配置 | 用途 | 单位 |
| --- | --- | --- |
| DAILY_BUDGET_CNY | DeepSeek 每日预算 | 人民币元 |
| DAILY_BUDGET_USD | Anthropic / OpenAI 合计每日预算 | 美元 |

两条线路独立记账，不自动换汇或借用余额；兼容 API 的 SDK 名称不改变计费来源。
0 表示禁用该线路；空白、非法或缺少预算时应拒绝真实调用。预算不能替代用户授权和本批调用次数上限。
M0.2 探针已实现环境变量读取、按所选模型的人民币预算检查与本批请求计数；uv --env-file .env 负责加载配置。美元线路只有配置与账本隔离测试，尚无 Anthropic/OpenAI 真实调用实现。
最小实测已成功，账本会拒绝重复运行；不要删除 .cache/m02-protocol 来重新获得次数。完整协议关卡尚未完成，详见 [实测矩阵](docs/protocol-deepseek.md)。
旧探针两请求授权已用完；本轮长程开发的 DeepSeek 整体额度见执行计划，同时遵守 .env 每日预算。SDK 美元估算不能代替人民币预算。新接入验收与费用边界见 [ADR-003](docs/adr/003-claude-agent-sdk-runtime.md)；本轮不改本地 .env。
历史批次限制见 [M0.2 准备记录](docs/operations/2026-10-03-m02-preparation.md)。

## PostgreSQL 配置

本批只提供 PostgreSQL 17 的 Compose 配置，没有迁移或仓储代码。
需要运行数据库时，把 .env.example 复制为本地 .env，自行设置 POSTGRES_PASSWORD。
POSTGRES_USER / POSTGRES_DB 默认 travel_agent，端口默认 5432，仅绑定 127.0.0.1。
启动 Docker Desktop 后运行 `uv run python scripts/dev.py db-up`；引擎不可用会记录到 docs/blocked/environment.md 并退出。
2026-10-03 已只读确认本机 Docker 正常；本地 PostgreSQL 17（5433）和 18（5432）均在接收连接。这两套 Windows 服务与项目的 Docker 数据库是独立的。
本机以后启动项目容器时，可在本地 .env 设置 POSTGRES_PORT=5434 避开已占用端口；本次没有创建容器、改数据库密码或写入数据。
PostgreSQL 是后台服务；需要图形管理界面时打开安装附带的 pgAdmin 4。当前的 check/test 不需要数据库，不能用数据库是否有窗口判断它们能否运行。

## 审阅与中断恢复

- [SDK 路线调整与恢复点](docs/operations/2026-10-03-agent-sdk-docs.md)：本轮文档修改、核查和验证。
- [修复与环境核对记录](docs/operations/2026-10-03-development-errors.md)：从这里判断现在的检查结果。
- [M0.1 审阅材料](docs/review/M0.1.md)：阅读顺序、失败证据和理解问题。
- [修复批次总结](docs/review/batch/2026-10-03-m0-repair.md)、[首次批次记录](docs/review/batch/2026-10-02-m0-core.md)。
- [文档汇总](docs/README.md)、[阻塞记录汇总](docs/blocked/README.md)、[待审阅决定](docs/decisions-pending.md)、[上游复用清单](docs/reuse.md)。

恢复前先检查 Git 状态；日志“开始”不代表成功。工程修复与旧探针增量已由 batch/2026-10-03-travel-autonomous 承接，按执行计划持续推进；旧批次和审阅记录保留作历史证据。
