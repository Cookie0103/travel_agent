# 2026-10-19 少问流程（交通重复追问、空值回显、酒店偏好前置阻塞）

产品立场：流程要宽松，“只要能查出来就行”；查询前不让用户回答多题，不唠叨。

## 1. 基本信息
- 分支：batch/2026-10-19-architecture-hardening（不提交、不推送；Railway 推送即部署）。
- 触发：一次真实 DeepSeek 运行（已部署应用），用户请求“京都2天1晚，11月20日到11月21日，2位成人1间房，住宿每晚预算1万到2万日元，公共交通出行，想看寺庙和抹茶。请帮我比较几家酒店，并生成行程。”

## 2. 问题记录

### P-1 [P1] 已说过的交通被再次询问，确认回显出现空值
- 现象：助手首条回复说“公交方式已按你的说明设好”，但随后的选择卡又问“交通方式”（步行/公共交通/打车）和“旅行节奏”；用户确认后回显为“确认：交通方式：；旅行节奏：标准。”，交通值为空。
- 假设与排除：
  - ✗ “前端把 label/value 对错了”：`answersSummary` 通过 `option_id` 到 `options.label` 查找，选项数据正常；空是因为 `answers.transport` 根本不存在。
  - ✗ “服务端丢了用户的交通回答”：`transport` 题 `required=false`，`validAnswers` 允许只答一部分（节奏已预选/点选，交通未点），所以提交合法。
  - ✓ 卡上交通没有预选：`build_form` 只预选 `request.transport`，而模型只在文字里说“已设好”，并未把 `transport` 写入 request（persona 要求先写后问，但无硬约束）。因此 request.transport 为空，服务端按“缺失”发卡。
  - ✓ 自动发卡总是整套 `TRANSPORT_PACE_GROUPS`：即使只缺 pace，卡上也带 transport。
- 根因：VERIFIED（三处叠加）。
  1. `apps/web/src/lib/choices.ts` `answersSummary`：对未回答的题照样输出“标签：”+空串，产生“交通方式：；”。
  2. `backend/services/travel.py`（`update_conversation_state` 里 `awaiting_field in {"pace","transport"}` 分支）：固定传 `TRANSPORT_PACE_GROUPS`，不看哪些字段真的缺。
  3. `backend/agent/persona.py` 交通/节奏段：没有强调“用户原话里已有的交通要第一步写入”，模型口头说设好却没写。
- 方案：
  - 采用 A：回显只输出有答案的题（空值整题省略）；时间题同理。
  - 采用 B：自动发卡改为 `groups_for_missing(missing)`，只含服务端 `missing_fields` 里仍缺的 transport/pace，已知的不再出现。
  - 采用 C：persona 明确“原话已说的交通/节奏第一步写入 request，已写入的绝不再问、不说‘已设好’却不写”。
  - 不采用：从自然语言由服务端解析交通（违反 explicit_fields 来源守卫，易误判）；把 transport 题强制必填（更唠叨，与立场相反）。
- 实现：`apps/web/src/lib/choices.ts`；`backend/domain/choices.py` 新增 `groups_for_missing`；`backend/services/travel.py`；`backend/agent/persona.py`。
- 测试（红→绿）：
  - `apps/web/tests/choice-form.test.ts::the echo never prints a group the user left unanswered`：红（实际输出 `确认：交通：；兴趣：美食；…`，与真实现象一致）→ 绿。
  - `tests/test_choices.py::test_auto_card_asks_only_for_fields_still_missing`：红（ImportError `groups_for_missing`）→ 绿。
- 改动的既有测试：无（均为新增）。
- 遗留：模型若仍不写 transport，服务端会把它当缺失，只问交通（单题），不会再带节奏/房型；根本上依赖模型遵守 persona，未做服务端自然语言解析。

### P-2 [P1] 酒店详情偏好（住宿方式/吸烟/床型）在查询前被强制询问
- 现象：交通/节奏确认后，第二张卡又问住宿方式/吸烟偏好/床型，用户需连按两次“确认并继续”才开始查酒店。
- 假设与排除：
  - ✗ 前端强制：前端只渲染服务端卡片。
  - ✗ 模型自己想问：persona 确实写了，但服务端也有硬门槛，仅改 prompt 不够。
  - ✓ `backend/domain/conversation.py:77` `task_missing(hotel_comparison)` 把 `missing_room_choices`（三组偏好各需恰有 1 个规范值）并入必填缺项。
  - ✓ `backend/domain/room_preferences.py:53` `room_preferences_question` 在缺任一组时返回“酒店查询前，请明确房型偏好”，`backend/services/hotels.py:155` 据此抛 422 `hotel_room_preferences_missing`，演示/离线运行时（`backend/agent/demo.py:52`、`fixture_conditions.py:288`）同样先问。
  - ✓ persona.py 第 44 段“先澄清住宿方式、禁烟、床型…没有说的不能默认”。
- 根因：VERIFIED。偏好被建模成“必填且不得默认”，服务端门槛 + prompt 双重强制。
- 方案：
  - 采用：偏好改为可选，未说按“无要求”（排序/资格提示本来就把未设当作 any，`room_assessment` 只在 `住宿：独立房间` 时过滤）。服务端只在同一组出现多个互斥规范值（真矛盾）时才追问并拦截。persona 改为“没提就直接查，不为此发卡/追问；查到后可附一句可再筛选”，并限制“整个对话至多一张合并的可选表单，且不阻塞查询”。
  - 不采用：新增一张“可选偏好”卡作为默认流程（即使不阻塞也多一张卡，与“别唠叨”相悖；需要时模型仍可用 `present_form` 发一张合并卡）。
  - 不采用：把无法解析的 `房型：xxx` 自由文本也视作冲突追问（更严格；选更宽松的）。
- 实现：`backend/domain/room_choices.py` 新增 `conflicting_room_choices`；`backend/domain/conversation.py` 的 `task_missing` 不再并入房型缺项；`backend/domain/room_preferences.py` 的 `room_preferences_question` 只对冲突返回问题；`backend/agent/persona.py`。`missing_room_choices` 保留（`room_choices_view`、旧记录兼容仍用）。
- 不变量保持：模型仍不能确认/保存/预订（工具集未动）；`explicit_fields` 与围栏未动；`lodging/smoking/bed` 仍是合法 `awaiting_field`，但不在 missing 时服务端拒绝记录为追问（原有 `conversation_question_unnecessary` 行为）。
- 测试（红→绿）：由下列既有测试改为新行为（先改断言，见红，再改实现见绿）：
  - 红：`tests/integration/test_room_preferences.py` 新的“缺偏好也能查询”、`tests/test_room_preferences.py` 的 `room_preferences_question(TravelRequest()) is None`、`tests/integration/test_conversation_state.py` 的 `missing_fields` 不再含 `bed`（红：`['bed','lodging_budget'] != ['lodging_budget']`）。
  - 绿：全量 `tests` 2279 passed（见 §3），其中 2 个遗漏的旧断言在全量跑出后按下表处理。
- 遗留：偏好为“无要求”默认时，用户事后才说禁烟需要重查（文字提示已提供）；`overnight_stay`、`hotel_search_location`、`lodging_budget`（行程）等其他必填不在本次范围。

## 3. 改动的既有测试及理由（逐条）
1. `tests/test_room_preferences.py::test_missing_preferences_are_optional_and_explicit_no_preference_is_answer`（原 `…have_no_defaults…`）：`room_preferences_question(TravelRequest())` 由“有问题”改为 `None`。理由：未说偏好不再阻塞。其余断言（完整三组→None、同组冲突→有问题）保留。
2. 同文件 `denied`（`"不要大床"`）由“床型出现在问题里”改为 `None`；理由：无法映射的自由文本不再逼用户重答（宽松选项）。
3. 同文件 `test_explicit_private_room_with_exclusion_text…`：原 `conflict`（单条 `住宿：独立房间，接受宿舍`，实为不可解析文本）改成真正的同组双值冲突 `("住宿：独立房间","住宿：接受宿舍",…)`，断言“有问题”保持；新增 `loose`（原单条文本）断言 `None`。理由：缺失不再是问题，冲突仍是。
4. `tests/integration/test_room_preferences.py::test_missing_room_preferences_rejects_before_query…` 重写为 `…do_not_block_query_but_conflict_does`：清空约束后 `search` 现在成功（调用 1 次、可 present）；改为 `床型：大床`+`床型：双床` 时仍 422 `hotel_room_preferences_missing`，且不新增查询。
5. 同文件 `test_missing_preferences_block_live_search…` 改名为 `test_conflicting_preferences_block_live_search_and_refresh_but_old_quotes_read`：把“清空约束”换成同组冲突，其余断言（不调用 Google/乐天、`usage.calls==0`、旧报价可读且带问题文案）保持。
6. 同文件 `test_offline_demo_asks_before_tools…` 改名为 `…_only_on_conflicting_preferences`：同上换成冲突，断言“房型”文案与仅一个 text 事件保持。
7. `tests/integration/test_conversation_state.py::test_original_goal_and_open_question_survive_three_rounds…`（原名含 bed）：原来用 `bed` 缺失作为跨三轮存活的追问；现在 bed 不再必填，改用 `lodging_budget` 做同一验证（去掉第三轮中途写入 `lodging_budget_unlimited`，最后一步再写入），全部“目标原话保留、awaiting_field 保留、missing_fields 精确匹配、最终 ready_tasks”断言结构不变。`test_known_or_optional_fields_cannot_be_recorded_as_required_question[bed]` 未改，现在更强地成立。

## 4. 验证
- `uv run python scripts/dev.py check`、`web-check`（含 node 测试与 build）、相关 pytest 与全量 `tests`（2279 passed, 1 skipped）。无付费模型调用，仅离线 fixture。
- 注：两个 integration 文件同时跑时共享临时库会互相干扰，需分开或串行（既有行为，非本次引入）。

## 5. 遗留与风险
- 模型仍可能口头说“已设好”而不写入 transport；服务端兜底为只问这一题。若要进一步，需“用户原话→transport”的服务端受限词表解析，与 explicit_fields 来源守卫要同时设计（待决）。
- 默认“无要求”意味着首轮结果不按禁烟/大床排序；已由 persona 提示用户可后补。
- 真实 DeepSeek 行为未复测（离线约束）；部署后请用同一句话复跑，期望：直接搜酒店，最多一张只含缺失项的卡。

## 第二轮：真模型复测后

### P-3 [P1] 助手在酒店结果后停下来问三个问题，没有暂存行程草稿
- 现象：用同一句话在已部署应用复测（DeepSeek）。比第一轮好：没有选择卡，直接查了酒店并展示 2 个报价。但文字回复停住并向用户提问：(a) “接受这两家酒店（都超预算）还是改日期/区域？”；(b) “节奏要标准/特种兵/慢节奏？”；(c) “11/20 几点到京都、11/21 几点离开？”。没有暂存草稿。用户立场：宽松，超预算无所谓（“超就超了”），小错误/默认值可以，不要唠叨。
- 假设与排除：
  - ✗ 酒店选择门槛：`requires_hotel_selection` / `awaiting_hotel_selection` 只在 `current.segments`（多城市）时出现，本例是单城市，不触发。
  - ✗ 到达/离开时间有服务端必填项：`task_missing` 里没有时间字段；时间题只在已写入 hard_constraints 的时间才由服务端自动追加，用户没说过时间，所以 (c) 完全是模型自己问的。
  - ✓ (b) 有服务端硬门槛：`task_missing` 对 itinerary 无条件加入 `pace`（`pace_of(request) is None`），于是 `ready_tasks` 不含 itinerary，`continuation_reason` 返回 None，运行不再被催着继续；persona 第 55 行还写着“节奏未说明时留空，在对话里追问”。
  - ✓ (a)/(c) 属 prompt：没有任何一句话告诉模型“超预算不是门槛”“时间未知就按全天规划”“同一轮要出草稿”；素材里“展示后请用户选”只针对多城市，模型把它泛化到单城市。
- 根因：VERIFIED。(b) 服务端把可选偏好建模成必填缺项 + persona 明文要求追问；(a)(c) 缺少 persona 约束，模型自行保守。
- 方案：
  - 采用 A（服务端）：`task_missing` 不再把 `pace` 并入 itinerary 缺项。节奏未说按“标准”默认；默认只出现在回复里的假设说明，不写入 request（因此不会进 `explicit_fields`、不是用户事实）。校验器本来对未知节奏就按每日上限 5 个（=标准上限）且无下限，行为已与“标准默认”兼容，不改。
  - 采用 B（prompt）：persona 新增“宽松流程”段：城市/日期/人数/房间已知就同一轮完成 查酒店→展示→规划→`stage_plan_change` 暂存；超预算只写一句“超出约 X%”、价格升序，不是门槛；单城市不要求用户先接受/选酒店（用价格最低且最贴近预算的一家并写明，事后可用只改酒店的 patch 换；多城市仍按原规则让用户选）；节奏未说不追问不发卡、按标准并注明假设；首末日抵达/离开时间视为未知，首末日按全天安排并注明，不编造时间、不写入 hard_constraints；至多在草稿暂存后附一句简短可选追问。同时改掉第 55 行“留空并追问”，第 45 行的“交通或节奏缺失才发卡”改为只对交通；`hotel-comparison.md` 技能加一句超预算不阻塞。
  - 不采用：服务端把默认 `节奏：标准` 写进 request（会被当成用户条件，违反 explicit_fields 来源守卫，且 `pace_of` 会把它当已确认）。
  - 不采用：服务端自动挑一家酒店并写入选择（单城市本来没有选择门槛，prompt 规定即可，避免新增服务端状态）。
  - 不采用：删除 `pace` 作为 `awaiting_field` 的合法枚举值（枚举保留给旧数据；不再缺失时服务端本来就拒绝记录为追问 `conversation_question_unnecessary`）。
- 实现：`backend/domain/conversation.py`（去掉 pace 缺项及未用的 `pace_of` 导入）；`backend/agent/fixture_conditions.py`（离线 `missing_question` 不再问节奏）；`backend/agent/persona.py`（四处，含新“宽松流程”段）；`backend/tools/skills/hotel-comparison.md`。
- 不变量保持：模型工具集未动，仍不能确认/保存/预订；围栏、`explicit_fields` 守卫、证据/unknown 语义未动（时间未知保持未知，不编造）；仍可由 `present_form` 展示节奏题（此时 `confirm_from_text` 仍要求先记录用户的节奏），只是不再强制。
- 测试（红→绿）：
  - `tests/test_pacing_rules.py::test_unstated_pace_never_blocks_itinerary_and_is_not_recorded_as_user_fact`：红（`'pace' not in ('pace',)`）→ 绿；同时断言 `pace_of` 仍为 None（默认没写进 request）、离线问题不再问节奏。
  - `tests/test_persona.py::test_prompt_keeps_lenient_one_turn_flow_rules`：新增 prompt 内容测试（本文件原本就有 prompt 文本断言）。
- 改动的既有测试及理由：
  1. `tests/test_persona.py::test_trip_pace_is_asked_for_without_defaulting_unspoken_user_facts` → `test_unspoken_pace_is_assumed_standard_but_never_recorded_as_user_fact`：原断言 prompt 含“节奏未说明时留空”（要求追问），与新立场相反；改为断言新文案，并保留“不把标准写成用户事实”的原意。
  2. `tests/test_fixture_conditions.py::test_other_soft_preferences_do_not_make_unspoken_pace_known`：原断言离线问题含“节奏”；改为断言 `pace_of` 仍为 None（“少走路”不能推断节奏，原意保留）且不再追问节奏。
  3. `tests/integration/test_choices.py`：`test_awaiting_pace_automatically_emits_card…` 改名 `…awaiting_transport…`，`source_card` 辅助函数：用 `awaiting_field="pace"` 作为“缺失字段”，现在 pace 不缺，服务端会 422；改用同样缺失的 `transport`。该测试里的显式 `present_form` 复用同一张卡，groups 改为只含 transport（自动卡现在只含仍缺的题）。断言结构（自动发 1 张卡、显式展示复用同 choice_id、revision 不变）保持。
  4. `tests/integration/test_memory_continuation.py`：同样把 `awaiting_field` 的占位字段从 `pace` 换成 `transport`（记忆键 `pace` 的断言不动）；目的是验证追问字段在多轮保留，与具体字段无关。
  5. `tests/integration/test_sdk_choices.py::test_native_sdk_roundtrips_server_owned_pace_card`：脚本里的 `awaiting_field=pace` 改为 `transport`（pace 不再缺失会 422）；自动卡现在只含交通，故由“两次展示同一张卡”改为“第一张只含 transport，第二张（显式 present_form）含 transport+pace 且选项由服务端固定”，选项标签断言原样保留在第二张上。
- 验证：`dev check`、相关 pytest、全量 `dev test`（结果见下）。无付费模型调用，仅离线 fixture。prompt 修改的真实效果必须再用 DeepSeek 复跑同一句话确认，期望：酒店展示后同一轮出草稿，回复含“超预算 / 节奏按标准 / 抵达离开时间未知”的假设说明，最多一句草稿之后的可选追问。
- 遗留：prompt 无法保证模型一定遵守；若仍停下，再考虑 `continuation_reason` 在“酒店已展示、itinerary 待办未完成”时由服务端催一次（现有机制已对 ready_tasks 催促，pace 解除后应能触发）。默认“标准”只体现在回复里，不会出现在草稿的条件区；首末日时间未知时的全天安排依赖模型说明。

## 第三轮：超预算不再阻止确认

### 现象
真实复测中 2 天草稿显示“有硬冲突，不能确认”，确认保存按钮置灰；唯一的硬冲突是 `hotel_over_budget_unaccepted`（“住宿报价超过预算上限，请先接受预算放宽或选择预算内报价”，分类“其他校验”）。用户明确决定：超预算酒店不得阻止确认，应是带超出额的警告。

### 假设与排除
- ✗ 前端自行计算“可确认”：`results.tsx:636` 的 `blocked`、`conversation.tsx:467`、`business-status.ts:29` 全部只读 `validation.status === "conflict"`，没有任何预算专用逻辑，前端无需改。
- ✗ 确认接口另有预算门槛：`PlanService.confirm` 只在重新校验 `report.status == "conflict"` 时拒绝（`backend/services/plans.py:326-327`）。
- ✓ 冲突源于校验器：`backend/domain/validator.py` 的 `accepted_hotel_budget_checks`（约 637 行起）把超预算报价标为 `conflict`，状态聚合（`conflict` > `unknown` > `complete`）使整份报告变冲突。

### 根因
VERIFIED：ADR-022 时期把“未接受放宽的超预算报价”建模为硬冲突，与现在“宽松流程、超就超了”的用户立场相反。

### 方案
- 采用：同一检查码 `hotel_over_budget_unaccepted` 的状态由 `conflict` 改为 `unknown`（校验器现有的“警告”词汇，聚合为 `partial`，与已有 `hotel_over_nightly_budget` 一致），文案改为“超出原每间每晚预算 +9,160 JPY（+45.8%）；…”，由同一份 `nightly_upper/nightly_price` 计算，不新增事实。码不变，便于日志/评测延续。
- 不采用：删除该检查（会丢失超出额提示）；新增 severity 枚举（词汇已够）；删除预算放宽卡流程（用户要求保留，只是不再前置）。
- 不变：全程总预算冲突 `known_cost_over_budget`、`lodging_budget_conflict`（住宿预算下限超过全程预算）、时间重叠等仍是硬冲突。

### 实现
- `backend/domain/validator.py:637-662`：降级并生成超出额文案。
- `backend/agent/persona.py:70`、`backend/tools/skills/hotel-comparison.md:9`：删去“不能规划超预算住宿 / 不得以超预算报价规划”，改为只提示。
- `docs/adr/022-hotel-budget-recovery.md` 末尾追加 2026-10-19 补充（未改写历史）。
- 前端无改动（状态驱动，`partial` 时按钮可用，警告文本经 `validation-groups` 作为“未知”组展示）；hotel 卡的超出额显示（`results.tsx:172-176`、`hotels.py:420`）未动。

### 测试
- 红→绿：`tests/integration/test_lodging_budget.py::test_over_budget_hotel_draft_can_be_confirmed_with_warning`（真实 PG：超预算报价暂存后无冲突、警告含“超出原每间每晚预算 +”，`PlanService.confirm` 成功且保存了该酒店）；单元：`tests/test_hotel_recovery.py::test_over_budget_hotel_warns_with_excess_but_does_not_block`。
- 离线 fixture，无付费调用。

### 改动的既有测试及理由
1. `tests/test_hotel_recovery.py::test_over_budget_cannot_be_planned_before_acceptance` → `test_over_budget_hotel_warns_with_excess_but_does_not_block`：原断言 `status == "conflict"`；新规则为 `unknown`/`partial`。
2. 同文件 `test_total_budget_cannot_be_reused_in_full_for_each_segment`：仍断言两段各一条 `hotel_over_budget_unaccepted`（数量不变），只把状态改为 `unknown`/`partial`。
3. 同文件 `test_single_city_legacy_hotel_reference_cannot_bypass_budget` → `…_over_budget_only_warns`：该 fixture 本就同时触发 `known_cost_over_budget`（全程总预算，另一规则），故断言硬冲突集合恰为 `{known_cost_over_budget}`，证明该规则未被放宽。
4. `tests/test_multi_city_itinerary.py::test_nightly_budget_conflict_blocks_unaccepted_increase_and_unlimited_skips_it` → `…excess_warns_without_blocking…`：两条 `hotel_over_budget_unaccepted` 由 `conflict` 改 `unknown`，总状态 `partial`；`hotel_over_nightly_budget` 两条、`known_cost == 30000`、不限预算不误报等断言原样保留。

### 遗留
- 多城市“选择酒店”提交仍有服务端闸门：`backend/services/hotels.py:497-503` 对超预算选择返回 422 `hotel_over_budget_unaccepted`（`validate_hotel_selection`）。本轮只改确认链路，未动它；若希望多城市也可直接选超预算酒店，需再放宽此处（并改对应测试）。
- 校验文案里出现“可在确认前换预算内报价，也可接受超预算”，未接 UI 上的接受按钮；预算放宽卡仍按原流程独立存在。
- 真实模型下 persona 变更效果未复测。

## 第四轮：多城市超预算选酒店放宽

### 现象
第三轮遗留：多城市“选择酒店”提交时，用户选了超过每间每晚预算的报价，服务端直接 422 `hotel_over_budget_unaccepted`（“所选酒店超过原住宿预算，请先接受预算放宽。”），选不了。用户明确决定（2026-10-19）：必须允许，仅作警告。

### 根因
VERIFIED：`validate_hotel_selection` 里有独立于校验器的超预算闸门，仍是 ADR-022 的“先接受放宽才能选”模型，与第三轮“超预算是警告”不一致。

### 方案
- 删除该闸门，选择按其余守卫通过；超出额不另存，由第三轮已有的校验器检查 `hotel_over_budget_unaccepted`（status `unknown`，文案“超出原每间每晚预算 +X JPY（+Y%）”）在暂存/校验时生成，用户经校验结果看到。
- 不变：过期/陈旧报价、未知证据、段数与日期覆盖、报价不属于对应住宿段、入住日期不匹配等守卫；预算放宽卡代码保留未删。
- 前端：检索 `apps/web/src` 无任何“超预算被拒/需先接受放宽”的文案或逻辑（无 `hotel_over_budget_unaccepted` 引用），故无改动、不需 `web-check`。

### 实现
- `backend/services/hotels.py`（`validate_hotel_selection`，约 494-495 行）：移除 `nightly_upper/nightly_price` 比较与 422，原位留注释。

### 测试
- 红→绿：`tests/integration/test_segment_hotel_selection.py::test_over_budget_segment_hotel_selection_is_allowed_with_warning`（真实 PG，三城市，每间每晚预算设为 1，三段各选一家 → `RunService.submit` 成功；对所选报价 `accepted_hotel_budget_checks` 返回 `unknown` 的 `hotel_over_budget_unaccepted` 且文案含“超出原每间每晚预算 +”）。修复前该测试在原 422 处失败。
- 离线 fixture，无付费调用。

### 改动的既有测试及理由
无。此前没有测试编码“多城市超预算选择被拒”；其余选择守卫测试（missing/dates/unknown/revision/expired）原样保留。

### 遗留
- 校验文案仍写“也可接受超预算”，UI 无对应接受按钮；预算放宽卡独立存在。
- 选择结果本身（提交响应）不携带警告文本，警告在暂存草稿的校验结果里出现；如需在选择当下就提示，需另行设计。
