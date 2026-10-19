# 批次计划与开发记录规则

2026-10-08 起生效。本文件规定：**修复/开发批次的计划写在哪里、状态在哪里维护、开发过程怎么记录、面试材料怎么沉淀**。所有执行者（Codex/GPT、Claude、本人）都按这里记录。

## 1. 目录职责（一类信息只放一个地方）

| 位置 | 放什么 | 不放什么 |
| --- | --- | --- |
| [docs/design/](../design/README.md) | 长期设计：目标、架构、数据与工具、总路线(M0–M4)、验收、来源 | 某一批次的任务状态、每日进展 |
| **docs/plans/YYYY-MM-DD-主题.md** | 一个批次的：范围、待决事项、设计取舍、任务表与**唯一状态**、每日进展、问题解决记录（摘要）、交付 | 长命令输出、完整日志 |
| [docs/operations/](../operations/) | 原始过程：执行的命令与真实输出摘要、失败尝试细节、部署/回退操作 | 任务状态（只链接回批次计划） |
| [docs/adr/](../adr/) | 新增接口/字段/依赖/契约等实质取舍：背景、选项、决定、后果 | 样式类小修 |
| [docs/review/cases/](../review/cases/) | 面试案例：按 STAR 写成可以讲的故事 + 深挖问答 + 证据链接 | 未完成的推测（标“候选”） |
| [docs/execution/](../execution/) | 通用工作流、工程标准、验证规则；`travel-agent.md` 已移入 [docs/archive/execution/](../archive/execution/travel-agent.md)（2026-10-08 之前的历史执行记录） | 新批次的状态 |
| [docs/evidence/](../evidence/) | 脱敏证据文件（JSON、截图） | token、密钥、私人对话原文 |

**单一事实规则**：任务状态只在当前批次计划里改。别处需要时写链接，不复制完成清单。设计变更改 design/ 或批次计划的“设计”节；不在 operations 里“顺便”改设计。

## 2. 批次计划怎么建

- 命名：`docs/plans/<开始日期>-<主题>.md`，例：`2026-10-08-product-v2.md`。一个修复批次一份，跨天继续追加，**不按天、不按 Bug 新建文件**。
- 固定章节（顺序不变）：
  1. 基本信息：开始日期、目标(一句话)、done means、范围/不做、分支、基线 commit
  2. 待用户决定：编号 D1…，每项写推荐项和不决定的影响；决定后写日期与结论，不删除
  3. 评审与设计：问题核实结论、方案取舍、各阶段设计要点
  4. 任务表：任务 ID、关联 Bug、依赖、验收条件（可执行：测试名/操作）、状态、证据
  5. 边界与不变量
  6. 发布与回退
  7. 每日进展（倒序，最新在上）
  8. 问题解决记录（P-编号）
  9. 验证与交付
- 新批次开始时，在 [AGENTS.md](../../AGENTS.md) 和 [docs/README.md](../README.md) 的“当前批次”处改成新文件链接。

## 3. 状态与证据标注

| 状态 | 含义 |
| --- | --- |
| `todo` | 未开始 |
| `doing` | 正在做（同一时间尽量只有 1–2 个） |
| `blocked` | 等外部条件/用户决定；写清等什么 |
| `done` | 代码已提交，**且**验收条件里列的检查已实际运行通过 |
| `dropped` | 不做了；写原因与日期 |

- 证据列写：commit 短 SHA + 跑过的命令及结果数字（例：`a1b2c3d · dev test 312 passed · web test 48 passed`）。
- 结论标注三档：**VERIFIED**（运行/复现过）、**REASONED**（读代码推断）、**ASSUMED**（未核实）。不能悄悄升级；“读代码能解释”只算 REASONED。
- “离线通过 / PG 集成通过 / 浏览器验收 / 真实 API 验收 / 独立审查”是五件不同的事，分别写，不合并成“已完成”。

## 4. 开发时怎么记录（执行者必须遵守）

在以下时刻写记录，而不是做完一大段再回忆：

| 时刻 | 写到哪里 | 写什么 |
| --- | --- | --- |
| 开始一个任务 | 批次计划任务表 | 状态改 `doing` |
| 复现/定位问题 | 批次计划 §8 新增或更新 P-条目；命令细节进 operations | 现象、假设清单（每个假设 ✓/✗ + 证据） |
| 遇到计划外的问题 | §8 新 P-条目（标“计划外”） | 为什么没预料到；是否影响其他任务 |
| 放弃一个做法 | §8 对应条目“尝试过的方法” | 做了什么、为什么不行（失败也要留） |
| commit 后 | 任务表证据列 + §8 条目“实现与验证” | SHA、改动文件、先红后绿的测试名与输出 |
| 当天结束 | §7 每日进展 | 按模板 4 行 |

### 每日进展模板

```markdown
### 2026-10-09
- 计划：T1.1、T1.2
- 完成：T1.1（a1b2c3d）；P-03 根因 VERIFIED
- 未完成及原因：T1.2 卡在 …（见 P-04）
- 下一步：…
```

### 问题解决记录模板（§8，每个 P-条目）

```markdown
### P-03 [B05] 刷新后对话历史丢失   状态：done   关联：T1.2 T1.3
- 现象：输入/前提 → 实际 → 期望（附截图或 run_id，脱敏）
- 环境：分支、commit、本地/Railway、数据库
- 假设与排除：
  1. ✗ 后端没存消息 —— PG 中 task_runs 有 prompt/answer（查询见 operations#…）
  2. ✓ 前端只恢复 localStorage 里的一个 run_id —— use-workspace.ts:206
- 根因：……（VERIFIED：失败测试 test_xxx 复现）
- 方案对比：A …（采用，理由）/ B …（不采用，理由）
- 实现：改动文件；commit
- 测试：首次失败输出 → 修复后通过输出；邻近边界测试
- 结果与遗留：还不知道/没覆盖的
- 面试一句话：……
```

## 5. 面试案例怎么沉淀

- 文件：`docs/review/cases/<批次开始日期>-<主题>.md`，一个批次一份，内含多个案例。
- **一个案例对应的 P-条目全部 `done` 之后**才把它从“候选”改成“完成”，再按模板写：
  1. 背景（S）：用户场景、影响多大
  2. 任务（T）：要保证的不变量
  3. 行动（A）：怎么定位（假设→排除→证据）、方案取舍、具体实现、测试
  4. 结果（R）：前后对比证据，只写实测数字
  5. 深挖问答：面试官可能追问的 3–5 个问题与回答
  6. AI 协作边界：哪些是 AI 做的、我自己判断/核实了什么
- 不编造指标；未复现的问题不写成“修复了”。

## 6. 禁止事项

- 在两个地方维护同一份状态；把旧历史记录的结论改写成新结论（历史只追加更正说明）。
- 用“没报错”“模型说完成了”当验收；为通过测试而改断言或跳过检查。
- 提交 token、密钥、私人对话原文、无关账号截图。

## 批次索引

按时间倒序。**新批次开始时在表头插入一行**（并按 §2 更新 [AGENTS.md](../../AGENTS.md) 与 [docs/README.md](../README.md) 的“当前批次”链接）。状态只是索引用的概括，权威状态在各批次文件；“案例/证据”列只放已存在的文件。

| 批次文件 | 一句话目标 | 状态 | 面试案例 / 证据 |
| --- | --- | --- | --- |
| [2026-10-19-session-log](2026-10-19-session-log.md) | 加固收尾：复核修复、清理第二批、迁移 0023、Railway 切分支与真模型（DeepSeek）验证、问得更少的流程 | 实施中；分支 `batch/2026-10-19-architecture-hardening` | [追问流程](2026-10-19-ask-less-flow.md) |
| [2026-10-18-completeness-hardening](2026-10-18-completeness-hardening.md) | 对抗性审查后修复真实缺陷（live 额度、数据库约束、Windows 事件循环等），并整理文档与测试总览 | doing | [审计报告](../review/audits/2026-10-18-completeness-audit.md)、[测试总览](../testing/README.md) |
| [2026-10-15-speed-repair-and-form](2026-10-15-speed-repair-and-form.md) | 提速、保证交付（冲突草稿也能暂存）、局部修复、通用表单取代写死的组合卡 | 实施中；本地已提交，真实模型速度仅线上首测 1 次（57.4 s/12 请求），未做 2 次验收 | [ADR-030](../adr/030-generic-choice-form.md)、[论文调研](../proposals/2026-10-15-planning-repair-research.md) |
| [2026-10-13-interaction-memory-eval](2026-10-13-interaction-memory-eval.md) | 回答不丢、外部故障自愈、酒店预算先自救、确认记忆，并用 V2 评测与 Langfuse 关联证明 | 2026-10-14 修复批次最终验收；用户 24 行人工标注与 κ 未完成；之后追加了 10-15 的补丁 | [面试案例](../review/cases/2026-10-13-interaction-memory-eval.md)、[操作手册](../operations/interaction-memory-eval.md)、[evidence/t*、f*](../evidence/README.md) |
| [2026-10-11-segment-hotel-selection](2026-10-11-segment-hotel-selection.md) | 多城市按住宿段逐段选酒店后统一规划；人工使用不再被单轮次数截断 | done（H1–H4） | [ADR-019](../adr/019-segment-hotel-selection.md)、[evidence/2026-10-11-*](../evidence/README.md) |
| [2026-10-10-multi-city-pacing](2026-10-10-multi-city-pacing.md) | 多城市行程、住宿预算分项、节奏密度、停留时长 | done（T0–T5；10-11 本轮交付） | [ADR-015](../adr/015-lodging-budget-and-condition-source.md)、[evidence/2026-10-10-*](../evidence/README.md) |
| [2026-10-08-product-v2](2026-10-08-product-v2.md) | Product V2 修复：保存丢失、条件版本、酒店覆盖、前端迁移、真实验收 | 2026-10-10 带已知限制结项（系统自动排行程另批） | [面试案例](../review/cases/2026-10-08-product-v2.md)、[操作记录](../operations/product-v2.md)、[evidence/product-v2/](../evidence/README.md) |
| [archive/execution/travel-agent](../archive/execution/travel-agent.md) | 2026-10-08 之前的 M0–M4 长程执行计划 | 已归档（历史） | [archive 索引](../archive/README.md) |

## 相关索引

- [问题与修复索引](problems.md)：全部 P-条目的编号、标题、状态。
- [测试总览](../testing/README.md)、[ADR 索引](../adr/README.md)、[操作记录](../operations/README.md)、[证据索引](../evidence/README.md)。
