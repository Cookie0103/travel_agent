# 代码架构地图

业务设计唯一来源：[design/02](docs/design/02-architecture.md)、[领域与工具](docs/design/03-data-tools.md)。
当前实施/缺口看[当前批次](docs/plans/2026-10-19-session-log.md)。此处只帮助定位代码，不另定义业务。

不熟悉术语时先看[架构白话讲解与逐表字段](docs/guides/system-walkthrough.md)：区分执行、进度和用户确认三条链。

| 目录 | 职责与入口 |
| --- | --- |
| backend/api | HTTP、身份依赖和SSE；app.create_app调用应用服务 |
| backend/services | 身份、旅行条件、目录、报价、TaskRun等用例及事务组合 |
| backend/domain | TravelRequest、Evidence、报价、营业时间等纯规则 |
| backend/persistence | SQLAlchemy表、仓储SQL、Alembic迁移；PostgreSQL事实来源 |
| backend/agent | 应用运行契约、上下文策略、应用事件；默认离线替身明确标注 |
| backend/providers | Claude SDK生命周期、隔离worker、费用边界及供应商适配 |
| backend/tools / mcp | 单份schema/业务执行器；SDK进程内桥接与server对外四个只读查询 |
| backend/adapters | 外部服务客户端（Rakuten/Google/天气/供应商）、外部API配额与重试、脱敏Trace导出 |
| backend/tools/skills | 提示技能（酒店比较、行程修订等），随工具层加载 |
| backend/server.py / cli.py | 组合根与uvicorn入口 / 用户命令行入口 |
| backend/limits.py / profile.py | 价格与预算设置 / 执行档位（限额分级） |
| backend/trace_log.py | Railway可见的单行TRACE元数据日志 |
| data / eval / scripts | 数据快照/fixture、评测、开发命令 |
| apps/web / mock_supplier | 攻略列表/详情、规划工作台、只读正式行程；模拟供应商与故障注入 |

主链：消息API → RunService → Agent → 隔离SDK worker → MCP → TravelToolExecutor → 业务服务 → 仓储。
事件链：worker私有进度 → 父进程验证 → RunService事务保存 → SSE读取；重连不触发执行。
确认链：页面确认API → 业务事务。模型没有正式保存/下单工具，后续实现仍保持此边界。

本批入口：`services/choices.py`负责服务器选择卡；`services/memory.py`负责确认事实、遗忘边界及SDK续接裁决；`services/user_profile.py`负责有引用的派生画像。画像显式生成仍走`providers/claude_agent/structured.py`的同一SDK无工具路径。`eval/simulator.py`复用应用服务执行合成用户动作，`eval/report.py`分别汇总交付、约束与成本。

三个状态源：SDK私有会话用于模型上下文；应用事件用于展示；数据库领域对象用于业务判断。
SDK文件与数据库事务不是同一原子操作；恢复验收见[可靠性](docs/RELIABILITY.md)。

分层由`dev check`中的11条import-linter契约保护（只管直接导入）；已有违规逐条登记在[分层债务](docs/execution/layering-debt.md)，各包依赖方向见其中“backend 模块地图”，新增违规会让检查变红；类型/规则依据见[工程标准](docs/execution/standards.md)。
数据库用例的事务/归属测试在tests/integration，默认真实本地PostgreSQL；模型默认离线。
跨层或新依赖变更先查已有入口和[ADR](docs/adr/)，避免复制第二套运行机制。
