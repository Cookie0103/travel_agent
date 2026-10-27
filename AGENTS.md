# AGENTS.md — 项目地图与执行入口

当前模式：**长程自主开发**（用户 2026-10-03 明确授权，替代逐任务人工关卡）。
目标：先完成可运行、可验证的 Travel Agent，再由用户集中审阅、学习和练习面试。

## 项目长期方法约定（用户 2026-10-21）

- **本仓库所有对话均适用**：方案讨论、实现、排障、源码导学、评测解释、简历和面试，以 Anthropic 的 [Commerce Agents 架构](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)与[工具设计](https://www.anthropic.com/research/writing-tools-for-agents)为首要方法参考。
- 开始或恢复时，先读[长期方法与代码映射](docs/guides/reuse.md#项目长期方法约定2026-10-21)；相关细节再查原文，不必每轮重读全文。未来会话必须沿用，不把它当作一次性阅读材料。
- 回答先联系用户任务、工具与上下文、服务端约束、评测证据；区分“原文建议 / 本项目实现 / 已验证效果 / 尚存差距”。不把原文示例或收益写成项目事实。
- 这是协作者的项目级持久约定，不是应用里的用户偏好记忆；不自动改业务设计、切换 runtime、扩大权限或发起付费调用。用户后续明确决定与现有安全边界继续有效。

## 开始或恢复时

1. **当前批次计划** [docs/plans/2026-10-19-session-log.md](docs/plans/2026-10-19-session-log.md)：范围、待决事项、任务状态、每日进展、问题解决记录；按 [记录规则](docs/plans/README.md) 持续更新，全部批次见[批次索引](docs/plans/README.md#批次索引)。上一批次 [2026-10-18 完整性加固](docs/plans/2026-10-18-completeness-hardening.md)，基座批次 [交互、记忆与评测](docs/plans/2026-10-13-interaction-memory-eval.md)，上一批次见 [住宿段选择](docs/plans/2026-10-11-segment-hotel-selection.md)，此前见 [Product V2](docs/plans/2026-10-08-product-v2.md)，2026-10-08 前的历史见 [旧执行计划](docs/archive/execution/travel-agent.md)。
2. [设计地图](docs/design/README.md) → [任务定义与依赖](docs/design/04-roadmap.md)。
3. [当前验收规格](docs/tasks/M4.md)及本次涉及的 02/03/05、ADR；按需读，不全仓灌入上下文。
4. [工作流](docs/execution/workflow.md)、[工程标准](docs/execution/standards.md)；先核对 git status，不覆盖已有工作。
5. 按任务查[架构地图](ARCHITECTURE.md)及[设计/前端/可靠性/安全/质量导航](docs/README.md)，不每轮全部重读。

## 持续执行

- 按计划实现 → 测试 → 自审 → 独立审查 → 修复 → 本地提交 → push当前开发分支 → 自动继续。
- 每个Mx.x完成并通过质量关卡后提交并push；不中断等用户确认。网络/认证失败保留本地提交并记录未推送项，继续可独立工作，恢复后补推。
- 不因为 M0.xx、里程碑完成、学习问题未回答或尚未合并 main 而等待用户。
- 原 M0.2/M0.3/M1.3/M1.6/M1.7/M2.2/M2.4 是自动质量关卡；高风险未解决问题不进入依赖任务。
- 新里程碑规格由 agent 依据既定设计补写并审查后执行，不再另等确认。
- 日常模块拆分、修复、测试、必要依赖和可回退默认值自主决定并留记录；新增依赖先写 ADR。
- 允许独立审查子 agent。审查需给定明确变更范围、要求和证据；默认只读，由主 agent 修复并复核。

## 保持的边界

- 设计唯一来源是 docs/design/；执行计划维护实施进度，不另造业务设计。设计冲突先定位依据；需改变产品目标、SDK 路线或安全不变量时才问用户。
- runtime 使用 Claude Agent SDK；旅行业务、tools、校验和事务独立实现。不引入第二套 runtime，不做 C 档代码。
- 遵守工程标准：类型、格式、分层、失败路径测试、真实 PostgreSQL 事务测试、Windows/UTF-8。
- **SDK 优先、简洁复用**：先查现有函数/接口和 SDK 公共能力，再写代码；不重复实现运行时，不为假想扩展加抽象。具体规则见 [工程标准 §3.4](docs/execution/standards.md#34-sdk-优先与简洁复用)，上游阅读依据见 [复用清单](docs/guides/reuse.md)。独立审查必须检查重复与过度设计。
- 默认离线；真实调用按执行计划中的供应商、累计次数/金额及 .env 每日预算同时限制，不因有 key 自动放开。
- 用户2026-10-03已授权push当前开发分支到既有origin，替代原“不push”规则；不force push、不合并main、不改写已有历史、不删除分支，不操作真实订单/付款。
- vendor/ 和用户给的上游只读；未经 ADR 不复制代码，内部仓库原文与密钥不得进入提交或日志。
- 保持 workspace-write + auto-review，不自行修改权限配置或扩大系统访问。

## 记录与停机

- 当前批次计划是唯一实时进度入口；按 [docs/plans/README](docs/plans/README.md) 记录任务状态、每日进展和问题解决记录（P-条目：假设与排除、根因证据、方案取舍、先红后绿测试、commit）。
- docs/operations 保存命令与原始过程；docs/review/cases 保存面试案例；docs/blocked 只记真实阻塞；统一从 docs/README.md 导航。
- 不为每个小任务新增一份要求用户阅读的报告；合并进里程碑记录，最终集中交付。
- 普通失败自主定位修复；同根因持续无进展时记录并转做独立工作，不通过改断言/跳过检查来过关。
- 仅缺凭据/授权、不可逆外部操作、实质产品架构冲突需要用户介入；隔离受影响工作并继续其他任务。
- 中断前落盘恢复点。断电、休眠或网络/运行额度不可用时不能承诺继续计算；恢复后从计划和 Git 续接。
