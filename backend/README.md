# 后端代码

这里是整个旅行规划后端：FastAPI 接口、业务规则、工具契约、Claude Agent SDK 适配、外部数据适配和 PostgreSQL 持久化。默认离线（fixture 运行时，不联网、不花钱）；真实模型需显式 `--live` 并通过费用守卫。`--relaxed` 只放宽次数与超时（见 `providers/claude_agent/profile.py`），费用上限不变。

| 子目录 | 负责什么 |
| --- | --- |
| domain | 旅行条件、行程、方案、预订、证据、执行事件等业务对象与规则；不依赖其他业务层 |
| services | 一次业务用例：核对归属、调用规则、读写数据库、管理 run 生命周期 |
| tools | 工具契约、旅行搜索/校验工具、工具执行事件；SDK 与离线演示共用同一入口 |
| agent | 应用执行入口：会话归属、版本/模型切换、唯一终态；不自写模型循环 |
| providers/claude_agent | Claude Agent SDK 的隔离 worker、费用守卫（limits/ledger/budget/guard）、HTTP 转发、事件转换 |
| adapters | 对接外部服务：供应商、地图、天气、Trace 导出；导入时不联网 |
| persistence | 表映射、迁移、查询和事务 |
| api | HTTP 与 SSE 薄入口，只调 services/agent，不直接读写数据库 |
| mcp | 把共享工具接成 SDK 进程内 MCP（bridge）；server 为只读 MCP 服务 |

## 核心阅读顺序（约 12 个文件）

1. `domain/execution.py`：执行请求/事件/终态的数据契约
2. `tools/contracts.py`：工具定义与参数、权限契约
3. `tools/travel.py`：旅行工具实现
4. `domain/validator.py`、`domain/itinerary.py`、`domain/plans.py`：行程规则与校验、方案对象
5. `services/travel.py`、`services/plans.py`：工具背后的业务用例
6. `tools/execution.py`、`mcp/bridge.py`：工具调用转应用事件；接到 SDK 的 MCP 桥
7. `agent/runtime.py`：检查会话归属，调用 runtime，发布唯一终态
8. `providers/claude_agent/runtime.py`：隔离进程内调 SDK，转换事件
9. `providers/claude_agent/guard.py`、`budget.py`：模型 HTTP 的预占/结算与限额
10. `services/runs.py`：run 创建、执行、事件落库、取消与恢复
11. `api/app.py`、`api/events.py`：路由与 SSE

## 一次请求的流向

```text
POST /sessions/{id}/messages        (api/app.py)
  → RunService.submit               (services/runs.py)   创建 run，202 返回
  → Agent.run                       (agent/runtime.py)
  → 离线 fixture 或 live: ClaudeRuntime (providers/claude_agent)
      → 隔离 worker → SDK/CLI → guard/budget → 模型
      → MCP bridge → tools → services → persistence
  → RuntimeEvent 提交到 PostgreSQL
GET /runs/{id}/events (SSE)         (api/events.py)      只读已提交事件，断线不影响 run
```

## 运行与检查

命令均由 `scripts/dev.py` 提供：

- `uv run python scripts/dev.py setup`：安装依赖与 pre-commit
- `uv run python scripts/dev.py check`：ruff check、ruff format --check、mypy --strict（win32/linux/darwin）、lint-imports、文档地图检查
- `uv run python scripts/dev.py test`：pytest（`tests/integration` 需要真实 PostgreSQL）
- `uv run python scripts/dev.py api`：启动 API（`backend/server.py`）

不变量：domain 不依赖其他业务层；SDK/httpx/mcp 只在 providers、adapters、mcp 内；api 只经 services/agent 访问其他层（见 `pyproject.toml` 的 import-linter 契约与 `tests/test_architecture.py`）。
