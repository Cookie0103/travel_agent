# 数据保留与删除方案（待用户决定）

来源：[完整性审查](2026-10-18-completeness-audit.md) 发现 G6。**本轮只出方案，没有实现**——涉及隐私、记忆“遗忘边界”语义和产品决定（批次计划待决 D2）。

## 现状

- 没有会话删除、账户删除接口；过期 demo 用户、会话、`run_events`、`evidence` 永不清理。
- `.env.example:25` 写着“V2 会话保留天数，默认 30；以下保护将在 V2 实施时接入”，检索 `backend/`、`scripts/` 没有任何 retention / purge / cleanup 实现。
- “遗忘”只覆盖偏好与记忆（`user_memory_facts` 清空值与原话、置 deleted，并设置 `users.memory_forgotten_at` 边界），**聊天原文保留**（批次决定 D1）。
- 所有外键都是默认 `NO ACTION`（已用临时库实测），没有 `ON DELETE` 策略。

## 外键依赖图

```
users
 ├─ sessions
 ├─ task_runs / evidence / bookings / plans / plan_drafts
 ├─ user_memory_facts / user_profile_summaries
sessions
 ├─ task_runs / evidence / travel_requests / choice_cards
 ├─ plans / plan_drafts / bookings / business_operations
 └─ user_memory_facts.session_id
task_runs
 ├─ run_events
 ├─ choice_cards.source_run_id 和 answered_run_id
 └─ user_memory_facts.source_run_id
evidence ← bookings.evidence_id
plans ← plan_versions / plan_drafts
user_memory_facts.superseded_by → user_memory_facts（自引用）
supplier_holds ← supplier_orders（供应商表，与用户无关）
```

以下外键列没有索引，做删除/清理时会变成慢路径：`bookings.evidence_id` / `user_id`；`choice_cards.answered_run_id` / `source_run_id`；`evidence.user_id`；`plan_drafts.plan_id` / `user_id`；`plans.user_id`；`task_runs.user_id`；`user_memory_facts.session_id` / `source_run_id` / `superseded_by`。（审计 G3 证明现有读查询不需要它们，所以本轮没加；**只有实现删除时才有意义**。）

## 删除顺序

删一个会话的安全顺序：

`run_events` → `choice_cards` → `user_memory_facts`（trip 范围，先把 `superseded_by` 置空）→ `business_operations` → `bookings` → `plan_drafts` → `plan_versions` → `plans` → `evidence` → `travel_requests` → `task_runs`（须先清掉引用它的 memory facts）→ `sessions`

删账户：对该用户所有会话重复上面的顺序，再按序清 `user_profile_summaries`、`user_memory_facts`（长期）、`users`。

## 必须注意的点

- `task_runs` 被 `user_memory_facts.source_run_id` 引用，需先置空或联带删。
- 遗忘语义依赖 `users.memory_forgotten_at` 边界：删用户数据时不能让边界失效，否则旧记忆会“复活”。
- 受益事实的来源 run 若被清掉，`checkpoint_allowed` 的校验会判定不通过。
- 记忆事实有“墓碑”语义，清理时要决定是否保留。
- catalog 导入只 upsert：快照里删掉的条目永久残留。本轮已加可选 `--prune`（见 P-C6）；若要保留历史引用的“软下线”，需要新增列（如 `catalog_entries.retired_at`），本轮无明确需求没加。

## 方案

| 方案 | 做法 | 成本 | 风险 / 前提 |
| --- | --- | --- | --- |
| A | 手写删除服务：一个事务里按上面的顺序删，不改 schema | 中（主要是顺序与测试） | 必须同时决定遗忘边界怎么处理 |
| B | 先补外键索引，再把外键改成 `ON DELETE CASCADE`（`user_memory_facts.source_run_id` 用 `SET NULL`） | 高（逐个外键 DROP 再 ADD，改动面大） | 需产品确认“级联会不会误删业务凭证”；与“迁移只做加法”相冲，需单独评估 |
| C | 过期清理脚本：按 `last_activity` 找出 N 天前的 demo 用户与会话，复用方案 A 的删除服务，带 dry-run | 中（依赖 A） | 需产品决定保留什么、用户同意方式 |

**推荐**：先做 A（可测试、不改 schema），再做 C；B 不推荐，除非另有强需求。
