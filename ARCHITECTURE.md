# 代码架构地图

业务设计唯一来源：[plan/02](plan/实操计划/02-Agent架构与实现设计.md)、[领域与工具](plan/实操计划/03-数据工具与外部API.md)。
当前实施/缺口看[执行计划](docs/execution/travel-agent.md)。此处只帮助定位代码，不另定义业务。

| 目录 | 职责与入口 |
| --- | --- |
| backend/api | HTTP、身份依赖和SSE；app.create_app调用应用服务 |
| backend/services | 身份、旅行条件、目录、报价、TaskRun等用例及事务组合 |
| backend/domain | TravelRequest、Evidence、报价、营业时间等纯规则 |
| backend/persistence | SQLAlchemy表、仓储SQL、Alembic迁移；PostgreSQL事实来源 |
| backend/agent | 应用运行契约、上下文策略、应用事件；默认离线替身明确标注 |
| backend/providers | Claude SDK生命周期、隔离worker、费用边界及供应商适配 |
| backend/tools / mcp | 单份schema/业务执行器；SDK进程内桥接与server对外四个只读查询 |
| backend/adapters | 脱敏Trace与外部观测导出 |
| data / eval / scripts | 数据快照/fixture、评测、开发命令 |
| apps/web / mock_supplier | 前端与模拟供应商位置；实施状态看执行计划 |

主链：消息API → RunService → Agent → 隔离SDK worker → MCP → TravelToolExecutor → 业务服务 → 仓储。
事件链：worker私有进度 → 父进程验证 → RunService事务保存 → SSE读取；重连不触发执行。
确认链：页面确认API → 业务事务。模型没有正式保存/下单工具，后续实现仍保持此边界。

三个状态源：SDK私有会话用于模型上下文；应用事件用于展示；数据库领域对象用于业务判断。
SDK文件与数据库事务不是同一原子操作；恢复验收见[可靠性](docs/RELIABILITY.md)。

分层通过`dev check`中的import-linter保护；类型/规则依据见[工程标准](docs/execution/standards.md)。
数据库用例的事务/归属测试在tests/integration，默认真实本地PostgreSQL；模型默认离线。
跨层或新依赖变更先查已有入口和[ADR](docs/adr/)，避免复制第二套运行机制。
