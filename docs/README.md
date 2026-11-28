# 文档入口

项目分阶段推进，文档也按阶段放。**现在是第二阶段**（2026-11-27 起）：规则关卡、商业期望分、Skill 分层、自进化、新评测集。

```text
docs/
  phase2/      现在在做的：设计、开发计划、过程记录都在这一个目录
  handbook/    两个阶段都要遵守的规则和系统说明（工作流、标准、设计、ADR）
  blocked/     真实阻塞记录（dev.py 遇到 Docker 等环境问题会自动写这里）
  assets/      README 用的截图
archive/
  phase1/      第一阶段的全部过程材料和调研（只读，按需查）
```

## 现在在哪

1. [第二阶段入口](phase2/README.md)：目标、读的顺序、目录约定。
2. [设计](phase2/design.md)：五条工作线各自怎么设计、公式、参数怎么定、实验怎么做。
3. [开发计划](phase2/plans/2026-11-27-judge-evolution.md)：**唯一实时进度**。任务表、待决定事项、每日进展、问题解决记录。

恢复工作的步骤：`git status` → 读开发计划的“每日进展”和未完成任务 → [工作流](handbook/execution/workflow.md)、[工程标准](handbook/execution/standards.md) → 按任务读设计与相关 [ADR](handbook/adr/README.md)。

## 我想知道……去哪看

| 我想知道…… | 去哪看 |
| --- | --- |
| 现在要做什么、做到哪了 | [开发计划](phase2/plans/2026-11-27-judge-evolution.md) |
| 第二阶段每条线为什么这么设计 | [设计](phase2/design.md)；论文与数据依据在[调研笔记](../archive/phase1/research/judge-scoring-notes/) |
| 写代码要守哪些规矩 | [工作流](handbook/execution/workflow.md)、[工程标准](handbook/execution/standards.md)、[长期方法约定](handbook/guides/reuse.md#项目长期方法约定2026-10-21) |
| 开发过程怎么记录 | [记录规则](handbook/recording.md) |
| 系统是怎么搭的 | [ARCHITECTURE](../ARCHITECTURE.md)、[系统白话讲解](handbook/guides/system-walkthrough.md)、[产品设计 01–07](handbook/design/README.md) |
| 为什么选这个技术 | [ADR 索引](handbook/adr/README.md) |
| 测试怎么跑、分几层 | [测试总览](handbook/testing/README.md)、[tests/README](../tests/README.md) |
| 评测怎么跑 | [eval/README](../eval/README.md)、[评测指南](handbook/guides/evaluation.md) |
| 安全与可靠性底线 | [SECURITY](handbook/SECURITY.md)、[RELIABILITY](handbook/RELIABILITY.md) |
| 第一阶段某件事当时怎么做的 | [第一阶段归档](../archive/phase1/README.md)（含旧路径对照表） |
| 卡住了（缺凭据、缺授权、环境坏了） | [blocked/](blocked/README.md) |

## 阶段怎么切换

一个阶段结束时：把 `docs/phaseN/` 整个 `git mv` 到 `archive/phaseN/docs/`，修链接，在 `archive/phaseN/README.md` 写清里面有什么；`handbook/` 不动，只把这个阶段确立的长期设计并进去。然后新建 `docs/phase(N+1)/`，并更新本页和 [AGENTS.md](../AGENTS.md) 的“现在在哪”。

## 给后续执行者

- 一类信息只放一个地方：状态→开发计划；命令与原始输出→`phase2/operations/`；取舍→ADR；证据→`phase2/evidence/`；面试故事→`phase2/cases/`。详见[记录规则](handbook/recording.md)。
- 新增文档后在所在目录的 README 补一行，保证 `dev check` 的入口链接可达；本页与 AGENTS.md、ARCHITECTURE.md 保持短小（AGENTS/ARCHITECTURE ≤100 行由检查强制）。
- 归档只迁入、不改写。
