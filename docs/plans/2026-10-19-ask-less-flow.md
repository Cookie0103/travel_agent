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
