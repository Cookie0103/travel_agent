# 分层债务清单

`pyproject.toml` 的 import-linter 有 11 条契约（`uv run --offline lint-imports`，由 `dev check` 执行）。契约只管**直接导入**（`allow_indirect_imports=true`）；下面这些边**已存在、暂时无法消除**，用 `ignore_imports` 逐条登记并加注释。新增违规会让契约变红；消除一条债务时同时删除对应的 `ignore_imports`。

来源与证据：[2026-10-18 完整性审查 F4](../review/audits/2026-10-18-completeness-audit.md) 与 [批次计划 P-F4](../plans/2026-10-18-completeness-hardening.md)。方法：用 grimp 按包对统计直接导入边，逐条核对后再写契约；用临时探针模块验证新契约能抓到新违规。

## 契约（11 条）

原有 3 条：domain 独立；SDK 不进入 api/agent/tools/domain/services/persistence/mock_supplier/data/eval；API 只经 services/agent 访问下层。
新增 8 条（均为 `forbidden`）：

1. persistence 不依赖 services / adapters / tools / agent / providers / mcp / api / mock_supplier / data / eval。
2. 只有入口导入 api。
3. 生产代码不导入 eval / data / mock_supplier。
4. adapters 不导入 services / tools / agent / providers / mcp / api / `persistence.models`（登记 1 条）。
5. tools 不导入 providers / mcp / persistence / api（无登记）。
6. services 不导入 tools（登记 2 条）。
7. services 不导入 providers 实现（登记 6 条）。
8. providers 与 agent 不导入 services（登记 4 条）。

services 导入 agent（`runs` 的 2 条）、mcp→services（3 条）属于主链设计方向，未纳入契约。

## 已登记的债务

| 边 | 原因 | 建议消除方式 |
| --- | --- | --- |
| `services.runs` → `tools.travel`、`tools.contracts` | RunService 直接构造 `TravelToolExecutor`；`tools.travel` 又导入 9 个 services 模块，形成 services↔tools 环 | 组合根（`server.create_app` 或 agent 工厂）构造 executor 后注入 RunService；`ToolExecutor` 协议放 domain 或 agent |
| `services.hotels` → `providers.hotel_fixture` | 用例直接读 fixture 提供者 | fixture 提供者移到 adapters 或 data，或由组合根注入 |
| `services.planning` → `providers.routes_fixture` | 同上 | 同上 |
| `services.models` → `providers.claude_agent.budget`、`settings` | 模型选项直接读 SDK 配置 | 把纯配置/预算常量下沉到 domain 或 `backend.profile` |
| `services.runs` → `providers.claude_agent.application` | 用例直接依赖 Claude 运行时 | 经 `agent.runtime` 协议由组合根注入 |
| `services.user_profile` → `providers.claude_agent.structured` | 函数内懒导入，绕过静态检查 | 注入“结构化生成”可调用对象 |
| `services.memory_extractor` → `providers.claude_agent.structured` | 默认DeepSeek抽取调用的函数内懒导入（构造参数已可注入） | 与画像一起由组合根注入“结构化生成”可调用对象 |
| `providers.claude_agent.database_tools` → `services.memory`、`services.travel` | 反向依赖：provider 调用业务用例 | 经 `tools` 层 executor 注入，不让 provider 直接持有 services |
| `providers.claude_agent.worker` → `services.common` | 只为 `ServiceError` | `ServiceError` / `transaction` 的共享类型下沉到 domain |
| `agent.demo` → `services.common` | 同上 | 同上 |
| `adapters.open_meteo` → `persistence.models` | 适配器内直接读写 `WeatherForecastRow`（2 处查询） | 下沉为 `persistence/weather.py` 仓储函数 |

## backend 模块地图（2026-10-19）

本节是后端模块与依赖方向的唯一说明；契约由 `pyproject.toml` 的 11 条 import-linter 保证（只管直接导入）。

| 包 | 职责 | 允许依赖 / 禁止 |
| --- | --- | --- |
| api | HTTP/SSE 路由、身份依赖 | 只经 services/agent 访问下层；仅入口 `server` 导入 api |
| services | 用例与事务组合 | 可用 domain/persistence/agent；不导入 tools、providers（各有登记债务） |
| domain | 纯业务对象与规则 | 不依赖其他业务层 |
| persistence | 表、仓储 SQL、Alembic 迁移 | 只依赖 domain；不上行 |
| tools | 工具契约/执行器、`skills/` 提示技能 | 不导入 providers、mcp、persistence、api |
| agent | 应用运行契约、上下文策略 | 不导入 services（登记 `demo` 1 条） |
| providers | Claude SDK 生命周期、worker、费用边界 | 不导入 services（登记 3 条）；SDK 只在此处、adapters、mcp |
| mcp | SDK 进程内桥接与只读 MCP server | 经 tools/services 取数据 |
| adapters | 外部服务客户端（乐天/Google/天气/供应商）、外部 API 配额与重试、脱敏 Trace 导出 | 不导入 services/tools/agent/providers/mcp/api/`persistence.models`（登记 1 条） |
| `server.py` / `cli.py` | 组合根与 uvicorn 入口 / 用户命令行入口 | 可装配各层 |
| `limits.py` / `profile.py` | 价格与预算设置 / 执行档位（限额分级） | 被 providers、services 读取 |
| `trace_log.py` | Railway 可见的单行 TRACE 元数据日志 | 各层可用，永不抛错 |

生产代码不得导入 eval / data / mock_supplier。

## 维护规则

- 新增债务必须先在这里写明原因和消除方式，再在 `pyproject.toml` 登记；不允许为通过检查直接加 `ignore_imports`。
- 消除债务后同时删除 `ignore_imports` 与本表对应行。
