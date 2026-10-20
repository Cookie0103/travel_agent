# 历史归档

2026-10-18 整理时迁入。这里是**已被取代的历史材料**：保留原文、不再更新，每份文件顶部加了“已归档”说明。当前状态一律看 [批次索引](../plans/README.md#批次索引)；不要把这里的结论当现状。迁移用 `git mv`，历史可用 `git log --follow` 追溯。

| 归档位置 | 内容 | 取代它的当前材料 |
| --- | --- | --- |
| [execution/travel-agent.md](execution/travel-agent.md) | 2026-10-08 之前的长程执行计划（约 104 KB：M0–M4 任务状态、授权额度、每日进展） | [docs/plans/](../plans/README.md) 批次计划 |
| [operations/](operations/) | 2026-10-02/03 的操作日志与 `.commands.jsonl` 原始命令（M0 核心、SDK 文档、协议实测、修复、目录整理、长程自主日志） | 当前操作手册见 [operations/](../operations/README.md) |
| [blocked/](blocked/) | 已解除的阻塞：2026-10-02 M0 核心、2026-10-03 M0.2 真实调用授权 | [blocked/README](../blocked/README.md) 仍保留未关闭项 |
| [review/M0*.md](review/) | M0 / M0.1 / M0.2 集中审查与 SDK 路线说明 | [tasks/M0.md](../tasks/M0.md)、[ADR-003](../adr/003-claude-agent-sdk-runtime.md) |
| [review/batch/](review/batch/) | 2026-10-02/03 两份批次总结 | 批次计划 §9 “验证与交付” |
| [review/cursor/](review/cursor/) | 2026-10-11 Cursor（GLM）代码精简审查全过程（含 schema 指纹基线） | 精简结果已并入代码；背景可查 |
| [proposals/](proposals/) | 早期前端重设计与后端调查，仅作历史背景 | [PRODUCT-V2-PLAN](../proposals/PRODUCT-V2-PLAN.md)、[前端约定](../guides/FRONTEND.md) |

## 归档文件清单

- 执行计划：[travel-agent.md](execution/travel-agent.md)。
- 操作日志（2026-10-02/03）：[M0 核心](operations/2026-10-02-m0-core.md)、[SDK 文档](operations/2026-10-03-agent-sdk-docs.md)、[长程自主日志](operations/2026-10-03-autonomous.md)、[人民币/美元预算线路](operations/2026-10-03-budget-currencies.md)、[报错修复与 Docker/PG 核对](operations/2026-10-03-development-errors.md)、[目录整理](operations/2026-10-03-directory-cleanup.md)、[M0.2 配置准备](operations/2026-10-03-m02-preparation.md)、[M0.2 协议实测](operations/2026-10-03-m02-protocol.md)（脱敏[结果](operations/2026-10-03-m02-protocol.result.json)；各 `.commands.jsonl` 在同目录）。
- 阻塞记录：[2026-10-02 M0 核心](blocked/2026-10-02-m0-core.md)、[2026-10-03 M0.2 真实调用授权](blocked/2026-10-03-m02-live.md)。
- 审查材料：[M0](review/M0.md)、[M0.1](review/M0.1.md)、[M0.2](review/M0.2.md)、[SDK 路线说明](review/M0-sdk-route.md)；批次总结 [10-02 M0 核心](review/batch/2026-10-02-m0-core.md)、[10-03 修复](review/batch/2026-10-03-m0-repair.md)；[Cursor 代码精简审查](review/cursor/2026-10-11-code-slimming/README.md)。
- 提案：[后端调查](proposals/BACKEND-CHANGE-INVESTIGATION.md)、[前端重设计](proposals/FRONTEND-REDESIGN.md)。

## 归档规则

- 只归档**已被新材料取代、且不再被日常工作引用**的文件；有信息量的内容迁移不删除。
- 不改写原文。需要更正时在文件顶部追加一行说明；大文件不重写。
- 归档后修正全仓相对链接，并确认文档链接检查为 0 死链。
- `docs/blocked/environment.md` 由 `scripts/dev.py` 的 `record_blocked` 写入，**不要移动**。
- macOS 的 `.DS_Store` 已删除并写入 `.gitignore`。
