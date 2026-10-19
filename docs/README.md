# 文档入口：按用途找

370 多个文件按“用途”分目录。**先看下面“现在在哪”，再用“我想知道…”表跳转**；历史材料在 [archive/](archive/README.md)，不是现状。代码目录说明见[项目首页](../README.md)，模块依赖见 [ARCHITECTURE](../ARCHITECTURE.md)。

## 现在在哪、怎么恢复

1. **最新批次**：[2026-10-19 加固收尾与真模型验证](plans/2026-10-19-session-log.md)（分支 `batch/2026-10-19-architecture-hardening`）。上一批 [10-18 完整性加固](plans/2026-10-18-completeness-hardening.md)、[10-15 提速与通用表单](plans/2026-10-15-speed-repair-and-form.md)、基座批次 [10-13 交互、记忆与评测](plans/2026-10-13-interaction-memory-eval.md)（[AGENTS.md](../AGENTS.md) 的稳定入口）。全部批次见[批次索引](plans/README.md#批次索引)。
2. 批次计划是**唯一实时进度**：任务表（状态+证据）、每日进展、问题解决记录（P-条目）。别处只链接，不复制状态。
3. 恢复步骤：`git status` → 读最新批次的“每日进展”和未完成任务 → [工作流](execution/workflow.md)、[工程标准](execution/standards.md) → 按任务读 [design/](design/README.md) 与相关 [ADR](adr/README.md)。
4. 记录规则（什么时候写什么、P-条目与案例模板）：[plans/README](plans/README.md)，所有执行者共用，不另立。

## 我想知道…→去哪看

| 我想知道… | 去哪看 | 什么时候写 |
| --- | --- | --- |
| 开发计划、某批次做了什么、状态 | [plans/README 批次索引](plans/README.md#批次索引) | 批次开始建文件，任务状态只在批次内改 |
| 测试怎么跑、分哪几层、CI 做什么、环境相关失败 | [testing/README](testing/README.md) | 新增测试层/环境问题时 |
| 测试计划与验收矩阵（需求→证据→缺口） | [execution/verification.md](execution/verification.md)、[评测指南](guides/evaluation.md)、[QUALITY_SCORE](guides/QUALITY_SCORE.md) | 能力有新证据时 |
| 开发中发现的问题、怎么解决的、试过哪些方法 | [问题与修复索引](plans/problems.md) → 批次计划 §8 | 复现/放弃做法/commit 后即时写 |
| 审计与对抗性审查发现 | [review/audits/](review/audits/) | 每次审查一份 |
| 为什么选这个技术/方案（取舍） | [adr/README](adr/README.md)；待你审阅的临时选择 [decisions-pending](adr/decisions-pending.md) | 引入依赖/契约/实质取舍时 |
| 产品与架构设计、任务依赖 | [design/README](design/README.md)、[DESIGN](DESIGN.md)；任务规格 [M0](tasks/M0.md)、[M1](tasks/M1.md)、[M2](tasks/M2.md)、[M3](tasks/M3.md)、[M4](tasks/M4.md) | 设计变更先改 design |
| 可靠性与安全不变量 | [RELIABILITY](RELIABILITY.md)、[SECURITY](SECURITY.md) | 不变量变化时 |
| 前端约定与浏览器验收 | [guides/FRONTEND](guides/FRONTEND.md) | 前端变更时 |
| 怎么运行、部署、评测、导出线上对话 | [operations/README](operations/README.md) | 边做边记命令与输出 |
| 证据（JSON、截图）在哪 | [evidence/README](evidence/README.md) | 每次验收留脱敏证据 |
| 集中学习、面试案例、演示 | [review/README](review/README.md)、[cases/](review/cases/) | 批次内 P-条目全 done 后成案例 |
| 阻塞（缺凭据/授权/环境） | [blocked/README](blocked/README.md) | 真实阻塞才记 |
| 上游参考与协议实测 | [guides/reuse](guides/reuse.md)、[protocols/](protocols/protocol-agent-sdk.md)（[DeepSeek](protocols/protocol-deepseek.md)） | 阅读上游/做协议实测后 |
| 提案与调研 | [PRODUCT-V2-PLAN](proposals/PRODUCT-V2-PLAN.md)、[论文调研](proposals/2026-10-15-planning-repair-research.md) | 动手前的方案 |
| 已被取代的历史（旧执行计划、M0 日志…） | [archive/README](archive/README.md) | 只迁入，不改写 |

## 目录一览

```text
docs/
  plans/       批次计划、记录规则、批次索引、问题索引   <- 日常最常用
  testing/     测试总览
  adr/         技术决策      design/  长期设计      tasks/  里程碑规格
  execution/   工作流、工程标准、验收矩阵            guides/ 开发指南
  operations/  操作手册与原始过程      evidence/  脱敏证据
  review/      集中学习、案例、审计     blocked/  阻塞    protocols/ proposals/
  archive/     历史归档（只读）
  DESIGN.md  RELIABILITY.md  SECURITY.md
```

## 持续记录（给后续执行者）

- 一类信息只放一个地方：状态→批次计划；命令与原始输出→operations；取舍→ADR；证据→evidence；面试故事→review/cases。
- 新增文件后在对应子目录 README（或本页表格）补一行，保证 [`dev check`](../scripts/check_docs.py) 的入口链接可达；本页与 AGENTS.md、ARCHITECTURE.md 保持短小（AGENTS/ARCHITECTURE ≤100 行由检查强制）。
- 新批次：新建 `plans/<日期>-<主题>.md`，在[批次索引](plans/README.md#批次索引)插入一行，并更新 AGENTS.md 与本页“现在在哪”的链接。
- 历史记录只追加更正说明，不改写；过时的整份材料用 `git mv` 迁入 archive 并修链接。
