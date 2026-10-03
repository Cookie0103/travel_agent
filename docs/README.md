# 文档目录：先看哪一份

当前已改为 Claude Agent SDK 路线，先看 [本次调整说明](review/M0-sdk-route.md)；实际 SDK 尚未接入。
想知道各个代码目录放什么，先看 [项目首页](../README.md)。

| 你想了解什么 | 去哪里看 | 什么时候写 |
| --- | --- | --- |
| 一个任务具体做了什么 | [review/M0.1.md](review/M0.1.md) | 每个任务结束或停止时更新 |
| 一整批完成了哪些任务 | [review/batch/](review/batch/) | 每批结束时一份总结 |
| 什么问题让工作停下了 | [blocked/](blocked/README.md) | 遇到阻塞才记录，不是每次测试一份 |
| 实际执行过哪些步骤，如何恢复 | [operations/](operations/) | 边做边记录；JSONL 保存命令与输出 |
| 每个任务应当交付什么 | [tasks/M0.md](tasks/M0.md) | 实施规格；不是完成报告 |
| 为什么选择某个工具 | [adr/](adr/) | 技术决策发生时记录 |
| 哪些选择等你审阅 | [decisions-pending.md](decisions-pending.md) | 有可回退的临时选择时记录 |
| 参考了哪些上游思路 | [reuse.md](reuse.md) | 阅读上游后记录，不能当作本项目能力 |

## 本次可直接打开的记录

- 2026-10-03：[SDK 路线说明](review/M0-sdk-route.md)、[ADR-003](adr/003-claude-agent-sdk-runtime.md)、[新版 M0 规格](tasks/M0.md)、[操作与恢复记录](operations/2026-10-03-agent-sdk-docs.md)。用户确认由 SDK 承担 runtime，自写业务与 tools；旧实测不算 SDK 验收。

以下按发生时保留，历史的“尚未开始”或旧设计不能覆盖上面的当前路线：

- 2026-10-03：[M0.2 阅读说明](review/M0.2.md)、[协议验证矩阵](protocol-deepseek.md)、[执行记录](operations/2026-10-03-m02-protocol.md)。离线 70 项通过，两次真实请求跑通最小往返；完整关卡尚未完成。
- 2026-10-03：[人民币 / 美元两条预算线路](operations/2026-10-03-budget-currencies.md)。用户要求的配置调整；当时尚未实现费用拦截；后续旧探针已有保护，新 SDK 路线仍须独立验证。
- 2026-10-03：[M0.2 配置准备与少量调用限制](operations/2026-10-03-m02-preparation.md)。仅记录准备要求，尚未开始真实模型调用。
- 2026-10-03：[报错修复和 Docker/PostgreSQL 核对](operations/2026-10-03-development-errors.md)、[修复批次总结](review/batch/2026-10-03-m0-repair.md)。工程检查与 37 个离线测试通过。
- 2026-10-03：[目录整理操作记录](operations/2026-10-03-directory-cleanup.md)。
- 2026-10-02：[M0.1 批次总结](review/batch/2026-10-02-m0-core.md)、[未完成原因](blocked/2026-10-02-m0-core.md)、[详细操作记录](operations/2026-10-02-m0-core.md)。

设计目标与任务顺序仍以 [plan/](../plan/README.md) 为准。这里解释实际做过什么，不会把目录占位写成已经实现的功能。
