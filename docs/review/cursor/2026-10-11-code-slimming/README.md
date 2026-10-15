# Code Slimming Review — Cursor (2026-10-11)

> 本目录记录 cursor（GLM 5.3）主导的 travel_agent 代码精简任务全过程。
> 全部为新增文件，不改动 `docs/review/` 下任何既有内容。

## 任务定义

- 仓库：`/Users/ke.chen/開発/agent/travel_agent`（FastAPI 后端 + Next.js 前端）
- 目标：**只精简、不改行为**。找冗余/重复/无用/可合并复用的代码，以及明显可简化的写法
- 排除：测试代码不精简、prompt 不精简、`apps/web/src/lib/api-types.ts` 为生成文件不手改
- 参照：`/Users/ke.chen/開発/agent/commerce-agents`（travel_agent 的架构设计模板）

## 分支与隔离

- 工作分支：`batch/2026-10-11-code-slimming`（基于 `3b9924b`）
- Worktree：`/Users/ke.chen/開発/agent/travel_agent-slimming`（独立目录，主检出零影响）
- 已部署分支 `batch/2026-10-10-frontend-restyle` 不做任何改动；不 push

## 角色分工

- GLM 5.3（cursor）：审查 + 编号提案 + 执行 + 验证 + 记录
- Codex（gpt-6.1-sol）：逐项审批（APPROVE/REJECT/REVISE）+ 最终验收 diff，不写代码
- 测试：最终否决权。验证失败修代码，绝不删断言/减弱断言/加 skip 凑绿

## 工作流

分区审查（只读，多 agent 并行）→ `proposals.md` 编号提案（REF-xxx，交出即停）→
Codex 审批（`codex-decisions.md` 记录）→ 只执行 APPROVE 项 → 每批验证 →
Codex 验收 → commit（每批一提交，代码 + 记录 + 测试适配说明）

## 测试联动适配规则（用户 2026-10-11 批准）

在已批准的生产代码删除范围内联动适配测试，无须逐项询问：

1. 被删函数对应的业务行为仍存在 → 改写测试，保留原有断言和失败路径覆盖
2. 仅验证已明确废弃的行为 → 可删除用例，说明该行为为何已废弃
3. 测试用于构造数据 → 改用现有 fixture 或测试辅助函数
4. 不得仅因测试失败就删用例、减弱断言、增加 skip、或把期望改成当前实现的结果

提交时逐条列出改写/删除的测试及理由。

## 验证关卡

- backend：`uv run python scripts/dev.py check`；`uv run python scripts/dev.py db-up` 后 `uv run python scripts/dev.py test`
- web：`npm run typecheck` / `npm run lint` / `npm test`（node --test）
- 已知基线失败（与精简无关，不修不删断言，报告时说明）：
  `tests/integration/test_evaluation_variants.py` 的 4 个 SDK capability
  协商环境失败（`('blocked', 'auto_compaction_capability', 0, [])`）

## 进度看板

| 阶段 | 状态 |
|---|---|
| 基础设施（worktree/分支/记录骨架） | ✅ 2026-10-11 |
| Phase 1 分区审查 | ✅ 2026-10-11（主会话直读，Task 派发通道故障） |
| Phase 2 提案（REF-001~008） | ✅ 2026-10-11，见 `proposals.md` |
| Phase 3 Codex 审批 | ✅ 三轮（8/8 APPROVE，含两轮 REVISE 修订） |
| Phase 4+5 执行与验证 | ✅ 四批全部实施并验证（R1/R2/R3/R4） |
| Codex 验收 | ✅ 四批全部 APPROVE（R2 曾 REJECT 一次修复后通过） |

**任务完成（2026-10-12）**：20 文件，+223/-133（生产代码净减，测试改写与新增占
+98 行；核心成果见 execution-log 总结节）。分支 `batch/2026-10-11-code-slimming`，
未 push。

## 文件索引

- `proposals.md` — 提案总清单（REF-xxx）
- `codex-decisions.md` — Codex 审批与验收记录
- `execution-log.md` — 执行流水（每批改动、验证结果、commit）