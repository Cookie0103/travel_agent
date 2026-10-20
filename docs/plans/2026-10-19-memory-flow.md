# 2026-10-19 长期偏好进上下文 + 草稿后的合并记忆确认卡

承接 [ask-and-select-flow](2026-10-19-ask-and-select-flow.md) §3.7（`MEMORY_MERGE_EXTENSION_POINT`）与 [ADR-024](../adr/024-confirmed-memory-facts.md)。分支 `batch/2026-10-19-architecture-hardening`。只改后端与测试；离线，无付费模型调用。

## 1. 背景与决定

用户最终决定：

1. 已确认的**长期**偏好每次运行都进模型上下文，助手不再重复问。要核实并用集成测试证明；检查“遗忘边界”会不会意外藏掉别的有效事实。
2. 可成为长期偏好的只有：节奏、平时几点起床、晚上几点结束、交通方式；确认后以后的合并选择卡不再问。**只对本次行程**（默认范围本次，绝不提议为长期）：住宿类型、禁烟、床型、同行、第一天几点到、最后一天几点走。
3. 草稿暂存后，若有新增/变更的可长期偏好（来自合并卡答案或聊天），发**一组**合并记忆确认卡：默认“记住”，每条可改“这次而已/不要记”，一次确认。没有草稿不发；每个会话轮至多一组；不重复提议已拒绝或已存在且不变的。
4. 已有长期节奏时，用户说“这次想轻松”只算本次行程：不改长期、不出卡。

## 2. 现状核查（有证据的结论）

- **VERIFIED 长期偏好每次运行都注入。** 链路：`RunService._execute` → `Agent.run` → `GuardedRuntime`/worker `run_prompts` → 每个用户轮次 `DatabaseTools.context_snapshot` → `TravelService.business_context` 里 `"memory": MemoryService.snapshot_in_transaction(...)` → 拼进系统提示 `travel_prompt(...) + snapshot`（`providers/claude_agent/worker.py`、`database_tools.py`）。快照只含 active 的 long_term 事实 + 本会话 trip 事实；不依赖本会话是否提过。唯一关闭处是评测变体 `include_preferences=False`（消融用，产品路径不走）。测试 `test_new_session_context_has_confirmed_long_term_prefs_and_trip_fact_does_not_leak` 取的就是 worker 拼进系统提示的那段文本。
- **VERIFIED trip 不外泄。** `persistence.memory.active` 对 trip 按 `session_id` 过滤；上面测试里另一会话的 trip 饮食事实在新会话上下文里不存在，原会话可见。
- **VERIFIED（并修复隐患）快照有 30 条/2000 字上限**，原排序为 `(ordinal, created_at)`，多次更新后序号靠后的单值偏好会被大量兴趣挤出。现在单值偏好（`SCALAR_KEYS`）排在集合类之前（稳定排序）。该测试在改前失败（已用临时去掉排序验证），改后通过。
- **VERIFIED 遗忘边界不会藏别的事实。** `MemoryService.cutoff = max(preference_changed_at, memory_forgotten_at)`，只用于 `recent_completed`（有界对话回顾）、`valid_state`（旧 goal_prompt/待办）和 SDK 断点/来源核对；**不过滤事实**。删除一条后另外三项仍在上下文（测试 `test_forgetting_one_fact_moves_the_boundary...`）。**但要注意（REASONED，沿用 ADR-024 的有意设计）：** 边界是用户级且**任何事实变更（包括确认“记住”）都会推进** `preference_changed_at`，所以确认/删除之后，边界之前的对话回顾（`recent_dialogue`、旧 goal_prompt）会不可见；`pending_tasks` 靠 `safe_after` 证明保留，草稿靠 `pending_draft` 不依赖对话回顾。这是意外的副作用面，但不是事实丢失；本次不改（改了会削弱“删除后不复活旧内容”的保证）。
- **VERIFIED 键定义。** `MemoryKey` 原有 pace/transport/…，没有起床和晚上结束；`trip_ask_form` 的 `MEMORY_COVERS` 已预留 `wake_time`/`evening_end`。`key` 列是 `String(30)` 且**没有 CHECK**（只有 scope/status/source 有，见 0022），所以新增键**不需要迁移**。
- **VERIFIED 草稿后的挂接点**：`stage_plan_change` 分支（`tools/travel.py`），展示由 `tools/execution.py` 的 auto_present 之后发出。
- **REASONED 模型不能代确认**：确认只经 `ChoiceService.accept` 的结构化点击；新卡仍是 `memory_confirm`，沿用 `ChoiceSelection.also`。

## 3. 方案

### 3.1 键
`MemoryKey` 加 `wake_time`、`evening_end`（自由文本 ≤80，如“7:30 左右”），`KEY_LABELS` 加“平时起床/晚上结束”，自动成为单值（`SCALAR_KEYS`）。`LONG_TERM_ELIGIBLE = (pace, wake_time, evening_end, transport)`，`TRIP_ONLY_PREFERENCES` 记录六个仅本次项。`MEMORY_ASK_KEYS` 改为取 `LONG_TERM_ELIGIBLE`，所以已确认的这四项会让合并选择卡省略对应组（原有逻辑，现在键真实存在）。

### 3.2 谁产生提议：服务端，不靠模型（决定并记录）
- **合并卡答案**：服务端直接从“已提交的合并选择卡（`purpose=trip_ask`）”的回写答案（`answered_form`）推导候选（`domain/memory_merge.card_candidates`）。证据 quote = 用户在卡上的答案文字（如“旅行节奏：特种兵”），`source="user_utterance"`、`source_run_id` = 提交该卡的那一轮。不新增 source（避免迁移与前端枚举变动）。这些 quote 不在后来暂存草稿那一轮的 `run.user_text` 里，所以不走 `propose` 的“quote 必须在本轮用户原话中”规则——证据是服务端校验过的结构化点击，不是模型自述。
- 候选必须**仍与当前 request 一致**（用户事后在聊天里改了这次的值就不提议）；“无要求/不确定”、非时间的文字（“看情况”）不是偏好；到达/离开/同行/住宿/禁烟/床型永不成为候选。
- **聊天里明说**：仍由模型调 `propose_memory`（原有 quote 来源校验不变）。区别：规划进行中（有 `itinerary` 目标且尚无草稿）时，四项长期的 ADD/UPDATE 照常校验并落成待确认事实，但卡片**暂缓**（卡行带 `deferred`，不展示、不进 `choices`），工具结果说明“草稿暂存后合并”；草稿已存在时按原样立即出卡。INVALIDATE 与 trip 范围不受影响。
- 两类候选在草稿暂存后由 `ChoiceService.merge_memory_cards` 合并；同键聊天提议优先于卡答案候选。

### 3.3 合并卡
- 触发：`stage_plan_change` 成功且草稿非冲突（与 auto_present 同条件）。服务端先确认会话里确有草稿、当前执行仍在运行、遗忘边界未越过本轮。
- 每个键一张 `memory_confirm` 卡（页面 `MemoryChoices` 把同一轮的卡合成一次确认），固定选项 记住/这次而已/不要记，新增 `ChoiceCard.default_option_id="remember"`（仅合并卡设置，其余不序列化）。顺序：节奏、起床、晚上结束、交通。操作：无现值=ADD；已有不同长期值=UPDATE 并指向它（点“记住”取代，“这次而已”只遮盖本会话）。
- 不重复：同轮已发则原样返回（幂等，至多一组）；已有相同值的 active、用户级已拒绝的相同键值、已有展示中的待确认同键卡，均不提议；每张合并选择卡的每个键只评估一次（`memory_offered` 标记），用户删除或拒绝后不会因同一答案再次出现。
- 工具结果带 `memory_choices` 与提示语，`tools/execution.py` 在草稿展示之后逐张发出 presentation；暂存本身不受影响（合并失败只是不发卡）。

### 3.4 “这次想轻松”
没有任何服务端路径会把请求里的本次节奏变成长期提议：卡答案候选来自 pace 组（已有长期节奏时该组本就不出现），聊天提议只来自模型的 `propose_memory`。persona 明确规定：本次说法只改 request，不调 `propose_memory`；只有“以后/一直/平时都……”才对已确认值 UPDATE。即使模型仍提议，用户也必须点击，且卡上有“这次而已”。

### 3.5 persona
新增一段：四项可长期、六项仅本次；已确认长期偏好服务端不再问，直接写入 request；本次说法不出卡；规划中的提议会等草稿后合并；见到 `memory_choices` 只用一句话提示。

## 4. 实现

- `backend/domain/memory.py`：新键、标签、`LONG_TERM_ELIGIBLE`、`TRIP_ONLY_PREFERENCES`。
- `backend/domain/memory_merge.py`（新）：`card_candidates`。
- `backend/domain/choices.py`：`ChoiceCard.default_option_id`。
- `backend/services/memory.py`：`propose_with_deferred`（`propose` 包装它）、`add_card`/`deferred_card`/`views`、`has_draft`、快照单值优先排序、`card()` 带默认选项。
- `backend/services/choices.py`：`merge_memory_cards(_in_transaction)`；`MEMORY_MERGE_EXTENSION_POINT` 注释更新。
- `backend/tools/travel.py`、`backend/tools/execution.py`：挂接与展示；`propose_memory` 结果在暂缓时说明。
- `backend/agent/persona.py`：见 3.5。
- 无迁移（`key` 无 CHECK）。API schema 改动：`ChoiceCard.default_option_id`、`MemoryKey`/`UiMemoryKey` 增两值；已在最后执行 `scripts/dev.py web-generate` 重新生成 `data/contracts/web-openapi.json` 与 `apps/web/src/lib/api-types.ts`。

## 5. 测试

先红：快照排序测试在去掉排序时失败（已验证）；其余新测试针对不存在的 API（`merge_memory_cards`、`propose_with_deferred`、`default_option_id`、新键）。

- `tests/test_memory_merge.py`（单元）：键标签全覆盖与新键；候选只含四项且 quote 为卡上文字；仅本次项从不成为候选；不确定/空/非时间文字不是偏好；与当前 request 不一致不提议；`default_option_id` 校验；persona 文案。
- `tests/integration/test_memory_flow.py`（真 PG，串行）：新会话上下文含四项长期偏好且无他会话 trip 事实；单值偏好不被兴趣挤出；删除一条后其余仍在、边界只截断对话回顾；草稿前不发、草稿后一组四张默认记住、同轮幂等、混选一次提交（记住/这次而已/不要记）并验证新会话上下文；已确认项下次不再问、被拒绝的不再提议、到达等从不提议；聊天明说的变更暂缓后合并为 UPDATE 并生效；已有长期节奏时“这次轻松”无卡无变更；冲突草稿不发。

## 6. 改动的既有测试及理由

仅一个：`tests/integration/test_memory_continuation.py::test_memory_confirmation_keeps_tasks_but_does_not_restore_old_goal_text`（3个参数化）。原来在“有 itinerary 目标、尚无草稿”时提议 `pace`，按新决定这属于暂缓（不出卡）；该测试的目的是“确认记忆不丢待办、不恢复旧原任务文本”，与具体键无关，故把键从 `pace` 改成 `interest`，断言不变。其余既有测试未改。

## 7. 风险与遗留

- **前端**需：对 `default_option_id` 预选（`MemoryChoices` 目前无预选）；`lib/memory.ts` 的键标签/`UiMemoryKey` 新增 `wake_time`/`evening_end`；value 为自由文本时原样显示。
- 仍可被模型提为长期的旧键 `lodging_type/room_type/smoking/companion_pattern` 没有在服务端禁用（评测集 v2-memory 依赖它们；用户仍须点击）。仅由 persona 约束“只用 trip”。若要硬禁，需同时调整评测用例。
- 暂缓提议在没有暂存草稿的会话里会停在 proposed（无卡），直到该会话暂存草稿；不会生效。
- 遗忘边界推进会截断对话回顾（见 §2），后果是“确认记忆后模型少看到前两轮对话”，事实与草稿不受影响。
- 卡答案的证据是服务端核对的结构化点击，不是原话子串；偏好页的“来源”仍显示“对话中逐条确认”。

## 8. 前端落地（apps/web）

- `MemoryChoices` 用纯函数 `memoryPicks`（`lib/choices.ts`）合成有效选择：`default_option_id`（须是该卡的真实选项）作预选，用户点击覆盖，已答复的卡不预选。仍是一次“确认并继续”，提交 `ChoiceSelection.also` 不变；可逐项改成“这次而已”或“不要记”。
- `lib/memory.ts` 增加 `wake_time`“平时起床时间”、`evening_end`“晚上结束时间”；值是自由文本，`memoryValue` 原样显示。偏好页复用 `memoryLabels`，无需改动。
- 长期节奏助手（`pace.ts` `longTermPace`）只看 `key === "pace"`，新键不影响。
- 测试：`apps/web/tests/memory-defaults.test.ts`（先红后绿）。
