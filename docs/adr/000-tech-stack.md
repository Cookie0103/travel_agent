# ADR-000 技术选型

状态：accepted（2026-10-02）

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
| 静态检查 | ruff（lint + format）、mypy --strict、import-linter | 规则见 AGENTS.md §3.1 |
| 模型 SDK | `anthropic`（DeepSeek / Claude）；`openai`（M3 对比时才加） | 02 §4 |
| MCP | `mcp` Python SDK 2.x | 06 §4 |
| 可观测 | `opentelemetry-sdk` + Langfuse | 02 §8.1 |
| 前端 | Next.js（App Router）+ TypeScript + pnpm | 演示用；不引入额外状态管理库 |
| 运行环境 | docker compose | 一键启动 |
| 任务入口 | `scripts/dev.py`（纯 Python） | 项目在 Windows 上执行，Makefile 和 bash 不可用；命令见 AGENTS.md §4 |

**版本号**：M0.1 时取各依赖当时的最新稳定版写入 `uv.lock` / `pnpm-lock.yaml`，之后升级需单独 commit。

## 待 M0 实测确认
- Langfuse 自托管的组件要求（v3 可能需要 ClickHouse、Redis、对象存储）。如果本地太重，开发期改用 Langfuse Cloud 免费层，在本 ADR 追加记录。
- mcp 2.x 与上游 `mcp==1.29.0` 的 API 差异。

## 明确不用
LangChain / LangGraph（手写循环，见 02）、Redis、消息队列、向量库、Celery。理由见 04 C 档 ADR（M4.3 补写）。

## 何时重新决策
某一项在实现中被证明不可用，或需要的能力只能靠新依赖获得时：写新 ADR，标记本 ADR 对应行为 superseded。
