# 文档目录：先看哪一份

当前采用 Claude Agent SDK 路线并进入长程自主开发。**只需看 [执行计划](execution/travel-agent.md)** 就能知道当前进度、决定、证据与下一步；阶段性材料无需逐项批准。
想知道各个代码目录放什么，先看 [项目首页](../README.md)。

## 工程地图与约定（按任务读取）

- [ARCHITECTURE](../ARCHITECTURE.md)：模块入口、依赖方向与状态来源。
- [DESIGN](DESIGN.md)：设计实施与简洁复用；业务设计继续链接plan。
- [FRONTEND](guides/FRONTEND.md)：界面状态、金额、SSE、失败恢复及浏览器验收。
- [RELIABILITY](RELIABILITY.md)、[SECURITY](SECURITY.md)：关键不变量与故障测试位置。
- [验收测试矩阵](execution/verification.md)：功能/正常与异常路径/跨模块证据/剩余缺口。
- [评测指南](guides/evaluation.md)：运行、对照、私有事实标注和校准口径。
- [QUALITY_SCORE](guides/QUALITY_SCORE.md)：按能力标证据与缺口，不用主观总分包装完成度。

`dev check`会检查入口长度与这些地图的仓库链接；不扫描历史/缓存，不发起网络请求。

## 目录一览

根目录只放 README 与三份核心约定（DESIGN、RELIABILITY、SECURITY），其余按用途归档：

| 目录 | 放什么 |
| --- | --- |
| [guides/](guides/) | 开发指南：[FRONTEND](guides/FRONTEND.md)、[QUALITY_SCORE](guides/QUALITY_SCORE.md)、[evaluation](guides/evaluation.md)、[reuse](guides/reuse.md) |
| [proposals/](proposals/) | [产品 V2 实现与验收范围](proposals/PRODUCT-V2-PLAN.md)；[前端方案](proposals/FRONTEND-REDESIGN.md)和[后端调查](proposals/BACKEND-CHANGE-INVESTIGATION.md)保留为历史背景 |
| [protocols/](protocols/) | 模型接入协议实测：[Claude Agent SDK](protocols/protocol-agent-sdk.md)、[DeepSeek](protocols/protocol-deepseek.md) |
| [adr/](adr/) | 技术决策记录，含[待审阅决定](adr/decisions-pending.md) |
| [execution/](execution/)、[tasks/](tasks/) | 执行计划与各里程碑任务规格 |
| [review/](review/)、[evidence/](evidence/) | 里程碑集中记录、脱敏证据 |
| [operations/](operations/)、[blocked/](blocked/README.md) | 执行记录与阻塞记录 |

| 你想了解什么 | 去哪里看 | 什么时候写 |
| --- | --- | --- |
| 当前做到哪里、如何恢复 | [执行计划](execution/travel-agent.md) | 持续更新，唯一实时进度入口 |
| 完整功能如何学习 | [review/](review/) | 按里程碑汇总，最终集中学习 |
| 一整批完成了哪些任务 | [review/batch/](review/batch/) | 每批结束时一份总结 |
| 什么问题让工作停下了 | [blocked/](blocked/README.md) | 遇到阻塞才记录，不是每次测试一份 |
| 实际执行过哪些步骤，如何恢复 | [operations/](operations/) | 边做边记录；JSONL 保存命令与输出 |
| 每个任务应当交付什么 | [tasks/M0.md](tasks/M0.md) | 实施规格；不是完成报告 |
| 为什么选择某个工具 | [adr/](adr/) | 技术决策发生时记录 |
| 哪些选择等你审阅 | [decisions-pending.md](adr/decisions-pending.md) | 有可回退的临时选择时记录 |
| 参考了哪些上游思路 | [reuse.md](guides/reuse.md) | 阅读上游后记录，不能当作本项目能力 |

## 本次可直接打开的记录

- [V2 验收记录](operations/product-v2.md)：真实 Google / 乐天 / Open-Meteo / DeepSeek、四城规划、日历导入和剩余范围；当前进度仍只维护在执行计划。

- [源码学习索引](review/learning.md)、[三段可重放演示](review/demos.md)、[项目表述审计稿](review/resume-draft.md)：集中学习入口，分别标注 SDK、真实业务服务和离线脚本的证据边界。

- [M4 交付规格](tasks/M4.md)、[M4 集中记录](review/M4.md)：容器启动、离线业务与重启证据；冻结评测和外部缺口分别记录。
- [当前版本三轮脱敏证据](evidence/m42-current-full-repeat-2026-10-04.json)：92/120规则通过、28失败保留；26规划候选全部partial，语义/真人校准尚未完成。
- [首次真实40test×3脱敏证据](evidence/m42-model-repeat-2026-10-03.json)：94/120规则通过及原失败/费用/时延，不当事实准确率或人工校准。
- [M2 可靠执行规格](tasks/M2.md)、[M2 集中记录](review/M2.md)。
- [M3 上下文与对照规格](tasks/M3.md)、[M3 集中记录](review/M3.md)：偏好、外部只读MCP与评测；未测能力不计完成。
- [M1 业务集中记录](review/M1.md)、[基础 API 真实 HTTP 证据](evidence/m11-api-smoke-2026-10-03.json)、[M1 规格](tasks/M1.md)。
- [M0 集中审查记录](review/M0.md)、[SDK 真实接入结果](protocols/protocol-agent-sdk.md)、[旅行工具真实查询证据](evidence/travel-query-2026-10-03.json)。
- [本地 Trace 与云导出决策](adr/005-observability-export.md)、[Langfuse 页面验收缺口](blocked/langfuse.md)。
- [初始真实评测](evidence/m06-baseline-2026-10-03.json)、[范围坏例回归](evidence/m07-scope-regression-2026-10-03.json)、[角色校准待办](blocked/persona-calibration.md)。

- 2026-10-03：[长程工作流](execution/workflow.md)、[工程标准](execution/standards.md)、[操作日志](operations/2026-10-03-autonomous.md)。已取消逐任务人工关卡，保留自动验证与独立审查。

- 2026-10-03：[SDK 路线说明](review/M0-sdk-route.md)、[ADR-003](adr/003-claude-agent-sdk-runtime.md)、[新版 M0 规格](tasks/M0.md)、[操作与恢复记录](operations/2026-10-03-agent-sdk-docs.md)。用户确认由 SDK 承担 runtime，自写业务与 tools；旧实测不算 SDK 验收。

以下按发生时保留，历史的“尚未开始”或旧设计不能覆盖上面的当前路线：

- 2026-10-03：[M0.2 阅读说明](review/M0.2.md)、[协议验证矩阵](protocols/protocol-deepseek.md)、[执行记录](operations/2026-10-03-m02-protocol.md)。离线 70 项通过，两次真实请求跑通最小往返；完整关卡尚未完成。
- 2026-10-03：[人民币 / 美元两条预算线路](operations/2026-10-03-budget-currencies.md)。用户要求的配置调整；当时尚未实现费用拦截；后续旧探针已有保护，新 SDK 路线仍须独立验证。
- 2026-10-03：[M0.2 配置准备与少量调用限制](operations/2026-10-03-m02-preparation.md)。仅记录准备要求，尚未开始真实模型调用。
- 2026-10-03：[报错修复和 Docker/PostgreSQL 核对](operations/2026-10-03-development-errors.md)、[修复批次总结](review/batch/2026-10-03-m0-repair.md)。工程检查与 37 个离线测试通过。
- 2026-10-03：[目录整理操作记录](operations/2026-10-03-directory-cleanup.md)。
- 2026-10-02：[M0.1 批次总结](review/batch/2026-10-02-m0-core.md)、[未完成原因](blocked/2026-10-02-m0-core.md)、[详细操作记录](operations/2026-10-02-m0-core.md)。

设计目标与任务顺序仍以 [plan/](../plan/README.md) 为准。这里解释实际做过什么，不会把目录占位写成已经实现的功能。

- [M4真实零工具三轮对照](evidence/m42-no-tools-repeat-2026-10-03.json)：同版本40×3，原规则失败保留。

- [M4完整配对统计](evidence/m42-paired-comparison-2026-10-03.json)：绑定两组原文件，错误/未知不刷掉。

- [本轮有限同版本验收测量](evidence/m42-controlled-sweep-2026-10-04.json)：fa9930b原40test×3，完整组97/120规则通过；余下实验已停止，partial与语义/真人unknown保留。本轮交付范围与最终结果见 [PROJECT_STATUS](../PROJECT_STATUS.md)，不重复每日运行。

## 2026-10-08 修复批次入口

- [完整问题与修复设计](../plan/实操计划/07-2026-10-08-product-v2-问题修复.md)：19项核查问题、澄清项、酒店touch bar与阶段验收。
- [过程记录](operations/product-v2.md#2026-10-08-调查与修复准备)、[面试案例索引](review/learning.md#2026-10-08-产品修复候选案例)：保留调查证据、方案取舍与限制。实时状态仅见[执行计划](execution/travel-agent.md)。
