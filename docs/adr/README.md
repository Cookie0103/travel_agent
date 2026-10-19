# 技术决策记录（ADR）

新增接口/字段/依赖/契约等实质取舍时新增一份，编号接续（下一个：031）。格式：背景、选项、决定、后果；被取代时在旧文件顶部注明并保留原文（例：029 被 030 取代）。

- [decisions-pending.md](decisions-pending.md)：可回退的临时选择，等用户审阅。
- 取舍与失败尝试的过程记录在批次计划 §8，参见[问题与修复索引](../plans/problems.md)；评测方案的“测了哪些、选了什么”见 [测试总览](../testing/README.md)。

| 编号 | 标题 |
| --- | --- |
| [000](000-tech-stack.md) | 技术选型 |
| [001](001-development-bootstrap.md) | 开发入口与提交检查 |
| [002](002-protocol-probe.md) | M0.2 小范围协议实测 |
| [003](003-claude-agent-sdk-runtime.md) | 用 Claude Agent SDK 承担运行时 |
| [004](004-sdk-request-budget-boundary.md) | SDK 请求与费用边界 |
| [005](005-observability-export.md) | 本地 OTel 记录与可选 Langfuse 导出 |
| [006](006-local-database-config.md) | 本地数据库配置和演示身份 |
| [007](007-frontend-workbench.md) | 旅行工作台依赖与契约 |
| [008](008-supplier-http.md) | 模拟供应商使用现有httpx |
| [009](009-container-demo.md) | 独立离线容器演示 |
| [011](011-persona-judge-through-sdk.md) | 固定温度语气评审复用 SDK 与费用守卫 |
| [012](012-evaluation-variants.md) | 评测对照复用同一SDK与业务边界 |
| [013](013-curated-catalog-supplement.md) | 公开来源补充数据独立版本与隔离评测 |
| [014](014-session-history.md) | 归属隔离、有界分页的旅行与对话历史 |
| [015](015-lodging-budget-and-condition-source.md) | 住宿预算分项、现算预算关系与条件来源 |
| [016](016-rakuten-hotel-discovery.md) | 乐天酒店按施设发现、促销价下限与“查看更多”入口 |
| [018](018-frontend-tailwind-shadcn.md) | 前端 Tailwind CSS 与 shadcn/ui 渐进迁移 |
| [019](019-segment-hotel-selection.md) | 住宿段选择使用规范报价引用 |
| [020](020-external-error-retry.md) | 外部读取只在拥有请求的边界重试一次 |
| [021](021-server-owned-choice-cards.md) | 选择卡由服务端生成，并在消息事务中确认 |
| [022](022-hotel-budget-recovery.md) | 酒店检索诊断与经确认的预算放宽 |
| [023](023-observability-linkage.md) | 同轮PG锚点、HTTP观测与Langfuse分数 |
| [024](024-confirmed-memory-facts.md) | 经逐条确认的偏好事实与选择性遗忘 |
| [025](025-derived-user-profile.md) | 有引用的衍生用户画像 |
| [026](026-evaluation-reference-metadata.md) | 评测参考摘要与通过门槛分离 |
| [027](027-teamorouter-haiku.md) | TeamoRouter Haiku 5.5 接入 |
| [028](028-live-process-lock.md) | 运行互斥随进程退出释放 |
| [029](029-combined-travel-details.md) | 交通、节奏与时间一次确认 |
| [030](030-generic-choice-form.md) | 通用服务端校验表单取代写死的组合卡 |
