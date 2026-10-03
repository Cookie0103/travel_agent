# ADR-000 技术选型

状态：部分 superseded（2026-10-03）。运行时、模型接入与 MCP 版本策略由 [ADR-003](003-claude-agent-sdk-runtime.md) 取代，其余选择保留。

## 背景
个人作品项目，按企业级标准实现，代码由 AI 生成、用户需要读懂。选型原则：主流、无聊、少组件；同一件事只用一种工具。

## 决策

| 领域 | 选择 | 理由 |
| --- | --- | --- |
| Python | 3.12 | 主流稳定版，类型特性足够 |
| 包管理 | uv（`pyproject.toml` + `uv.lock`） | 快、锁版本、一个工具管虚拟环境和依赖 |
| Web | FastAPI + Pydantic v2 | 用户熟悉；Pydantic 同时做工具 schema |
| 数据库 | PostgreSQL 17（docker） | 业务数据、事件、队列都放这里 |
| 数据访问 | SQLAlchemy 2.x（async）+ psycopg 3 | 主流；一个驱动同时支持同步（迁移）和异步 |
| 迁移 | Alembic | SQLAlchemy 官方配套 |
| 测试 | pytest + pytest-asyncio | 标准 |
| 静态检查 | ruff（lint + format）、mypy --strict、import-linter | 规则见 docs/execution/standards.md §3.1 |
| Agent SDK | `claude-agent-sdk`（计划在 M0.2 引入）；`anthropic` 只保留原探针用途 | 02 §4、ADR-003 |
| MCP | 与锁定 Agent SDK 兼容的版本，M0.2 核实 | 内部工具桥接；M3.3 对外只读服务 |
| 可观测 | `opentelemetry-sdk` + Langfuse | 02 §8.1 |
| 前端 | Next.js（App Router）+ TypeScript + pnpm | 演示用；不引入额外状态管理库 |
| 运行环境 | docker compose | 一键启动 |
| 任务入口 | `scripts/dev.py`（纯 Python） | 项目在 Windows 上执行，Makefile 和 bash 不可用；命令见 docs/execution/standards.md §4 |

**版本号**：依赖在对应任务确实需要时安装并由工具写入锁文件；SDK、CLI 和 MCP 以组合兼容验证为准。已有锁文件本轮不改，升级单独 commit。

## 待 M0 实测确认
- Langfuse 自托管的组件要求（v3 可能需要 ClickHouse、Redis、对象存储）。如果本地太重，开发期改用 Langfuse Cloud 免费层，在本 ADR 追加记录。
- Agent SDK 与 MCP 版本组合、Windows 进程要求及 DeepSeek 兼容性，按新版 M0.2 验证。

## 明确不用
LangChain / LangGraph（本次选用 Claude Agent SDK，见 ADR-003）、Redis、消息队列、向量库、Celery。理由见 04 C 档 ADR（M4.3 补写）。

## 何时重新决策
某一项在实现中被证明不可用，或需要的能力只能靠新依赖获得时：写新 ADR，标记本 ADR 对应行为 superseded。
