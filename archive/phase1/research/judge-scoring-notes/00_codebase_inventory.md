# 00 代码库盘点（供「评判打分落地方案」写作者使用）

- 盘点时间：2026-11-26；仓库 `D:\项目\秋招项目\PLAID\travel-agent`；分支 `main`，HEAD `dedcf84`（2026-10-28）。全程只读，未跑评测/真实调用/迁移，未读 `.env`。
- 证据标记：**【读】**=逐行读过源码/文档；**【跑】**=用 `.venv/Scripts/python.exe` 跑只读脚本或 `pytest --collect-only`（不写缓存）得到；**【推】**=推断，未直接验证。
- 行号均指 HEAD 版本。路径相对仓库根。

## 0. 对「已知信息」的核对

| 说法 | 核对结果 |
|---|---|
| `backend/domain/validator.py` 约 712 行 | 712 行【跑】 |
| 约 40 个 check code，状态 conflict/unknown/verified | **41 个**不同 code（37 个字面量 + `lodging_budget_{conflict,within,unknown,warning}` 4 个拼接值）【读+跑】；`CheckStatus` 定义在 `backend/domain/itinerary.py:121` |
| 自由文本硬条件在 ~L85 一刀切 unknown | `validator.py:85-93`，code=`free_text_constraints`；**只要 `request.hard_constraints` 非空就触发**，即使里面全是规范文本（`节奏：标准`、`住宿：独立房间`）也触发【读】。最终 90 次 trial 的 9 份草稿里 9/9 触发【跑】 |
| 「下雨→室内」只是系统提示词里的一句话 | `backend/agent/persona.py:57`（第 22 段）「规划户外景点前先查天气，降水概率≥60%优先考虑室内；未知不猜测」，全 prompt 仅此 1 处【跑】。校验器无对应规则。另有：`PlaceSearchInput.indoor` 参数（`domain/catalog.py:175-176`），离线演示 `agent/fixture_runtime.py:126-137` 在 prompt 含「室内/雨」时带 `indoor=True` |
| 任何地方都没有 commission / partner 字段 | 属实【跑 grep：backend/eval/data/tests/scripts/apps/web/src + docs】。唯一相关物是乐天联盟 ID `RAKUTEN_AFFILIATE_ID`（`adapters/rakuten.py:139,188-189`、`adapters/live_data.py:41`），只用于生成联盟链接，不进报价对象 |
| 6 个 skill 文件 + `load_skill`；prompt 只给 4 个写了触发条件 | 属实【读+跑】。`hotel-comparison`、`itinerary-revision` 在 `travel_prompt()` 中出现 0 次，只存在于 `SkillInput` 枚举（`tools/travel.py:70-79`） |
| `eval/cases/v3.jsonl` 30 题 7 类 | 属实【跑】：main_flow 4 / ambiguous 5 / mid_change 5 / fault 5 / out_of_scope 3 / memory 6 / adversarial 2 |
| `cb203d0` 把业务 prompt 从 11,035 减到 9,563 字符 | 属实【跑：`git show` + ast 取字面量】：业务字面量 11,035→9,563（−1,472）。HEAD 现为 **9,042**（之后又少 521）。`docs/plans/2026-10-26-commerce-agent-optimizations.md:48` 写的是「16163→14691」，差值同为 1,472，口径不同（无法复现其基数） |

---

## A. 规则层

### A1 入口、签名、数据流【读】

- 纯函数 `validate_itinerary(request, proposal, records, now, *, transport_default=None) -> ValidationReport`（`validator.py:51-100`）。输入只有四样：`TravelRequest`、`ItineraryProposal`（items + hotel_evidence_id/hotel_stays）、本行程引用到的 `EvidenceRecord` 元组、当前时间。**没有天气、没有上一版草稿、没有用户记忆、没有未被引用的候选**。
- `EvidenceKind = Literal["place","article","hotel_offer","route"]`（`domain/evidence.py:13`）——没有 weather。
- 服务层包装 `validate_proposal(db, context, request, proposal, live)`（`services/planning.py:152-206`）：解析证据（`resolve_records`，`services/travel.py:697-741`，缺失→404 `evidence_missing`，失效→409 `evidence_stale:<kinds>`）、`hydrate_records`、读已确认交通偏好 `memory.transport_default`，再调纯校验器；校验器抛的 `ValueError` 转 422 `validator:<reason>`。
- 报告：`ValidationReport{status: complete|partial|conflict, checks, known_cost, estimated_cost, scope}`（`itinerary.py:141-165`）。`status` = 有 conflict→conflict；否则有 unknown→partial；否则 complete（`validator.py:94-97`）。
  - **`other_costs` 无条件 unknown（`validator.py:480-487`）⇒ `complete` 实际不可达**【读】。旁证【跑】：`.cache/verification-sweep-20261004.json` 各组 `constraints.states.complete = 0`、`observed_hard_constraint_pass_rate = 0.0`。
- 给模型的反馈 `feedback()`（`itinerary.py:149-165`）：按 conflict→unknown→verified 排序、`pace_warning`/`repeated_place_warning` 优先，**只给前 12 条** + `check_counts` + `truncated`。
- TRACE 标签 `traced()`（`validator.py:41-48`）：`code:status@d{天}i{项}` + 时刻，仅进 TRACE 日志，不进 API/事件。

### A2 全部检查（41 个 code）【读】

「仅多城市」= 代码用 `if request.segments` 门控；`segments` 的 `min_length=2`（`travel_request.py:93`），**单城市请求 `request.segments is None`，这些规则不跑**。tier 列为评测分级（`eval/v3_tiers.py:9-49`），「未登记」= 落到 `DEFAULT_TIER="soft"`。

| # | code | 可能状态 | 触发条件 | 读取的输入 | 行号 | 仅多城市 | eval tier |
|---|---|---|---|---|---|---|---|
| 1 | `trip_dates` | unknown / conflict / verified | 日期未齐→unknown；item 的东京日期早于 start 或晚于 end→conflict；否则 verified（每个 item 一条） | request.start_date/end_date、item.start/end | 302-309 | 否 | hard |
| 2 | `visit_duration` | conflict | `end <= start`（直接返回，该 item 不再做其他检查） | item.start/end | 276-277 | 否 | soft |
| 3 | `visit_duration_range` | unknown / conflict | 时长不在类别区间内→unknown；`< lower/2` 或 `> upper*2`→conflict | place.category、`VISIT_DURATION_RANGES`（`catalog.py:97-123`，38 类 8 档，如 museum 45–180、temple 20–120、theme_park 180–600 分钟） | 278-301 | **是** | 未登记 |
| 4 | `place_source` | unknown | place 证据 `status!="verified"`（缺 provider/source_ref/content_version 或 value 为空） | EvidenceRecord.status | 310-311 | 否 | hard（但只会 unknown，不会判失败） |
| 5 | `city` | conflict（单城市且 request.city 空时 unknown） | 多城市：place.city 不在 `cities_on(request, 当天)`（转场日允许两城）；单城市：`request.city != place.city`（**字符串严格相等，不走 `same_city` 别名**） | place.city、request.city/segments | 312-331 | 两套逻辑 | hard |
| 6 | `overlap` | conflict | 前一项 end > 本项 start（或列表未按时间排序） | 相邻 item | 332-337 | 否 | soft |
| 7 | `opening_hours` | verified / conflict / unknown | `opening_state()`（`domain/opening_hours.py:59-87`）：整段停留被营业窗口覆盖→verified；不覆盖→conflict；无数据/语法不支持（节假日、季节、注释）/停留>1天/place 缺来源→unknown | place.opening_hours、item.start/end | 338-363 | 否 | soft |
| 8 | `departure_time` | conflict | `request.departure_time`（每日出发时刻）存在且当天首项开始早于它 | request.departure_time | 364-371 | 否 | soft |
| 9 | `route_unexpected` | conflict | 当天首项带了 route_evidence_id | item.route_evidence_id | 385-405 | 否 | soft |
| 10 | `route_missing` | unknown | 非首项没有 route_evidence_id | 同上 | 406-407 | 否 | soft |
| 11 | `route_source` | unknown | route 证据 status=unknown | route EvidenceRecord | 411-412 | 否 | soft |
| 12 | `route_scope` | conflict | route 起终点 ≠ 前项/本项 place 的 entity_id，或 route.transport ≠ `request.transport or transport_default` | RouteEstimate、place 证据 entity_id、交通方式 | 418-434 | 否 | soft |
| 13 | `route_departure` | conflict | route.departure < 前项 end，或 > 本项 start | RouteEstimate.departure | 436-451 | 否 | soft |
| 14 | `route_duration` | unknown | route.minutes 为空（live：查询失败/额度用完；fixture：路段表未覆盖） | RouteEstimate.minutes、record.data_mode | 452-458 | 否 | soft |
| 15 | `route_gap` | conflict | departure + minutes > 本项 start | 同上 | 459-460 | 否 | soft |
| 16 | `route_live` | verified | data_mode=live 且时间够 | record.data_mode | 461-462 | 否 | soft |
| 17 | `route_estimate` | unknown | 非 live（fixture/synthetic）且时间够 | 同上 | 463-470 | 否 | soft |
| 18 | `pace_too_sparse` | unknown | 节奏已知（下限：慢节奏 2 / 标准 4 / 特种兵 6）时，完整日（非首末日、非转场到达日）已知景点数 < 下限；或连续完整日区间一个景点都没有 | `pace_of(request)`、place.category∈`SIGHTSEEING_CATEGORIES`（38 类）、segments | 129-165 | **是** | soft |
| 19 | `day_gap` | unknown | 同日同城相邻两项间隔 > 3 小时 | 相邻 item、place.city | 166-187 | **是** | soft |
| 20 | `pace_warning` | unknown | 某日已知景点数 > 上限（慢节奏 3 / 标准 5 / 特种兵 8；节奏未知默认 5） | 同 18 | 188-202 | 否（但见 A10-G5） | soft |
| 21 | `repeated_place_warning` | conflict | 同一 `place_id`（景点类别）在全行程出现 >1 次 | place.place_id、category | 203-216 | 否 | soft |
| 22 | `meal_time` | unknown（全行程汇总成 1 条，最多列 4 个） | 非首末日：早饭=首项开始距 07:00 不足 1h；午饭(12–14)/晚饭(18–20)=有项目触及窗口且 06:00–23:00 间没有 ≥2h 且与窗口相交的空档 | item 时间、request.start_date/end_date | 220-266 | 否 | soft |
| 23 | `other_costs` | unknown | **无条件** | — | 480-487 | 否 | soft |
| 24–27 | `lodging_budget_conflict` / `_within` / `_unknown` / `_warning` | conflict / verified / unknown / unknown | `lodging_budget_relation(request)`（`travel_request.py:473-535`）：住宿预算下限总额 > 全程预算→conflict；上限 ≤ 全程预算→within；上限 > 全程预算→warning；缺数据→unknown | request.lodging_budget/budget/rooms/日期 | 488-500 | 否 | 未登记 |
| 28 | `hotel_missing` | unknown | 单城市路径且没有 hotel_evidence_id / hotel_stays | proposal | 510-511 | 否 | soft |
| 29 | `route_fare` | unknown | 路段没有 fare 且不是「步行且有耗时」 | RouteEstimate.fare/transport | 512-527 | 否 | soft |
| 30 | `budget_missing` | unknown | request.budget 为空 | request.budget | 528-529 | 否 | soft |
| 31 | `known_cost_over_budget` | conflict | 已知住宿金额（下界）> 全程预算 | offer.total 或 base+tax+fee、request.budget | 530-538 | 否 | soft |
| 32 | `estimated_cost_over_budget` | unknown | 已知住宿 + 路段票价估算 > 全程预算 | 同上 + route.fare | 539-547 | 否 | soft |
| 33 | `hotel_stay_skipped` | unknown | 某住宿段没有 stay 且 `request.lodging_skipped`（用户点了「先不选酒店」） | trip_segments、stays_of | 568-581 | stay 路径 | 未登记 |
| 34 | `hotel_stay_missing` | conflict | 某住宿段没有 stay 且未跳过 | 同上 | 568-581 | stay 路径 | 未登记 |
| 35 | `hotel_stay_scope` | conflict | stay 日期不匹配任何住宿段/互相重叠；或报价证据对该段不适用；或报价内部条件不一致 | HotelStay、证据 conditions | 591-612 | stay 路径 | hard |
| 36 | `hotel_over_nightly_budget` | unknown | 住宿预算按「每间每晚」、非不限、同币种，且 offer.total > 该段总额上限 | offer.total、lodging_budget | 620-645 | stay 路径 | soft |
| 37 | `hotel_over_budget_unaccepted` | unknown | `nightly_price(offer) > nightly_upper(request)`；文案含超出额与百分比（用户 2026-10-19 决定：超预算只提示不阻止） | `domain/hotel_recovery.py:37-55` | 648-673 | 否 | soft |
| 38 | `hotel_source` | unknown | 酒店证据 status=unknown | EvidenceRecord.status | 681-684 | 否 | hard（只会 unknown） |
| 39 | `currency` | conflict | offer.currency ≠ request.currency | — | 701-702 | 否 | hard |
| 40 | `hotel_total` | unknown / verified | offer.total 为空（缺税费，known 取下界）→unknown；有含税总价→verified | HotelOffer.total | 703-712 | 否 | soft |
| 41 | `free_text_constraints` | unknown | `request.hard_constraints` 非空 | request.hard_constraints | 85-93 | 否 | soft |

统计【读】：只会 conflict 13 个；只会 unknown 21 个；只会 verified 2 个（`route_live`、`lodging_budget_within`）；混合 5 个。能产出 verified 的总共 5 个 code（`trip_dates`、`opening_hours`、`route_live`、`lodging_budget_within`、`hotel_total`）。

「stay 路径」= `request.segments or proposal.hotel_stays` 为真时走 `stay_costs()`（`validator.py:501-503,557-617`）；否则走单酒店 `hotel_cost()`。

### A3 不是 check 的硬拒绝（整次校验失败）【读】

`validator.py` 抛 `ValueError`，`services/planning.py:177-206` 转 422：条件版本已变（L61-62）；行程证据集合不符或有证据不适用（L63-66）；place 引用不是 place 证据（L71-72）、实体不一致（L74-75）；route 引用不是 route 证据（L409-410、L515-516）；酒店引用不是 hotel_offer（L679-680）、报价与证据不一致（L686-687）、报价条件不一致 `HOTEL_CONDITIONS_REASON`（L691-698，stay 路径下降级为 `hotel_stay_scope` conflict）、报价过期 `HOTEL_EXPIRED_REASON`（L699-700）。

### A4 `backend/domain/repair.py` 自动修什么（339 行）【读】

- 入口 `repair(content, report, facts, *, validate, reroute) -> Repair(content, report, disclosed)`（L280-335）。只接受「硬冲突数严格下降且没有新增冲突种类」的改动（L317-319）；指纹防环（L338-339）；尝试上限 `min(MAX_OPS=12, 3×冲突数)`（L22、L291）。
- 算子按顺序 `OPERATORS = (clamp, shifts, pushes, moves, drops)`（L231）：

| 算子 | 针对的 code | 动作 | 限制 | 行号 |
|---|---|---|---|---|
| `clamp` | `visit_duration`、`visit_duration_range` | 把时长夹进类别区间（只改 end） | 锁定项不动；类别无区间不动 | 82-99 |
| `shifts` | `opening_hours` | 同一天内、不越过相邻项，按 15 分钟步长（07:00–21:00）平移到最近的营业窗口 | 锁定项不动 | 102-133 |
| `pushes` | `route_gap` | 本项及其后同日各项整体后推缺口（向上取整到 5 分钟） | 尾部有锁定项或推过 23:00 则放弃 | 136-164 |
| `moves` | `opening_hours` | 挪到相邻旅行日末尾（该日最后一项结束 +30 分钟，或 09:00），须营业且 ≤21:00；清掉路线引用 | 锁定项不动 | 167-202 |
| `drops` | `repeated_place_warning` 的后一次；其次任何 subject 为 `item:N`/`route:..->N` 的冲突项里最靠后的 | 直接去掉该项 | 不删某天仅剩的一项、不删锁定项 | 205-228 |

- `settle()`（L238-277）：`route_unexpected`→清掉路线引用；`route_scope`/`route_departure`（`STALE`，L21）及被改动项缺失的路线→调用 `reroute` 重新估算（受 `live.usage.run_caps["routes"]` 余额限制，`services/plans.py:128-158`）。
- 不会被修的：subject 不是 item/route 的冲突——`hotel_stay_missing`、`hotel_stay_scope`、`currency`、`known_cost_over_budget`、`lodging_budget_conflict`。`trip_dates`/`city`/`overlap`/`departure_time` 没有专门算子，只可能被 `drops` 删项消掉。
- 不新增景点、不改日期范围；所有改动写进 `Repair.disclosed`→`PlanDraft.repairs`（`domain/plans.py:153`），`summary()` 提示模型「回复里必须逐条写明」（L161-162）。

### A5 校验在哪里被调用【读】

| 调用点 | 位置 | 计入修复轮次 | 说明 |
|---|---|---|---|
| 工具 `validate_itinerary` | `tools/travel.py:826-839` → `PlanningService.validate`（`services/planning.py:145-149`） | 是 | 可选诊断；返回 `feedback()` + `repair_rounds_remaining` |
| 工具 `stage_plan_change` | `tools/travel.py:752-779` → `PlanService.stage`（`services/plans.py:79-98`）→ `_stage`（L164-293，校验在 L254） | 是（见下） | 首次校验有冲突→不落库→`_repair`（L100-162）→再 `_stage(fixed)` 落库，**带冲突也暂存** |
| 服务端修复内部 | `services/plans.py:131-135`（每个候选一次） | 否 | `repair()` 的试算 |
| 幂等重放 | `services/plans.py:207` | 否 | 同参数重复暂存时重校验 |
| 展示草稿 `present_travel_result(itinerary)` / 自动展示 | `services/plans.py:393-399`（`get_draft`）；自动展示 `tools/execution.py:317-334` | 否 | 展示前重校验 |
| 用户确认保存 | `services/plans.py:323-327` | 否 | conflict→409 不能保存 |

### A6 修复轮次上限怎么工作【读】

- 额度：`Limits.max_validations = 4`（`backend/profile.py:24`），DEFAULT/RELAXED/HUMAN 三档都是 4 = 首次校验 + 3 轮修复。评测变体 `no_repairs` 设为 1（`worker.py:165-166`）。构造上限 `MAX_VALIDATIONS_CAP=50`（`tools/travel.py:357`）。
- 计数器在 `TravelToolExecutor`（每个用户轮次新建一个，`database_tools.py:81-85`）：`self.validations`、`self.last_validation`、`self.best`（冲突最少的已校验候选）（`tools/travel.py:408-411`）。
- `_take_validation(proposal, staging)`（`tools/travel.py:919-940`）：
  1. 暂存的正是刚用 `validate_itinerary` 校验过的同一份→不计数；
  2. 暂存且额度已用完（`repairs_exhausted`，L906-913）→不计数、不拒绝；并且初次暂存会被替换成 `self.best`（L753-759）；
  3. 否则额度已满→抛 429 `blocked`，reason=`repair_limit`，文案指示「立即 stage_plan_change 暂存…尚未加载时先 load_skill repair-limit」；
  4. 否则 `validations += 1`。
- `repair_limit` 不终止本轮运行（`tools/travel.py:519`）。每次校验/暂存结果带 TRACE 标签 `repair_round:N`、`max_validations:M`（L536-542）——**只进 TRACE 日志，不进 `RuntimeEvent`**。
- 模型可见文案随档位替换：`with_repair_rounds()`（`tools/contracts.py:22-35`）作用于 `validate_itinerary` 描述、skill 文本；prompt 用 `travel_prompt(repair_rounds)`（`persona.py:80-83`）。
- 服务端确定性修复（A4）与上述模型可见轮次是两套独立额度。

### A7 校验时已经有、但没被检查的数据【读】

| 数据 | 现状 | 校验器能否读到 |
|---|---|---|
| **天气** | `get_weather_forecast`（`tools/travel.py:726-737`）→ `adapters/open_meteo.py:46-137`。返回 `{status, days:[{date, description, high, low, rain_probability}], source_ref, retrieved_at}`。**不产生 Evidence、`evidence_ids` 为空**；结果只缓存在表 `weather_forecasts`（主键 city 小写 + start_date + end_date，payload JSONB，3 小时内复用；`persistence/models.py:82-88`）。离线模式直接返回 `unavailable`（L730-731）；超过今天+15 天或日期未定返回 `status=unknown`（`open_meteo.py:50-53`）。**多城市只按 `request.city`（=首段城市）查一个点、覆盖全程日期**（L734-736） | **不能**。要用需在 `validate_proposal` 里按 (city, start, end) 读 `WeatherForecastRow` 传入，或新增 Evidence 种类 |
| **地点 indoor** | `Place.indoor: bool \| None`（`catalog.py:37`）。夹具 `data/fixtures/kyoto.json` 20 个景点 8 True/12 False【跑】；OSM 导入取 `indoor` 标签（`data/import_catalog.py:103`）；**Google 实时地点不设置 indoor（恒为 None）**（`adapters/google_maps.py:101-113`）。**实时模式下 `search_places` 不把 `indoor`/`category` 参数传给 Google**（`services/catalog.py:54-56`），参数被静默忽略 | 能读到字段，但 live 下恒为 None |
| **地点 category** | `Place.category: str`；Google 经 `place_category()`（`catalog.py:154-161`）从 types 取；38 个景点类 + 24 个非景点类 | 能；已用于节奏/时长，可用来派生室内/室外【推】 |
| **坐标** | `Place.latitude/longitude`；酒店坐标只在 live 的 `display_details`（`hotel_details.py:10-15`） | place 能；酒店坐标在证据侧列，校验器目前不取 |
| **上一版草稿** | 每次暂存一行 `plan_drafts`（payload=完整 `PlanDraft`，含 content、changes、validation、repairs、base_version）；每个正式版本一行 `plan_versions`。`differences(before, after)`（`domain/plans.py:246-269`）已能按 `item_id` 算 add/update/remove/移动，但只对「上一正式版本」算（`services/plans.py:260`）。**首次暂存每次都新生成 item_id**（`initial_content`，L183-188），保存前的多份初稿之间无法按 item_id 对比，只能按 place 证据/place_id 匹配【读+推】；保存后的 patch 保持 item_id | **不能**（签名里没有 previous）。`PlanDraft.changes`/`hotel_changed` 在 `_stage` 里已算好，可在服务层加规则 |
| **抵达/离开时刻** | 没有类型字段。只以文本存在 `hard_constraints`：卡片写 `第一天抵达：…`/`最后一天离开：…`；模型按 prompt 第 7、32 段写自由文本（如「11号早上9点抵达」）。`request.departure_time` 是「每日开始游玩时刻」，不是抵达 | 文本可读，**未解析、未检查** |
| **起床/晚上结束** | `soft_constraints` 文本 `平时起床：…`、`晚上结束：…` | 未检查 |
| **儿童年龄** | `request.child_ages: tuple[int(0–17), …] \| None`（`travel_request.py:108`）。用途仅：酒店证据条件、夹具容量过滤（`hotels.py:139`）、乐天「儿童计价未知」使总价为空（`rakuten.py:318-326`）、路线票价人数 | 能读到，**没有任何规则用它** |
| **兴趣** | `request.interests`（≤20 条文本） | 未检查 |
| **同行** | `soft_constraints` `同行：…` | 未检查 |
| **房型偏好 vs 所选酒店** | `room_assessment()`（`domain/room_preferences.py:19-40`）只用正则识别宿舍/舱房/资格限定，用于搜索过滤与排序；禁烟靠乐天查询参数 `squeezeCondition=kinen`（`rakuten.py:182-183`）；**床型没有任何匹配逻辑** | 校验器不检查所选报价的房型 |
| **用户记忆** | 仅交通默认值经 `transport_default` 传入 | 其余不传 |

### A8 hard_constraints / soft_constraints 怎么存、哪些有固定模式【读】

- 类型：`tuple[Text, …]`，每条 1–200 字、各最多 20 条（`travel_request.py:36,124-126`）。存表 `travel_requests.conditions`（JSONB，`persistence/models.py:164-171`；写入 `persistence/travel.py:38-71`）。
- 写入路径：`update_travel_request`（模型；含 `room_preferences` 枚举投影、`remove_hard_constraints`，`travel_request.py:234-276`）；合并选择卡 `trip_ask_patch`（`domain/choices.py:556-609`）；节奏卡 `pace_patch`（L211-222）；通用表单 `form_patch`（L299-350）。
- 可用代码解析的固定模式：

| 文本模式 | 存放 | 取值 | 写入方 | 现有解析函数 |
|---|---|---|---|---|
| `节奏：{标准\|慢节奏\|特种兵}`（别名：正常/标准节奏/轻松/佛系/悠闲） | hard（卡片写 hard 并从 soft 删除） | `PACE_ALIASES`（`travel_request.py:412-421`） | 卡片/表单/模型 | `pace_of()`（L424-430） |
| `住宿：{独立房间\|接受宿舍\|接受舱房\|无要求}` | hard | `ROOM_CHOICES`（`domain/room_choices.py:8-12`）+ 16 个别名（L14-31） | `room_preferences` 枚举 / 卡片 | `recognized_room_choices()`（L80-81） |
| `房型：{禁烟\|无要求}` | hard | 同上 | 同上 | 同上 |
| `床型：{双床\|大床\|无要求}` | hard | 同上 | 同上 | 同上 |
| `第一天抵达：{9:00 前\|中午 12:00 左右\|下午 15:00 左右\|傍晚 18:00 左右\|晚上 21:00 左右\|自由文本≤40字}` | hard | `TRIP_ASK_SPECS["arrival"]`（`choices.py:403-415`）、`PREFIXES`（L464-470） | 卡片；模型按 prompt 第 12 段同前缀写 | 只有「是否已有」判断 `_timed()`（L481-485）、`shown_times()`（L245-253），**不解析成时刻** |
| `最后一天离开：{中午前\|15:00 左右\|18:00 左右\|晚上 21:00 左右\|自由文本}` | hard | `TRIP_ASK_SPECS["departure"]`（L416-427） | 同上 | 同上 |
| `平时起床：{6:30 左右\|7:30 左右\|8:30 左右\|9:30 左右\|10:30 以后\|自由文本}` | soft | L378-390 | 卡片/模型/长期记忆 `wake_time` | 无 |
| `晚上结束：{19:00 左右\|21:00 左右\|22:00 左右\|23:00 以后\|自由文本}` | soft | L391-402 | 卡片/模型/长期记忆 `evening_end` | 无 |
| `同行：{一个人\|情侣\|家人\|朋友\|其他\|自由文本}` | soft | L428-440 | 卡片/模型 | 无 |
| `{表单题目}：{选项、选项}` | hard | 模型用 `present_form` 自拟 | 表单 | 无 |
| 其他自由文本（带日期的航班/车次时间、饮食、无障碍等） | hard/soft | 任意 | 模型 | 无 |

- 卡片里选「不确定/无要求」时：节奏、起床、结束、抵达、离开、同行**不写入**；房型三组写入 `…：无要求`；交通选「不确定」写 `transport="transit"`（`choices.py:586-595`）。
- 类型化字段（不在约束文本里）：`transport`、`departure_time`、`child_ages`、`rooms`、`adults`、`budget`、`lodging_budget`、`segments`。

### A9 现有测试【跑：`pytest --collect-only -q -p no:cacheprovider`】

| 文件 | 测试函数 | 收集到的用例数 | 覆盖 |
|---|---|---|---|
| `tests/test_itinerary.py` | 28 | 60 | 营业时间、路线 scope/departure/gap/missing、重复景点、预算、酒店来源、密度、用餐、反馈排序 |
| `tests/test_multi_city_itinerary.py` | 10 | 12 | 多城市城市/住宿段/每晚预算 |
| `tests/test_pacing_rules.py` | 11 | 24 | pace_too_sparse、pace_warning、day_gap、节奏别名 |
| `tests/test_visit_duration_rules.py` | 3 | 22 | 时长区间与极端值 |
| `tests/test_route_guidance.py` | 6 | 6 | 路线反馈文案、TRACE 标签 |
| `tests/test_repair.py` | 15 | 19 | 五个算子、锁定项、有界性 |
| `tests/test_lodging_budget.py` | 5 | 20 | 两预算关系 |
| 合计（校验器 + 修复，单元） | 78 | **163** | |

- 另有集成测试（真实 PostgreSQL，未收集）：`tests/integration/test_planning.py`（5 个函数）、`test_plans.py`（19）、`test_sdk_planning.py`（2）、`test_segment_hotel_selection.py`（8）。
- 明确把「单城市不跑新规则」固定为现状的测试：`test_pacing_rules.py:110 test_legacy_single_city_keeps_soft_only_pace_and_no_new_sparse_checks`、`test_visit_duration_rules.py:62 test_legacy_single_city_extreme_duration_keeps_original_checks`、`test_multi_city_itinerary.py:256 test_single_city_validation_report_matches_the_pre_segment_baseline`。
- 全仓 `def test_` 共 1,367 个【跑 grep 计数】。

### A10 具体缺口（每条附所需数据）

| # | 缺口 | 证据 | 需要的数据 / 改动点 |
|---|---|---|---|
| G1 | 自由文本硬条件一刀切 unknown，规范文本也被盖住 | `validator.py:85-93` | A8 表中的前缀解析；逐条出 check，只对剩余自由文本报 unknown |
| G2 | 首日抵达、末日离开时刻没有规则（首日首项应晚于抵达；末日末项应早于离开并留缓冲，prompt 第 22 段写「飞机至少提前2小时」） | 无对应 code | `第一天抵达：/最后一天离开：` 的 9 个固定标签可直接映射时刻；自由文本需时间解析；交通工具类型（飞机/新干线）只在自由文本里 |
| G3 | 起床/晚上结束偏好没有规则 | 无对应 code | `平时起床：/晚上结束：` 的 9 个固定标签；长期记忆 `wake_time`/`evening_end` |
| G4 | 天气→室内没有规则 | A7 | ①天气进校验器（读 `weather_forecasts` 或新增证据种类）；②室内判定：live 下 `indoor` 恒 None，需 category→室内映射表；③多城市天气只查首段城市；④>16 天为 unknown；⑤评测合成数据不提供天气（`evaluation_faults.py:210-211` 对未知主机返回 `{"routes": []}`），需要合成天气夹具 |
| G5 | **单城市行程不跑 `pace_too_sparse`、`day_gap`、`visit_duration_range`**；且单城市的 `pace_warning` 只认 soft 里的 `节奏：`（`validator.py:119-126`），而卡片把节奏写进 hard ⇒ 单城市选了节奏也按「节奏未确认、上限 5」处理 | `validator.py:119-129,278`；`choices.py:211-222,591-593` | 无需新数据；v3 题的用户话里「京都」出现 21 次、「大阪」3 次，多城市题只有 1 道【跑】⇒ 现有题库几乎全是单城市 |
| G6 | 儿童年龄不参与任何规则 | A7 | `request.child_ages` 已有；规则阈值需产品定义 |
| G7 | 房型偏好（禁烟/床型/独立房间）不与所选报价核对 | A7 | `HotelOffer.room_type`（房型名字符串）；需床型/禁烟关键词正则（如 ツイン/ダブル/禁煙）【推】 |
| G8 | 没有「改动范围」规则（只换一处、未要求的项不变） | `results-2026-10-20.md:56-60` 记录的人工改判正是此类 | `PlanDraft.changes`、`plan_drafts` 历史；初稿间需按 place 匹配 |
| G9 | 「每天最后一项回酒店」只在 prompt 第 32 段，无校验 | 无对应 code | 酒店坐标（仅 live 的 `display_details.latitude/longitude`）、place 坐标 |
| G10 | 兴趣覆盖不检查 | A7 | `request.interests` + `place.category` |
| G11 | 费用：门票/餐饮无数据源，`other_costs` 恒 unknown，报告永远到不了 complete | `validator.py:480-487` | 需要门票数据源或把该项从「阻止 complete」里拿掉 |
| G12 | 日程边界（最早/最晚时刻）没有校验规则；07:00–21:00/23:00 只是修复算子的常量，特种兵 09:00–20:30 只在 prompt | `repair.py:24`；`persona.py:57` | 无需新数据 |
| G13 | 每日通勤总时长、单段步行上限、转场日跨城交通没有规则 | 无对应 code | `RouteEstimate.minutes/transport` 已有 |
| G14 | 评测分级表漏登记 7 个 code：`visit_duration_range`、`lodging_budget_×4`、`hotel_stay_missing`、`hotel_stay_skipped`；`tests/test_eval_v3_score.py:72-90` 的正则抓不到多行条件状态/拼接/条件表达式写法的 code，所以测试没有报红 | 【跑】对比 `VALIDATOR_TIER`（34 个）与校验器（41 个） | 改 `eval/v3_tiers.py`；`ValidatorCheck.known_code`（`v3_cases.py:126-130`）也因此不接受这 7 个 code |
| G15 | 评测指标 `repair_rounds` 只数 `validate_itinerary` 工具调用（`eval/v3_score.py:133-152`），模型实际走 `stage_plan_change` ⇒ 最终 90 次 trial 全为 0【跑】 | 同左 | `repair_round:N` 目前只在 TRACE；需进 `RuntimeEvent` 或按 `stage_plan_change` 次数统计 |
| G16 | 营业时间只支持固定时段语法；最终 90 次 trial 的草稿里 `opening_hours` 74 verified / 29 unknown【跑】 | `opening_hours.py:31-56` | Google `regularOpeningHours` 的节假日/特殊时段 |

---

## B. 酒店报价

### B1 数据模型与每个报价可用的属性【读】

- 夹具费率 `HotelRate`（`domain/hotels.py:25-41`）→ `quote()`（L129-167）→ `HotelOffer(QuoteFields)`（L44-126）。实时由 `adapters/rakuten.py:370-415` 直接构造 `HotelOffer`。报价整体存进 `evidence.payload.value`；展示细节 `StoredHotelDetails`（`domain/hotel_details.py:10-31`）存 `evidence.display_details` / `evidence.hotel_metadata` 两个侧列（`persistence/travel.py:94-121`）。

| 属性 | 字段 | 夹具（离线） | 实时乐天 | 评测合成 |
|---|---|---|---|---|
| 标识 | `offer_id`(uuid)、`rate_id`、`hotel_id`、`hotel_name` | 有 | 有（`rate_id=rakuten:{hotelNo}:{planId}:{roomClass}`） | 有（合成评测酒店1–3） |
| 房型 | `room_type`（名称字符串） | 双床房 / 家庭房 | 乐天 roomName | `禁煙ツイン個室` |
| 价格 | `base_amount`、`tax_amount`、`fee_amount`、`included_total`、`total`(派生)、`total_reason`、`currency` | base/tax/fee 分列；2 条故意缺税或费 | 只有逐晚核算的含税 `included_total`；儿童/超过 7 晚/成人不能均分到房时为空（`rakuten.py:318-326`） | 按故障场景 8,000–50,000 |
| 评分 | `review_average` | 无 | 有 | 无 |
| 评价数 | `display_details.review_count` | 无 | 有 | 无 |
| 位置 | `display_details.address`、`latitude`、`longitude` | 无 | 有 | 固定 35/135 |
| **距离** | — | **无字段** | **无字段**（查询固定为地理编码中心 3 km：`rakuten.py:187`） | 无 |
| 早餐 | `breakfast: bool\|None` | 有 | 来自 `withBreakfastFlag` | 无 |
| 取消/退款 | `refundable: bool\|None` | 有 | **恒为 None**（`rakuten.py:391`） | 无 |
| 容量 | `HotelRate.max_guests_per_room`（不进 offer） | 有 | 无 | 无 |
| 图片/链接 | `image_url`、`booking_url`、`hotel_info_url`、`plan_list_url`、`reservation_url`、`more_url` | 无 | 有 | 无 |
| 时效 | `quoted_at`、`expires_at` | 5 分钟（`hotels.py:166`） | `evidence_ttl_minutes`：default 15 / human 30（`profile.py:23,47`） | 同实时 |
| 搜索诊断 | `display_details.search_diagnostics`（`HotelSearchDiagnostics`，`hotel_recovery.py:16-34`）、`search_total_found`、`price_basis` | 有诊断 | 有 | 有 |
| 卡片派生 | `budget_excess`、`budget_excess_percent`（`services/hotels.py:425-432`）、`lodging_exceeds_trip_budget`、`lodging_exceeds_lodging_budget`（`hotels.py:117-124`）、`room_tags`、`qualification_unknown`、`room_preference_mismatch` | 有 | 有 | 有 |
| 星级 / 设施 / 取消政策明细 / **合作方 / 佣金** | — | 无 | 无 | 无 |

- 卡片组装：`HotelOffer.card()`（`hotels.py:91-126`）用 `model_dump(exclude={"request"})` 把 **QuoteFields 的全部字段**输出给模型和前端；`cards()`（`services/hotels.py:389-422`）再并入展示细节与房型评估。给模型的 `offers` 仅去掉 `stay`、`request_revision`、`image_url`（`tools/travel.py:1060`）。
- 比较结论 `compare()`（`hotels.py:170-206`）：只在入住条件/币种一致且都有含税总价时给出 `lowest_offer_ids`。

### B2 数据规模【跑】

- `data/fixtures/hotels.json`：**12 条费率 = 6 家酒店 × 2 房型，全部京都（1 个城市）**。字段 13 个：`rate_id, hotel_id, hotel_name, room_type, max_guests_per_room, base_per_room_night, tax_per_room_night, fee_per_room_night, weekend_surcharge, breakfast, refundable, available_from, available_until`。基础价 6,500–15,000 日元/间夜，按 hotel_id 递增；双床房（2 人、无早餐、不可退）/ 家庭房（4 人、含早、可退）；周末加价统一 1,500；`kyoto-5-rate-1` 缺税、`kyoto-6-rate-1` 缺服务费。
- 评测合成（`adapters/evaluation_faults.py:160-196`）：每次查询固定返回 3 家「合成评测酒店N」；合成城市只认京都/大阪/奈良（L38-42）；合成景点每城 12 个、类别全是 museum（L49-67）。
- 实时：任意日本城市（地理编码 + 乐天 `VacantHotelSearch`，每页 30 条，半径 3 km）。代码内城市别名规范值 15 个（`travel_request.py:433-462`）；攻略快照 14 个城市（`data/snapshots/`）。

### B3 展示顺序怎么定【读】

1. **实时**（`rakuten.py:239-467`）：乐天 `sort="standard"`（上游默认序）→ `lowest_per_hotel()` 每家取资格合格且价格可信的最低价套餐，酒店保持上游顺序（L483-506）→ **有住宿预算上限时按首晚每间价格升序**（L309-315），没有上限时直接取前 `limit` 家（L316-317）→ `evaluate()`（`hotel_recovery.py:58-141`）：预算内的排前、超预算的排后；预算内为 0 时用 `sort="+roomCharge"` 重查一次（L417-455），仍为 0 则按 1.5/2/3 倍档取最便宜的 3 家并发预算放宽卡。
2. **夹具**（`services/hotels.py:234-309`）：文件顺序 → `room_order()`（资格未知/房型不符的稳定排后，`room_preferences.py:43-50`）→ 有预算上限时每家取最低价再 `evaluate()`；否则 `hotel_rate_indices()`（`domain/hotel_selection.py:8-29`：先覆盖不同酒店，再每家最多 2 套餐，总数 ≤6，保持上游顺序）。
3. 工具结果超长时 `bounded_offers()` 从尾部裁掉整张卡（`tools/travel.py:1063-1083`）。
4. **页面最终顺序 = 模型传给 `present_travel_result` 的 `offer_ids` 顺序**（`services/hotels.py:337-363`：`known_quotes` 与 `resolve_evidence` 都按传入 id 顺序），之后只过一遍稳定的 `room_order()`。服务端在展示时不重排；前端 `apps/web/src/components/results.tsx` 未发现对酒店卡排序【跑 grep】。
5. 文字约束：prompt 第 28 段「价格最低的在前」、`hotel-comparison` skill「按价格升序」；回复文字要求「每家只写名称、房型和总价」（第 42 段）。
6. 结论：现有排序信号只有上游序、价格、预算内外、房型资格；**评分、评价数、位置都没有进入排序**。

### B4 合作方/佣金属性与计算分数的自然挂载点【读+推】

| 目的 | 位置 | 说明 |
|---|---|---|
| 夹具酒店带合作方/佣金 | `HotelRate`（`hotels.py:25-41`）+ `data/fixtures/hotels.json` | `extra="forbid"`，加字段必须同步改模型；`load_rates()`（`providers/hotel_fixture.py:13-18`）对整个文件算 sha256 作为 `content_version` |
| 报价对象携带 | `QuoteFields`/`HotelOffer`（`hotels.py:44-71`） | **注意**：`card()` 会把 QuoteFields 所有字段输出给模型和页面；佣金若不想外泄，需像 `display_details` 那样 `exclude=True`，或不进 offer |
| 只在服务端保存、不进报价契约 | `StoredHotelDetails`（`hotel_details.py:25-31`）→ `evidence.display_details` 侧列 | 现有「搜索整体信息不进卡片」的先例：`SEARCH_FIELDS`（`services/hotels.py:366`）在组卡时被排除 |
| 实时酒店的合作方信息 | 乐天响应里没有；需按 `hotel_id`（乐天 hotelNo）查服务端对照表，在 `HotelService._quote`（`services/hotels.py:211-233`）构造证据时并入 | 【推】 |
| 分数的纯函数 | 新增 `backend/domain/` 模块，与 `evaluate()`（`hotel_recovery.py:58`）同层 | 输入可用：`nightly_price`、`nightly_upper`、`review_average`、`review_count`、坐标、`breakfast`、`refundable`、房型评估 |
| 分数影响候选顺序 | `HotelService._quote`（取 `limit` 之前）与 `HotelService.present`（`services/hotels.py:337-363`，目前跟随模型给的 id 顺序） | 要让服务端决定顺序，需在 `present` 里重排 |
| 评测侧读取 | 证据表 `evidence`（kind=hotel_offer）+ `request_details.hotel_flow.picks` + `run_events` 的酒店比较展示 | 见 B5 |

- 改契约的连带：`data/contracts/web-openapi.json`、`apps/web/src/lib/api-types.ts`（卡片字段类型）会随 schema 变化【推】。
- 相关单元测试：`tests/test_hotels.py`（13 例）、`tests/test_hotel_recovery.py`（10 例）、`tests/test_hotel_selection.py`（5 例）【跑】。

### B5 哪些用户动作被持久化（可作「历史数据」）【读】

| 动作 | 表 / 字段 | 内容 | 局限 |
|---|---|---|---|
| 查到的全部报价 | `evidence`（kind=`hotel_offer`；`payload`=EvidenceRecord，`display_details`、`hotel_metadata`、`invalidated`） | 每次搜索的每个报价一行，含完整价格与入住条件 | 条件变化只置 `invalidated`，不删 |
| 展示给用户的候选及顺序 | `run_events.payload`（kind=`presentation`，`data.component="hotel_comparison"`，`cards` 按展示顺序）——`event_metadata()` 对酒店比较卡整份保留（`domain/execution.py:269-323`） | 展示集合、位次、当时的 `budget_excess` | 需要按 run 解析 JSON |
| 用户选中的酒店 | `travel_requests.request_details.hotel_flow.picks[入住日] = {check_out, evidence_id, source: button\|chat\|assign_confirm}`（`domain/hotel_flow.py:15-27`；写入 `services/hotel_selection.py:61-90`、`services/runs.py:286-294`）；同轮规范引用 `request_details.selected_hotels` | 每个住宿段当前选择 | **只保留最新一次，覆盖写，没有时间戳和位次**；时间可从对应 `task_runs.created_at` 推 |
| 用户选「先不选酒店」 | `request_details.hotel_flow.skipped` | 负样本 | 同上 |
| 预算放宽卡接受/保持、其他卡片 | `choice_cards`（`kind`、`content`、`answered_option_id`、`answered_run_id`；`models.py:222-237`） | 用户对放宽预算的决定 | — |
| 草稿 | `plan_drafts`（每次暂存一行；`confirmed_version`） | 完整草稿 + 校验报告 + repairs | 草稿 10 分钟过期但行保留 |
| 确认保存行程 | `plan_versions`（不可变，`payload`=SavedPlan 含 `hotel_stays`）、`plans.current_version` | 「计划确认」 | — |
| 模拟暂留/下单 | `bookings`（`payload.status` ∈ quoted/held/confirmed/booked/failed/unknown/expired + `history`；`domain/booking.py:12-14,61-79`）、`supplier_holds`、`supplier_orders` | 「预订」漏斗 | **仅离线夹具**：实时模式 `hold_hotel` 被禁用并从工具表移除（`tools/travel.py:320,739-745`） |
| 每轮用户原话与回复 | `task_runs`（`user_text`、`prompt`、`answer`、`status`、`mode`） | — | — |
| 乐天链接点击 | **没有记录**（API 路由里无点击/跳转上报端点，`backend/api/app.py`）【跑 grep】 | — | 实时模式下「是否真的去预订」不可观测 |

- 实时模式可观测的最强转化信号 = 酒店被选中（picks）与行程被确认保存；没有真实下单。
- 评测库是每次运行临时建、结束即清（`eval/v3_run.py:898-900`），**历史 trial 的数据库状态不留存**；留存的只有 `.cache/eval-v3/<run>/trials.jsonl`（每 trial 的 flags/metrics/checks/tools/judge/每轮回复前 2000 字）与 `transcripts/`。trial 行里**没有**酒店卡明细和所选酒店【跑：行内键列表】。

---

## C. 评测 v3

### C1 文件与职责【读】

| 文件 | 行数 | 职责 |
|---|---|---|
| `eval/v3_cases.py` | 391 | 题目 schema（pydantic，`extra="forbid"`）与加载 |
| `eval/v3_user.py` | 452 | 脚本化用户 `ScriptRunner` |
| `eval/v3_run.py` | 945 | 入口、trial 循环、终态采集、断点续跑 |
| `eval/v3_score.py` | 514 | 确定性评分 `score_trial` |
| `eval/v3_tiers.py` | 50 | 校验 code 的 hard/soft 分级表 |
| `eval/v3_report.py` | 220 | summary.json / report.md / scatter.csv |
| `eval/v3_judge.py` | 446 | rubric 评审、人工校准表、一致率 |
| `eval/claims.py` | 209 | 回复文字与服务端事实对账（虚假声明） |

### C2 题目 schema（`V3Case`，`v3_cases.py:304-370`）【读】

- 顶层：`case_id`、`category`（7 类，L33-35）、`title`、`setup`（预置 request）、`fault`（9 种，`adapters/evaluation_faults.py:16-26`）、`patience_s`、`ttfua_s`、`user_script`（1–12 步）、`fallback{policy: stop|idk|facts, max_extra_turns}`、`user_facts`、`hard_checks`、`soft_checks`、`required_tools`、`forbidden_tools`（默认 `["hold_hotel"]`）、`memory{l1,l2,l3,l4}`、`rubric`（3–5 条）、`notes`。
- `user_script` 动作（`Step`，L77-109）：`say` / `card{kind, option, answers, if_missing}` / `hotel_pick{rank: first|last|cheapest|0–9, segment}` / `new_session` / `switch_user` / `confirm_plan`。卡种类 6 种：trip_ask、form、pace、budget_relaxation、memory_confirm、hotel_assign（L36-47）。
- 检查类型 6 种（L117-258）：

| type | 断言对象 | 备注 |
|---|---|---|
| `validator` | 最后一份草稿里某 code 的状态 | 只接受 `VALIDATOR_TIER` 里的 34 个 code；全 verified 才 pass |
| `state` | 终态子集比对（request / saved_version / hotel_stays / bookings / memory） | `request.pace` 为派生键 |
| `db` | 9 种断言：hotel_selected、draft_exists、draft_no_conflict、draft_min_places、plan_saved、no_plan_saved、no_new_orders、memory_active、memory_absent | |
| `reply` | 某轮回复正则 matches / not_matches | |
| `card` | 某轮发出的卡种类、含/不含某题 | |
| `turn_tool` | 某轮调用过/没调用某工具 | 只看工具名 |

- 现有 30 题的实际用法【跑】：硬检查 77 条（db 63、state 7、reply 4、turn_tool 3）；软检查 23 条（全是 reply）；**validator 类型检查 0 条**；rubric 每题 3 条共 90 条；`required_tools` 出现：search_hotel_offers 12、stage_plan_change 3、search_places 1；**没有任何题要求或断言 `load_skill`**；`fallback` 全部缺省（=stop）⇒ 没有题会触发 LLM 用户；`patience_s`/`ttfua_s` 全部未设；带 `fault` 6 题、带 `setup` 9 题、带 `memory` 规格 4 题。
- 脚本步数分布：1 步 15 题、2 步 5 题、3 步 3 题、4 步 4 题、5 步 2 题、6 步 1 题。动作合计：say 41、card 16（trip_ask 10、memory_confirm 5、budget_relaxation 1）、hotel_pick 4、new_session 3、confirm_plan 1、switch_user 1。
- 生成草稿的题只有 3 道（main-single-city-full-save、main-multi-city-hotels-draft、mid-replace-one-spot）；多城市题 1 道。用户话里出现的城市：京都 21 次、大阪 3 次，其余 0。

### C3 成功怎么算（`score_trial`，`v3_score.py:390-480`）【读】

`success = hard_pass ∧ ¬false_claim ∧ tool_ok ∧ memory_ok ∧ ¬abandoned ∧ ¬empty_reply ∧ step_ok ∧ infra_error is None`（L442-451）

- `hard_pass`：题目显式硬检查全部 pass（unknown 算不过）；**自动把最后一份草稿的每条校验结果纳入**，其中 6 个 hard code（trip_dates、hotel_stay_scope、currency、place_source、hotel_source、city）出现 conflict 即失败（L398-404）。
- `soft_score`：软检查（显式 + 自动 soft 校验项）按权重的通过比例；不进 success。
- `false_claim`：`eval/claims.py` 用正则找「在预算内 / 已选酒店 / 已记住 / 已订好」等断言，与当轮服务端事实 `ClaimFacts` 对账；不一致即失败，无法判断记 unknown。
- `tool_ok`：必需工具都调用过、禁止工具没调用、没有未注册工具名、没有 blocked 的 run。
- `memory_ok`：声明了的 L1 提取 / L2 落库 / L3 进 prompt / L4 行为全过。
- 等待时间只记录；rubric 评审不进 success。
- 失败只取一个原因，优先级：infra_error > abandoned > blocked_or_hallucinated_tool > false_claim > empty_reply > hard:\<id\> > step_unavailable > tool > memory（L483-514）。

### C4 报告打印的指标（`v3_report.py:77-201`）【读】

trial 数与 repeat；success 率；pass^1、pass^3；Success@T（60/120/180 秒，按最慢一轮，仅参考）；失败原因 × 类别表；总耗时 p50/p95（nearest-rank）；TTFUA p50/p95；成本（CNY）合计与每 trial；输入缓存命中率；声明 unknown 次数；rubric 逐项 yes/no/unknown 与 yes 率、按题 yes 率、措辞翻转率。`scatter.csv` 列：case_id, category, trial, success, total_s, max_turn_s, ttfua_s, soft_score, judge_yes_rate, cost_cny, reason。每 trial 另推 Langfuse 数值分（`finish_trial`，`v3_run.py:621-651`）。

### C5 离线夹具模式 vs live 模式【读】

| | 离线（默认） | `--live` |
|---|---|---|
| 运行时 | `OfflineRuntime(FixtureRuntime)`（`v3_run.py:95-105`），无模型，按关键词触发固定工具 | `V3Runtime(GuardedRuntime)`（L108-146），DeepSeek（`mode="deepseek"`，`v3_user.py:378`） |
| 数据 | 夹具酒店/景点/路线 | `fault` 为空→真实乐天/Google/Open-Meteo；`fault` 非空→合成数据（两者互斥，L122-123） |
| 评审 | 关 | 默认开（同一 DeepSeek 结构化调用，`--no-judge` 关闭；`--judge-check` 再用改写措辞评一遍） |
| L3 来源 | 服务层快照 | 实际 prompt 快照文件（需专用评测库 `travel_agent_eval_<hex>`） |
| 意义 | 「只证明设施」：两次离线全量成功率 12/30、11/30【跑】 | 成绩来源 |
| 成本 | 0 | 账本前后差值，含评审调用（L565、L608-611） |

- 命令：`uv run python scripts/dev.py eval-v3 [--live] [--trace-cloud] [--repeat 1..3] [--case-id …] [--cases 文件] [--profile human|default|relaxed] [--max-cny N] [--resume RUN_DIR] [--no-judge] [--judge-check]`（`v3_run.py:666-700`）。默认 profile=human（不限工具次数、run 超时 900 秒）。一次运行共用一个临时库，每个 trial 新建用户和会话。
- **v3 入口没有 `--variant`**，消融变体不能在 v3 上跑（见 C8）。

### C6 脚本化用户 vs LLM 模拟器【读】

| | v3 `ScriptRunner`（`eval/v3_user.py:150-452`） | `eval/simulator.py`（690 行） |
|---|---|---|
| 用户行为来源 | 题目里写死的步骤 | LLM 扮演（`structured_call("simulator")`，提示词 `SIMULATOR_RUBRIC`，`persona.py:149-164`），依据隐藏目标表决定下一动作 |
| 选酒店 | 确定性：最近一次酒店比较展示里按 first/last/cheapest/下标（`choose_card`，L95-110） | LLM 输出 `hotels` 动作 |
| 点卡片 | 指定 option；表单默认取卡上预选值再被脚本答案覆盖（L117-147） | LLM 输出 `choice` 动作 |
| LLM 出场 | 仅 `fallback.policy="facts"` 时（现有 30 题为 0） | 每个用户动作一次 |
| 规模 | 30 题，每题 1–6 步 | 8 个场景（L101-146），每 trial 最多 8 个用户动作（L290），默认重复 3 次 |
| 数据 | 真实 API 或合成 | 合成故障数据（`Scenario.fault` 默认 `coverage`） |
| 人设 | 无 | 一句「简短耐心的旅行用户」（L377） |
| 步骤走不下去 | 记 `step_unavailable`，trial 失败 | LLM 自行决定 |

### C7 已有运行产物的汇总数字（`.cache/eval-v3/`，只取聚合）【跑】

目录下 11 次运行 + `analysis-2026-10-20.md`。全部发生在 2026-10-19/20，git sha 为 af40646 / 5baa3ba / 998b3f9 / eae76b3 / 7cccb41 / 36281fc——**都早于 `cb203d0`（skill 拆分，10-26）、只读工具并发、prompt 缓存重排、异步记忆抽取**；当时只有 2 个 skill，工具表里还有 `propose_memory`。HEAD 之后没有任何 live 运行产物；所有 trial 行的 `cache` 字段为空。

| 运行 | 模式 | 题×重复 | trial | 成功 | 成功率 | 平均秒 | p50 / p95 秒（summary.json，nearest-rank） | 成本合计 / 每 trial（CNY） |
|---|---|---|---|---|---|---|---|---|
| 20261019T151812Z | 离线 | 3×1 | 3 | 1 | 33% | 0.1 | 0.09 / 0.10 | 0 |
| 20261019T153640Z | 离线 | 3×1 | 3 | 1 | 33% | 0.1 | 0.09 / 0.10 | 0 |
| 20261019T230503Z | live | 3×1 | 3 | 3 | 100% | 14.3 | 13.3 / 22.2 | 0.336 / 0.112 |
| 20261020T012419Z | 离线 | 30×1 | 30 | 12 | 40% | 0.1 | 0.09 / 0.16 | 0 |
| 20261020T014723Z | 离线 | 30×1 | 30 | 11 | 37% | 0.1 | 0.10 / 0.18 | 0 |
| 20261020T022051Z | live | 3×1 | 3 | 2 | 67% | 20.9 | 20.0 / 31.4 | 0.461 / 0.154 |
| 20261020T022345Z | live | 1×1 | 1 | 1 | 100% | 65.1 | 65.1 / 65.1 | 0.652 / 0.652 |
| **20261020T022655Z（首轮全量）** | live | 30×3 | 90 | 76 | **84.4%**（pass^3 80%） | 27.7 | 19.2 / 76.7 | 21.334 / 0.237 |
| 20261020T035404Z | live | 6×3 | 18 | 14 | 77.8% | 37.8 | 27.9 / 91.8 | 6.935 / 0.385 |
| 20261020T040808Z | live | 3×3 | 9 | 9 | 100% | 40.0 | 41.6 / 44.4 | 3.853 / 0.428 |
| 20261020T072434Z | live | 3×3 | 9 | 8 | 88.9% | 87.4 | 84.3 / 112.8 | 10.212 / 1.135 |

**文档采用的最终 90 次（按 `docs/proposals/eval-redesign/results-2026-10-20.md:36-41` 的规则从 4 次 live 运行拼接：首轮未改动的 22 题 66 次 + 三次重跑的 8 题 24 次）**，我按同一规则重新聚合【跑】：

| 指标 | 数值 |
|---|---|
| trial 数 / 题数 | 90 / 30 |
| 代码判定成功 | 89/90（98.9%）；文档经 1 处人工改判后采用 **87/90（96.7%）**，pass^3 28/30（93.3%） |
| 每 trial 总耗时 | 平均 28.6 秒；中位 20.8 秒（nearest-rank p50 = 20.4）；**p95 = 84.3 秒**；最小 9.7、最大 112.8 |
| 最慢一轮耗时 | 平均 11.8 秒；p50 8.1；p95 44.9；最大 55.8 |
| TTFUA（首个展示事件） | 平均 9.3 秒；p50 5.8；p95 39.9 |
| 成本（CNY） | 合计 23.23；**平均 0.258 / trial**；中位 0.145；最大 1.607。四次 live 运行总花费 42.33（与文档一致） |
| 每 trial 轮数 / 工具调用 | 平均 1.99 轮（最多 5）；工具调用平均 4.1、p95 17、最多 34 |
| judge yes 率 / soft_score | 0.913（86 个有评审的 trial）/ 0.914（72 个有软项的 trial） |

按类别（最终 90 次）：

| 类别 | n | 成功（代码判定） | 平均秒 | p95 秒 | 平均成本 CNY |
|---|---|---|---|---|---|
| main_flow | 12 | 11 | 54.9 | 92.8 | 0.604 |
| mid_change | 15 | 15 | 49.5 | 112.8 | 0.596 |
| memory | 18 | 18 | 22.5 | 36.6 | 0.135 |
| ambiguous | 15 | 15 | 20.1 | 33.9 | 0.142 |
| fault | 15 | 15 | 17.9 | 21.3 | 0.124 |
| out_of_scope | 9 | 9 | 13.1 | 14.2 | 0.040 |
| adversarial | 6 | 6 | 13.1 | 13.4 | 0.041 |

- 口径注意：`total_s` 是整个多轮 trial 的墙钟时间，**含评审调用**（`v3_run.py:404,453`）；成本币种 CNY，是预算账本记账值（`budget.totals()`，按 `limits.py:59-70` 的价表上界 `usage_upper` 计：deepseek-flash 输入 2 / 输出 8 元每百万 token），缓存折扣未对账，不等于供应商实付。
- 最终 90 次里出现过各工具的 trial 数：search_hotel_offers 43、update_conversation_state 49、present_travel_result 32、update_travel_request 28、search_places 12、propose_memory 12、stage_plan_change 9、estimate_routes 9、get_weather_forecast 8、validate_itinerary 2、select_hotel_from_chat 2、get_saved_plan 2、**load_skill 2**、get_place_facts 1。
- 最终 90 次里 9 份草稿的自动校验项计数：trip_dates pass 103；opening_hours pass 74 / unknown 29；route_fare unknown 66；route_duration unknown 60；route_missing unknown 11；hotel_total pass 12；other_costs、lodging_budget_unknown、budget_missing、free_text_constraints 各 unknown 9；meal_time unknown 6；route_live pass 4；visit_duration_range unknown 3；route_source unknown 2；pace_warning unknown 1。没有任何 conflict。

### C8 消融变体（`backend/providers/claude_agent/evaluation.py`）【读】

| 变体 | 效果 | 实现位置 |
|---|---|---|
| `full`（B3） | 全功能 | — |
| `no_tools`（B0） | 不给任何工具，prompt 追加「没有工具或外部事实」 | `evaluation.py:48-49`；`worker.py:146-156` |
| `no_skills` | 工具表去掉 `load_skill`，其余不变 | `evaluation.py:51` |
| `no_preferences` | 每轮状态不带长期偏好/记忆/画像 | `worker.py:167`；`database_tools.py:149-153` |
| `no_repairs` | `max_validations = 1` | `worker.py:165-166` |
| `no_compaction` | 关闭 SDK 自动压缩 | `worker.py:191` |
| `baseline_b2`（B2） | 同时关压缩和偏好（组合基线，不是单因素） | 同上 |

- 运行方式：`uv run python -m eval.run --database --live --variant <名> [--suite legacy|frozen|v2|v2-memory] [--split dev|test] [--repeat 1..3]`（`eval/run.py:551-575`）。限制：必须 `--database --live`；不能与 `--workflow`、评审混用；**只支持单条 prompt**（`worker.py:105`）。⇒ 只能在旧套件（单轮题）上跑，**不能在 v3 多轮题上跑**。
- 历史结果【跑：`.cache/verification-sweep-20261004.json`，frozen 40 test × 3 = 120 条，commit fa9930b，当时 2 个 skill】：full 97/120；no_tools 18/120；baseline_b2 103/120；fixed_itinerary 38/120（34 条 error）；**no_skills 101/120**（不低于 full）；no_preferences / no_repairs / no_compaction 未跑完（状态 `user_paused_for_completion_audit`）。各组约束 `complete` 都是 0（见 A1）。`docs/guides/evaluation.md:31` 另记一批较早结果 full 94/120、B0 17/120。

### C9 旧套件（`eval/cases/`，`eval/cases/README.md`）【读+跑】

| 文件 | 条数 | 状态与用途 |
|---|---|---|
| `datamind_adapted.jsonl` | 21 | 历史 legacy：DataMind 改编的单轮首答题（需求理解、选工具、超范围） |
| `travel_m1.jsonl` | 9 | 历史 legacy：业务 dev 题；与上面合成 legacy-30，是 `eval/run.py` 默认套件 |
| `frozen_v1.jsonl` + `frozen_v1.json` | 60（20 dev + 40 test） | 冻结集，sha256 校验，test 不用于调优；消融对照在它上面跑 |
| `v2_interaction.jsonl` | 8 | v2 交互/故障恢复机制开发集（未冻结） |
| `v2_memory.jsonl` | 20 | v2 确认记忆开发集（抽取、trip、否定、第三人、更新、投毒） |
| `v3.jsonl` | 30 | 现行多轮题库 |
| `simulator.py` 内置场景 | 8 | LLM 模拟用户场景（不在 cases 目录） |

### C10 `eval/business_metrics.py` 今天测什么（131 行）【读】

- 只服务旧套件（`eval.cases.Case`），不接入 v3。三项：
  1. `constraint`：本轮最新草稿的校验状态（not_applicable / unavailable / no_candidate / complete / partial / conflict）+ verified/unknown/conflict 计数；汇总出候选覆盖率、`hard_constraint_pass_rate`（只有 complete 算过）、无冲突率。
  2. `booking`：模拟暂留是否正确（correct/incorrect/unavailable），范围是暂留、unknown 保留、预期供应商故障、无新增订单。
  3. `recovery`：恒为 `unmeasured`。
- **与收入、佣金、转化、推荐质量无关**；名字里的 business 指「业务分项观测」。

---

## D. Skills

### D1 `load_skill` 怎么工作【读】

- 定义：`ToolDefinition("load_skill", "按白名单加载业务步骤；文本不授予额外工具权限。", SkillInput…)`（`tools/travel.py:187-191`），描述 23 字，**不含任何 skill 的用途或触发条件**；模型能看到的 skill 目录只有 schema 里的 6 个名字枚举（L70-79）和 prompt 第 33 段的 4 条触发。
- 执行（`tools/travel.py:879-896`）：同一执行器内已加载过→返回 `{name, already_loaded: true}`；否则读 `backend/tools/skills/<name>.md`，过 `with_repair_rounds()` 替换修复轮数，记入 `self.loaded_skills`，返回 `{name, version, instructions}`，其中 **`version = sha256(渲染后全文)` 的 64 位十六进制**。
- `self.loaded_skills` 是内存集合，随 `TravelToolExecutor` 每个用户轮次重建（`database_tools.py:81-85`），执行器不记得上一轮加载过什么，也不落库。live 真实数据下不续接 SDK 会话（`worker.py:185-187,236-239`），上一轮的 skill 文本不在模型上下文里，需要时得重新加载【推】。
- `load_skill` 计入每轮工具调用额度（`_admit`，`tools/travel.py:585`；human 档不限次）。结果不加不可信围栏（`tools/fencing.py:27`）。

### D2 加载时到底记录了什么【读】

| 记录处 | 内容 | 有 skill 名？ | 有哈希？ |
|---|---|---|---|
| 工具结果（只给模型） | `name`、`version`、`instructions` | 有 | 有 |
| `RuntimeEvent` tool_started（`tools/execution.py:124-133`） | `tool_name="load_skill"`、`argument_keys=("name",)`、`arguments=ToolArgumentFacts()` | **无**——`argument_facts()`（`domain/tool_facts.py:48-65`）只为 memory_extractor / present_travel_result / search_hotel_offers 提取封闭参数 | 无 |
| `RuntimeEvent` tool_finished（L165-189） | code、result_empty、无 evidence | 无 | 无 |
| 表 `run_events` | 同上两条事件 | 无 | 无 |
| TRACE 日志（`tools/execution.py:137,144-157`） | name、call_index、elapsed_ms、`result_chars`、code | 无（`result_chars` 只能间接区分） | 无 |
| OTel / Langfuse span（`adapters/tracing.py:382-442`） | `tool.name`、`tool.argument_keys`、状态 | 无 | 无 |
| v3 trial 行 | `tools.started`（工具名集合）、`metrics.tool_calls` | 无 | 无 |
| rubric 评审输入（`eval/v3_judge.py:68-87`） | 每个工具调用的名称与状态 | 无 | 无 |
| `eval/run.py:540` manifest | 静态的 skill 名单 | 名单，不是使用记录 | 无 |

- 结论：**评估器今天只能数「某轮调用了几次 load_skill」，不知道加载的是哪个 skill，也拿不到内容哈希。**
- 最小改动点【推】：在 `ToolArgumentFacts`（`tool_facts.py:23-29`）加一个封闭枚举字段（skill 名）并在 `argument_facts()` 里填充，它会自动流到 `RuntimeEvent.arguments`→`run_events`→v3 `TurnObs.events`。哈希要进事件则需在 tool_finished 上加字段。
- 「本该加载」的 4 个触发信号**已经在事件里**【读】：`request.segments` 非空（终态快照 / `<server_state>`）；`tool_finished.relaxation_cause`、`relaxation_tier`、`choice_card ∈ {shown, declined}`；`tool_finished.external`（attempts、provisional、kind）；`tool_finished.reason == "repair_limit"`（`domain/execution.py:208-233`）。所以这 4 个 skill 的命中率分母可以从事件确定性算出。
- 现有测试只断言文本位置：`tests/test_persona.py:162-172`（4 个触发名出现在 prompt、枚举里有）；live 是否按触发加载**从未验证**（`docs/plans/2026-10-26-commerce-agent-optimizations.md:73`）。历史数据里 load_skill 只在 2/90 个 trial 出现（当时只有 2 个无触发条件的 skill）。

### D3 六个 skill 文件【跑：字符数/哈希；读：内容】

| 文件（`backend/tools/skills/`） | 主题 | 字符 | 字节 | sha256 前 12 位（原文） | prompt 里有触发条件？ |
|---|---|---|---|---|---|
| `hotel-comparison.md` | 酒店比较口径（同条件含税总价）、超预算只提示、展示后等用户选、预算放宽卡解释、两预算层级关系 | 943 | 2,555 | fea32da54e20 | **无**（prompt 中出现 0 次） |
| `itinerary-revision.md` | 已有正式行程的局部改动：定位 item_id、保留未改项与锁定项、暂存看差异 | 322 | 728 | b72ff7a860a1 | **无**（prompt 中出现 0 次） |
| `multi-city.md` | 多城市写 segments、分段查酒店带 segment_arrive、hotel_stays、转场日 | 365 | 745 | 6d691082d195 | 有：「用户涉及两个以上城市或 request.segments 非空」 |
| `budget-relaxation.md` | relaxation 诊断怎么讲、放宽卡 accept/keep、declined 之后不能再提、无候选的替代方向 | 853 | 2,083 | f4ae8ea8b191 | 有：「relaxation 非空、choice_card 为 shown/declined 或出现 budget_relaxation 卡，或酒店无候选」 |
| `external-errors.md` | 外部失败怎么说、provisional 只修参一次、attempts/auto_retried 口径 | 259 | 663 | 638bbbebb76f | 有：「external 显示失败、重试或 provisional=true」 |
| `repair-limit.md` | 修复额度用完后直接暂存并展示、如实写明 repairs 与剩余冲突 | 321 | 719 | 0e8457028c27 | 有：「校验/暂存提示修复次数用完」；`tools/travel.py:937` 的报错文案也提示加载 |
| 合计 | | 3,063 | | | 4 / 6 |

（`README.md` 96 字符，是说明不是 skill。注意返回给模型的 `version` 是替换修复轮数**之后**文本的哈希；default 档位下与原文相同。）

### D4 系统提示词的组成与大小【跑+读】

`system = travel_prompt(repair_rounds) + DatabaseTools.guidance()`（`worker.py:173`）；每轮业务状态不在 system 里，而是 `<server_state>` 块前置到用户消息（`database_tools.py:43-54`）。

| 组成 | 来源 | 字符 |
|---|---|---|
| 角色规格 | `backend/agent/persona.md` 全文（含一段 JSON 规则：≤600 字、≤8 句、≤3 个选项、禁用词） | 523 |
| 分隔 | `"\n\n"` | 2 |
| 业务规则 | `persona.py:36-78` 字面量，43 个非空段落 | 9,042 |
| **`travel_prompt()` 合计** | | **9,567**（UTF-8 21,989 字节） |
| 工具次数规则 | `DatabaseTools.guidance()`（`database_tools.py:156-172`） | 167（human）/ 203（default、relaxed） |
| **system 合计** | | **9,734（human）/ 9,770（default）** |
| 固定流程附加（仅评测 `--workflow`） | `tools/workflow.py:27-33` | — |

- 对比：18 个工具定义（live 17 个，去掉 hold_hotel）的描述合计 2,647 字符，JSON schema 合计 21,743 字符——**工具 schema 是 system 的两倍多**；其中 `update_travel_request` schema 5,781、`stage_plan_change` 5,095。
- 历史：cb203d0 前业务字面量 11,035 → cb203d0 后 9,563 → HEAD 9,042【跑】。

### D5 `travel_prompt` 逐段盘点【跑：字符数；读+推：分类】

段号 Pnn 对应 `persona.py` 源码行 L(35+nn)。分类：**核心**=几乎每轮都需要；**主流程**=规划/酒店主链每次都用但对闲聊、只比酒店等轮次无用；**低频**=特定场景才用。

| 段 | 行 | 字符 | 内容 | 分类 | 可迁往的 skill（建议名） |
|---|---|---|---|---|---|
| P01 | 36 | 41 | 身份、data_mode | 核心 | — |
| P02 | 37 | 47 | 海外目的地 | 核心（短） | — |
| P03 | 38 | 39 | 非旅行业务、情绪 | 核心（短） | — |
| P04 | 39 | 47 | 缺信息先问 | 核心 | — |
| P05 | 40 | 63 | search_places / search_content 选择 | 核心 | — |
| P06 | 41 | 114 | 每轮记录明确条件 | 核心 | — |
| P07 | 42 | 254 | departure_time 语义 vs 抵达/返程/航班时间 | 低频（用户提到时刻才用）；与字段描述 `travel_request.py:116-123` 重复 | `trip-times` |
| P08 | 43 | 165 | 手填表单值优先、explicit_fields、skipped_fields | 低频 | `manual-form-precedence` |
| P09 | 44 | 61 | 两预算冲突先问 | 低频；与 hotel-comparison skill 末段重复 | `lodging-budget` |
| P10 | 45 | 254 | 房型用 room_preferences 枚举写入 | 低频（卡片已覆盖）；与工具描述重复 | `room-preferences` |
| P11 | 46 | 524 | 省级目的地要 hotel_search_location（约 190 字）+ 房型记录规范文本（约 330 字） | 低频 | `broad-destination` + `room-preferences` |
| P12 | 47 | 1,310 | 问清流程：写入已说条件、合并卡、提交后的假设；present_form、旧卡重发、文字确认等边角 | 主流程（约 900 字）+ 低频边角（约 400 字） | 边角部分 → `trip-ask-edge-cases` |
| P13 | 48 | 58 | 摘要够用就不读详情 | 核心 | — |
| P14 | 49 | 45 | 查询关键词 | 核心 | — |
| P15 | 50 | 40 | 只按资料回答并引用 | 核心 | — |
| P16 | 51 | 52 | synthetic 标注 | 护栏（非生产数据） | — |
| P17 | 52 | 143 | fixture/snapshot/live 标注、不可信文本 | 护栏 | — |
| P18 | 53 | 47 | 只有注册工具 | 护栏 | — |
| P19 | 54 | 49 | 部分不能执行时说明边界 | 核心 | — |
| P20 | 55 | 83 | 不暴露内部 ID | 护栏 | — |
| P21 | 56 | 58 | 只记明确字段（与 P06 重复） | 核心 | — |
| P22 | 57 | 346 | 节奏定义、每日时段、规划顺序、**天气/室内一句**、实时酒店不暂留 | 主流程（仅行程规划） | `itinerary-planning` |
| P23 | 58 | 312 | 全程景点去重与重复冲突的修法 | 主流程（仅行程规划）；服务端已有 `repeated_place_warning` + `drops` | `itinerary-planning` |
| P24 | 59 | 135 | 记录 goals | 核心 | — |
| P25 | 60 | 220 | awaiting_field、短答 | 核心 | — |
| P26 | 61 | 464 | ready_tasks（约 130 字）+ 住宿预算怎么问怎么写、晚数算法（约 330 字） | 核心 + 低频 | 后半 → `lodging-budget` |
| P27 | 62 | 286 | 搜索与路线批量、并发查询 | 主流程（仅行程规划） | `itinerary-planning` |
| P28 | 63 | 635 | 宽松规则、绝不自动选酒店（约 300 字）；`select_hotel_from_chat` 各返回状态处理（约 250 字）；一家都没找到（约 85 字） | 主流程 + 低频 | 中段 → `chat-hotel-selection`；末段并入 `budget-relaxation` |
| P29 | 64 | 172 | 酒店先展示、预留调用额度 | 主流程 | — |
| P30 | 65 | 145 | 恢复时先展示 pending_draft | 低频 | `resume-draft` |
| P31 | 66 | 91 | 搜索行自带 evidence_id | 主流程（仅行程规划） | `itinerary-planning` |
| P32 | 67 | 856 | 暂存/自动展示/残余冲突、用餐留白、换酒店只改酒店 patch、每天回酒店、note 写法、抵达返程写入硬条件 | 主流程（仅行程规划）；「页面换酒店」约 110 字为低频 | `itinerary-planning`；换酒店 → `itinerary-revision` |
| P33 | 68 | 272 | skill 触发索引 | 必留 | — |
| P34 | 69 | 389 | 初始规划先逐段查酒店、展示全部、等选择 | 主流程 | — |
| P35 | 70 | 246 | 多城市校验密度、visit_duration_range 含义 | **低频（仅多城市）** | 并入现有 `multi-city` |
| P36 | 71 | 63 | 酒店卡组件 | 主流程（酒店） | 并入 `hotel-comparison` |
| P37 | 72 | 51 | 参数只含 schema 字段 | 核心 | — |
| P38 | 73 | 146 | 没有记忆工具、不能宣称已记住 | 低频（用户说「记住」时） | `memory-preferences` |
| P39 | 74 | 93 | 「这次而已」语义 | 低频 | `memory-preferences` |
| P40 | 75 | 295 | 四项可长期偏好、其余只对本次 | 半低频（已确认偏好的用法每次规划都相关） | `memory-preferences` |
| P41 | 76 | 63 | 展示前校验、最多 3 轮 | 主流程（仅行程规划） | `itinerary-planning` |
| P42 | 77 | 141 | 酒店比较回复要简短 | 主流程（酒店） | 并入 `hotel-comparison` |
| P43 | 78 | 84 | 不出现内部字段名 | 护栏 | — |

汇总【跑：按上表加总；分类为推断】：

| 去向 | 涉及段落 | 约字符 |
|---|---|---|
| 新 skill `itinerary-planning` | P22、P23、P27、P31、P32（去掉换酒店）、P41 | 约 1,840 |
| 并入现有 `multi-city` | P35 | 246 |
| 并入现有 `hotel-comparison`（并给它触发条件） | P36、P42 | 204 |
| 并入现有 `itinerary-revision`（并给它触发条件） | P32 的换酒店部分 | 约 110 |
| 并入现有 `budget-relaxation` | P28 末段 | 约 85 |
| 新 skill `room-preferences` | P10、P11 后半 | 约 580 |
| 新 skill `memory-preferences` | P38、P39、P40 | 534 |
| 新 skill `lodging-budget` | P09、P26 后半 | 约 390 |
| 新 skill `chat-hotel-selection` | P28 中段 | 约 250 |
| 新 skill `trip-times` | P07 | 254 |
| 新 skill `broad-destination` | P11 前半 | 约 190 |
| 新 skill `manual-form-precedence` | P08 | 165 |
| 新 skill `resume-draft` | P30 | 145 |
| 新 skill `trip-ask-edge-cases` | P12 边角 | 约 400 |
| **可迁出合计** | | **约 5,400 / 9,042（约 60%）**；其中纯低频约 3,300，其余是「仅行程规划」的主流程块 |

- 频率旁证【跑，最终 90 次 trial】：生成草稿的 trial 9 个（10%）；调用 search_hotel_offers 的 43 个（48%）；select_hotel_from_chat 2 个；多城市题 1 道（3 个 trial）。即 `itinerary-planning` 那 1,840 字在九成对话里用不到。

### D6 产品已处理、但没有成文指引的业务场景【读+推】

| 场景 | 现状 | 证据 |
|---|---|---|
| 雨天/天气应对（换室内、调顺序、>16 天未知、多城市各城天气） | prompt 一句话 | `persona.py:57`；A7 |
| 带儿童出行（节奏、适龄景点、晚间时间；乐天有儿童时总价为空、无法比价） | 只有「child_ages=[] 代表无儿童」 | `rakuten.py:318-326`；v3 有 1 道题 main-family-child5-hotels |
| 住超过 7 晚（乐天不核算总价） | 无指引 | `rakuten.py:321-322` |
| 成人数不能均分到房间（总价为空） | 无指引 | `rakuten.py:323-325` |
| 按评分/评价数/位置推荐酒店、解释为什么推荐 | skill 只讲价格口径 | 字段存在（B1），无文字 |
| 首日抵达日/末日离开日怎么排 | P22 一句话 | — |
| 转场日跨城交通 | multi-city skill 一句话 | — |
| 报价过期/证据失效后的刷新 | 只有报错文案里的补救提示 | `services/travel.py:735-740` |
| 锁定项不可改、解锁流程 | 只有工具报错 | `domain/plans.py:215-216` |
| 当日往返（0 晚） | 仅「0 晚不问住宿预算」 | P26 |
| 交通方式取舍（步行/公交/打车） | 无 | — |
| 饮食、无障碍等自由文本硬条件 | 无（统一 unknown） | A8 |
| 用餐安排 | 「只留时间，不搜索餐厅」一句 | P32 |
| 攻略问答 | P05、P13–P15 短句 | — |
| 模拟暂留/下单（仅离线） | 只有工具描述 | `tools/travel.py:239-245` |
| 合作酒店/商业推荐话术与披露 | **完全没有** | 第 0 节 |

- 业务 skill 的现实数量估计【推】：现有 6 个 + 从 prompt 可迁出的新 skill 10 个（D5 汇总表里标「新 skill」的行）+ 上表无指引场景里值得单独成文的约 5–7 个（天气应对、带儿童、酒店推荐理由、抵离日、长住/特殊人数、商业推荐披露）⇒ **约 21–23 个**。

---

## E. 仓库里保留的方法参考

### E1 `docs/guides/reuse.md`「项目长期方法约定（2026-10-21）」（L5-49）【读】

- 两篇来源：Anthropic《The anatomy of effective commerce agents》与《Writing effective tools for agents》；阅读核对日期 2026-10-21。只采用方法，不复制原文、上游代码或收益数字。
- **服务端约束**：「模型提出方案，服务端检查身份、证据、版本和限额；展示按已核验 ID 补齐数据。保存与模拟下单经真实确认入口。外部文字按不可信材料处理。」并注明：强制发卡、酒店选择与本地修复是本项目自己的实现，不是文章原样提供（L22）。
- **评测**：用真实任务、初始状态和正反例构造可核验终态；允许不同解题路径；保留故障、状态变化与跨会话场景；读实际对话、工具结果和 trace 定位失败；调整工具描述/schema/返回内容后做回归；**调优集与留出集分开，当前无留出集的结果不能讲成泛化能力**（L26）。
- **Skills / 上下文**：一个主 Agent + 按需业务 Skill；常用规则与低频步骤分开；稳定提示与每轮变化的业务快照分开（L18）。
- **指标口径（固定检查 5–7）**：说明样本、分母、规则、统计单位、版本；任务成功率、稳定通过率、相关性、事实准确性、judge 体验分分开讲；耗时说明是模型 HTTP、单轮、首展示还是整个 trial、是否含评审、分位算法；成本区分账本记账与实付；部分重跑/拼接/人工改判必须披露；**文章里的效果、缓存命中率或收入收益不能成为本项目指标**（L34-36）。
- **商业排序**：这一节没有任何关于商业排序、佣金、合作方的内容。全 `docs/`（guides/design/plans/proposals/adr/review）grep「商业排序、佣金、收入、转化率、ranking、sponsor、merchandis」无命中【跑】。

### E2 仓库里对两篇文章的其他笔记【读】

- `docs/plans/2026-10-26-commerce-agent-optimizations.md`（83 行）：逐条对照 commerce agents 文章的调查表（L9-16）与 5 项改动：prompt 缓存重排、只读工具并发、**低频规则拆成 skill（cb203d0）**、live eval workflow、异步记忆抽取。明确「高风险操作由后端控制：已对齐，未改」。明确不做（用户决定）：扩充评测数据、工具结果字段白名单裁剪、页面上下文注入、记忆第二/三层读取（L18）。**未做 live 验证**的项里包括「skill 是否按触发条件加载」（L73）。剩余风险第 4 条：`load_skill` 计入工具额度，`no_skills` 消融的含义随之变大（L80）。
- `docs/guides/reuse.md:77-79`：官方材料结论——单主 Agent 按需读取 Skills；安全约束由代码执行层落实；工具模式表达展示卡片再由服务端校验补齐；文章数字不写进完成证据。
- `docs/proposals/eval-redesign/research-notes.md:11-24`：读的是另两篇 Anthropic 文章（Demystifying evals for AI agents、Building effective agents）：task/trial/grader/outcome 术语；能用代码判就用代码；评产出不评路径；judge 留 Unknown 选项；capability 与 regression 评测分开；pass^k；从 20–50 道来自真实失败的题起步。
- 仓库里没有工具设计文章的独立摘要，只有 reuse.md 的「工具契约」一段（L20）和固定检查第 4 条。

### E3 `docs/design/05-validation.md`（169 行）【读】

- 三层验证：确定性回归（FakeRuntime + 真实测试库 + 故障钩子）/ Agent 任务评测（固定初始状态 + 输入 + 允许的结果）/ 外部接口验证（§1）。模拟用户用来发现问题，转成固定用例才进正式评测（L15）。
- 核心回归矩阵 R01–R19（§2）；与规则层最相关：R05（伪造/过期 Evidence 不用于卡片）、R06（闭馆、预算缺项、跨午夜、路线失败：**conflict 与 unknown 分开，不悄悄放宽硬条件**）、R07（局部替换、同一地点去两次、锁定项：item_id 稳定、无关项不变）。
- 用例规模目标：M0 21 条 → M1 30 条 → 最终约 60 条（20 dev + 40 test 冻结）（§3）。「60 条只能支持对照结论，不写显著提升 X%」（L92）。每个「应拒绝/应追问」的用例配一个正常对照。
- 指标定义（L78-88）：任务完成率、工具调用准确率、事实准确率/覆盖率、**约束通过率（unknown 与 conflict 分开统计）**、预订正确率、恢复完成率、成本与延迟（P50/P95）、质量评分、角色语气。评分顺序：先规则断言，再 LLM 评审；解析失败单列 `judge_error`。
- 基线 B0–B3 与单因素对照（§4）：每次只关一项——Skills 按需加载、上下文压缩、长期偏好、validator 反思循环。
- 门禁（§7）：只用 dev 调优；test 冻结后跑 3 次报波动；每次结果绑定 commit、数据版本、prompt/skill/schema 版本、SDK/CLI 版本、模型、币种与价格。
- 这份设计文档没有收入、佣金、商业排序相关的指标。

### E4 v3 评测的设计意图（`docs/proposals/eval-redesign/`）【读】

- `README.md`（v0.4）：目标是用约 30 题 × 3 次回答「同一模型同一系统能否稳定、及时、诚实地做完一份日本行程并记住该记的偏好」（§0）。成功由代码与数据库终态判定，judge 只给体验分，校准达标（两位真人、一致率 ≥80%）后才可进入成功判定（§0、§3.2）——**真人校准尚未完成**。
- 五个维度（§3）：结果正确（进）、等待时间（v0.3 起只记录）、工具与恢复（进）、记忆四层（进）、用户体验 rubric（先不进）；外加横向的虚假声明检查。
- 约束分级（§4）：硬约束 = 日期、城市、人数/房间、用户明确的房间要求、数据必须来自工具；软约束 = 景点不重复、营业时间已核实、酒店在预算内、节奏、路线。**「软约束没满足又没告诉用户→按虚假声明处理」的检测器在暂缓清单里**（§9）。实现上只加了一张 code→级别映射表（`eval/v3_tiers.py`）。
- 出题原则（§5.1；`question-generation-spec.md` §2）：每题一个明确边界情况、可客观判定；用户按脚本、信息分轮给；正反例都要；真实 API 题只断言性质不断言具体酒店/价格/景点；**不出依赖具体天气的断言**；日期在 2026-11-01 至 2027-03-31；试跑后剔除全过/全挂的题。合成数据题只能用京都、大阪、奈良。
- 明确不做：比较模型、100% 维度覆盖、IRT 选题、自动失败归因（§0；`research-notes.md` §C）。
- `results-2026-10-20.md` 的使用限定（L62-68）：结果是本系统在自建 30 题上的完成度，无对照组；题按本系统设计编写；模拟用户按脚本；只覆盖日本国内 2026 年 12 月；**测评期间题目被改过，没有留出集**；部分 unknown 来自评测自设配额耗尽。已知待修：`mid-replace-one-spot` 的检查应改为「该轮 stage_plan_change 成功且是基于原草稿的补丁」（L60）。
- `eval/cases/README.md`：v3 为现行题库「持续扩充」；旧套件原地保留，v3 成为默认后再归档。

---

## 附：与五项后续工作直接相关的现状速查

| 后续工作 | 现成可用 | 明确缺失 |
|---|---|---|
| (1) 更多确定性规则 | 41 个 code、纯函数校验器、163 个单元用例、修复算子、A8 的固定文本前缀 | 天气与上一版草稿进不了校验器；live 地点无 indoor；抵达/离开/起床/结束未解析；单城市不跑多城市规则；分级表漏 7 个 code |
| (2) 商业期望分 | 报价的价格、预算超出额、评分、评价数、坐标、早餐；`evaluate()` 是现成的服务端排序点；picks / 确认保存 / 卡片回答可做标签 | 无合作方/佣金字段；无距离字段；夹具酒店无评分与位置；实时无真实下单与点击记录；picks 只留最新且无位次；页面顺序由模型给的 id 顺序决定；评测库不留存、trial 行不含酒店卡 |
| (3) 用历史运行改进 skill | `trials.jsonl`（失败原因、checks、tools、judge、每轮回复）、transcripts、`analysis-2026-10-20.md` | 事件里没有 skill 名与哈希；HEAD 之后无 live 基线；历史运行只有 2 个 skill 的时期 |
| (4) 100–200 题评测集 | schema、加载校验、脚本化用户、6 类检查、9 种故障、断点续跑、题目规范文档；按现有均值粗算 150 题 × 3 次约 116 元、约 3.6 小时串行（0.258 元、28.6 秒 / trial）【推】 | validator 类检查从未使用；无 skill 相关断言；合成数据仅 3 城 3 酒店 12 景点；无留出集；真人校准未做；规划类题只有 3 道 |
| (5) 更多 skill 与命中率 | 白名单加载机制、内容哈希、4 个触发信号已在事件里、`no_skills` 变体 | skill 名不进事件；2 个 skill 无触发条件；`no_skills` 只能在单轮旧套件上跑；load_skill 工具描述不含目录 |
