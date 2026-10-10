# 2026-10-10 多城市行程 · 住宿预算 · 节奏密度批次

记录规则见 [plans/README](README.md)。**本文件是本批次唯一的任务状态入口**。上一批次见 [2026-10-08-product-v2](2026-10-08-product-v2.md)（其 T8.1/P-99/P-100 已提交，512 KiB 请求边界与重复景点硬冲突为本批基线能力）。

## 0. 执行者（Codex）从这里开始

1. 读 [plans/README](README.md) → 本文件 §1–§5 → [docs/execution/standards.md](../execution/standards.md) → ADR-015（住宿预算与条件来源，本批会扩展它）。不要一次读全仓。
2. 分支：`batch/2026-10-10-frontend-restyle`（基线 `0e0bc71`，开工时 `git status` 应干净）。出现非 agent 产生的改动先停下问用户，不 stash/reset（沿用 D8）。
3. 第一件事：把 [AGENTS.md](../../AGENTS.md) 和 [docs/README.md](../README.md) 的“当前批次”链接改到本文件（T0.1）。
4. 每个任务：先写失败测试 → 实现 → 跑项目自己的命令（§9）→ 自审 → commit（消息带任务 ID）→ push → 更新 §4 证据列与 §8 P-条目。
5. §2 的 D 项是本计划给出的推荐默认；**用户未改动前按推荐执行**，执行中发现推荐不可行就在 §8 记录并停下问。
6. 本文件中的代码位置于 2026-10-10 由 Claude 读源码核实（REASONED），执行前如行号漂移，以函数名为准。

## 1. 基本信息

| 项 | 内容 |
| --- | --- |
| 开始日期 | 2026-10-10 |
| 目标 | 一份旅行可以跨多个城市、分段住宿，在“查询→草稿→校验→保存→恢复→展示”全链路成立；同时让住宿预算、节奏密度、停留时长有可执行的规则反馈 |
| done means | §4 每个任务的验收测试先红后绿并已提交；§9 必需检查全部通过且输出已记录；“三城市+两段住宿”与“旧单城市行程”两条路径在真实 PostgreSQL 上完成 草稿→确认保存→重新读取 |
| 范围 | ①多城市+分段住宿 ②每间房每晚住宿预算确认（含“明确不限”）③取消24条上限 ④节奏密度（过多/过少/大片空白）⑤停留时长合理范围 ⑥统一“AI 整理”说明 ⑦全程景点不重复（覆盖多城市与修改） |
| 不做 | 不同晚上不同预算；酒店星级；景点费用查询；跨城车次/票价查询（只给标注为“建议”的文字）；官网营业时间爬虫；不主动问全程预算/酒店总预算/币种；“住在A城、白天去B城”的不换宿 day trip（B城不在城市段里则按城市不一致处理）；新评测体系、新安全框架、大量报告 |
| 分支 | `batch/2026-10-10-frontend-restyle`，基线 `0e0bc71` |
| 执行者 | 实现：Codex；规划审查：Claude；最终判断：本人 |
| 预计 | 约 16–24 小时 Codex 工作量，7 个可运行提交（§9.3） |

## 2. 待用户决定（未改动即按推荐执行）

| ID | 问题 | 推荐（默认执行） | 不决定的影响 |
| --- | --- | --- | --- |
| D1 | 多城市条件放哪里 | `TravelConditions` 新增可选 `segments`，**持久化在 `request_details`**（与 `lodging_budget`、`hotel_search_location` 同一机制，JSONB，无需 alembic 迁移）。`city/start_date/end_date` 保留并由 segments 派生（city=首段城市），旧读取方、历史列表、`legacy_request` 快照不变 | 若新建表/列要写迁移，工期+3–4h |
| D2 | 行程里多个酒店怎么关联 | `PlanContent/ItineraryProposal/PlanPatch` 新增 `hotel_stays: tuple[HotelStay]`（`check_in, check_out, hotel_evidence_id`），保留 `hotel_evidence_id` 只用于单城市旧数据；两者不能同时出现。读取时统一转成 stays 视图 | 直接删 `hotel_evidence_id` 会破坏已保存行程的读取 |
| D3 | “明确不限”怎么存 | 新增 `lodging_budget_unlimited: bool`（与 `lodging_budget` 互斥，存 `request_details`）。三态：未回答（两者皆空）/有金额/明确不限 | 只靠 null 无法区分“没回答”和“不限”，会重复追问 |
| D4 | 住宿预算必须确认的时机 | 只在 `itinerary` 任务且存在 ≥1 晚住宿时进入 `task_missing`（字段名 `lodging_budget`）；`hotel_comparison` 单独查酒店时保持可选，不阻断 | 若酒店比较也强制，会改变上一批已验收的酒店流程 |
| D5 | 规则严重度 | **conflict（阻止确认保存）**：重复景点（已有）、停留时长极端异常（< 下限的一半或 > 上限的两倍）、住宿段重叠/缺口/报价与段不匹配。**unknown（建议性，模型修正但不阻止）**：每日景点过多/过少、大片空白、停留时长轻度偏离、报价超出每晚预算 | 全部 conflict 会让普通行程生成失败；全部 unknown 则模型可能忽略 |
| D6 | 节奏同义词 | 规范值仍为 `节奏：标准/慢节奏/特种兵`；“轻松/佛系/悠闲”统一归入慢节奏，“标准节奏/正常”归入标准。识别只在一个函数里做 | 各模块继续各认各的 |

## 3. 评审与设计

### 3.1 对 Codex 原方案的审查结论

原方案范围判断准确，顺序（数据结构→流程→规则→前端→验证）合理。需要修正/补充的点：

1. **漏了一个会让“>24条”验收失败的隐性上限**：`bounded_plan`（`backend/tools/travel.py:731`）把返回给模型的 `cards` 截到 8 条、`changes` 截到 6 条，并按 8000 字符再缩。页面 API 能看到完整内容，但**模型在修改第 9 条以后的项目时拿不到它们的 `item_id`**。取消 24 条上限后这个问题会被放大，必须给模型一条读取完整 `item_id` 列表的途径（见 T2.2）。
2. **“节奏识别不一致”只部分成立**：validator/conversation/前端都用 `节奏：` 前缀，规范值一致；真正的差异是 conversation.py 同时查 soft+hard，validator 只查 soft，fixture 只认“标准节奏”，persona 把“佛系/轻松”口头映射为慢节奏但代码不认。修法是收敛成一个函数，不是重写。
3. **“当前规则允许住宿预算未知时继续规划”有明确出处**：`backend/agent/persona.py:54`“住宿分项预算null是可选信息……不再索要”。这句必须改，否则新规则与提示词互相打架。
4. **抵达/返程时刻目前只在 `hard_constraints` 自由文本里**，validator 无法机械读取。密度规则只能按“首日/末日/转场日 = 非完整日”放宽下限，不能声称按航班时刻计算；这一点在反馈文案里要诚实。
5. **城市名一致性是多城市的最大隐患**：Google 地点的 `city` 直接取模型传入的搜索城市字符串（`adapters/google_maps.py:101 place_from_response`），validator 用 `request.city != place.city` 精确比较。多城市后“神户/神戸/Kobe/神戸市”任一不一致都会变成 city conflict。需要一个小的 `same_city()` 归一（见 T1.1）。
6. 原方案“证据绑定到对应城市和住宿日期”方向正确，但可以更省：**place/article/route 证据不需要按段绑定**（全局 `city` 由首段派生、规划中不变），只有 hotel_offer 需要按段绑定。城市归属改在 validator 里按天检查。
7. 已有 `LodgingBudget` 支持 `basis: total` 和任意币种（ADR-015）。本批**不删除**这些能力（旧数据兼容），只是提示词只问“每间房每晚、JPY”。

### 3.2 问题核实表（2026-10-10 读源码，REASONED）

| # | 限制 | 位置 | 结论 |
| --- | --- | --- | --- |
| 1 | 单 city / 单 hotel_search_location / 单组日期 | `backend/domain/travel_request.py` `TravelConditions` | 成立 |
| 2 | 单 `hotel_evidence_id` | `domain/plans.py` `PlanContent`、`PlanPatch`；`domain/itinerary.py` `ItineraryProposal`；`services/plans.py:139,276,328` | 成立 |
| 3 | 景点城市必须等于 request.city | `domain/validator.py` `visit_checks`（`request.city != place.city`） | 成立 |
| 4 | 证据按当前全局条件逐字段比较 | `domain/evidence.py` `applicable` + `evidence_conditions`；`hotel_cost` 再比一次 `offer.request` | 成立；hotel_offer 含 city/start/end，route 含 city/start/end |
| 5 | 酒店按全局日期/地点查 | `services/hotels.py` `_quote`（`request.hotel_search_location or request.city`，`rakuten.search(request, …)`） | 成立；adapter 接收 `TravelRequest`，可传入“按段派生的请求副本”而不改 adapter |
| 6 | 24 条上限 | `domain/plans.py:21`(PlanContent)、`:65`(PlanPatch.operations)、`domain/itinerary.py:32`、`services/plans.py:51`(locked_item_ids)；前端仅生成的 `api-types.ts` | 成立；前端无手写 24 |
| 7 | 隐性 8 条截断 | `tools/travel.py:731 bounded_plan`；`ValidationReport.feedback` 只给前 12 条检查 | **原方案未列出，新增** |
| 8 | 节奏识别 | `validator.py:101`、`conversation.py:74`、`fixture_conditions.py:167`、`apps/web/src/lib/pace.ts` | 部分成立（见 3.1-2） |
| 9 | 密度只查过多 | `validator.py sightseeing_checks` | 成立；过少、空白均无 |
| 10 | 停留无合理范围 | `validator.py visit_checks` 只查 `end<=start` | 成立 |
| 11 | 住宿预算可不确认 | `persona.py:54`；`conversation.py task_missing` 无该项 | 成立 |
| 12 | 每项重复“模型概述、非来源核实” | `persona.py:59`；`itinerary.py:25` 字段 description（会进 `api-types.ts`） | 成立 |
| 13 | 草稿 stage 只因重复景点拒绝，其余 conflict 可暂存；confirm 拒绝任何 conflict | `services/plans.py require_unique_sightseeing`、`confirm` | 成立；D5 依赖这一行为 |
| 14 | 持久化都是 JSONB | `persistence/models.py` PlanVersionRow/PlanDraftRow/TravelRequestRow.request_details | 成立 → 新字段无需迁移 |

### 3.3 最小数据结构

```python
# domain/travel_request.py
class TripSegment(BaseModel):          # frozen, extra=forbid
    city: str                          # 1–40
    arrive: date                       # 到达该城市的日期
    depart: date                       # 离开该城市的日期（转场日同时属于前后两段）
    hotel_search_location: str | None = None
    # nights = depart - arrive；nights == 0 表示当日游/末日不住宿

class TravelConditions:
    segments: tuple[TripSegment, ...] | None = Field(default=None, max_length=6)
    lodging_budget_unlimited: bool = False
```

不变量（`TravelConditions` 的 model_validator，结构错误直接拒绝）：
- 至少 2 段才写 `segments`；单城市保持 `None`（旧路径完全不变）。
- `segments[0].arrive == start_date`，`segments[-1].depart == end_date`，`segments[i+1].arrive == segments[i].depart`（连续、无重叠、无缺口）；同一城市可以出现多次。
- 只有最后一段允许 `nights == 0`（例：末日京都一日游后返程）。
- `city` 由服务端写为 `segments[0].city`、日期写为首末；不一致时拒绝。
- `lodging_budget` 与 `lodging_budget_unlimited=True` 互斥。

派生函数（全部放 `travel_request.py`，各处只调用它们，不自行判断）：
- `trip_segments(request) -> tuple[TripSegment, ...]`：`segments is None` 时返回由 `city/start/end/hotel_search_location` 构成的单段。**这是旧数据兼容的唯一入口。**
- `segment_request(request, seg) -> TravelRequest`：`model_copy(update={city, start_date=arrive, end_date=depart, hotel_search_location, segments=None})`，只在内存中用于酒店查询与证据条件，不写回。
- `cities_on(request, day) -> set[str]`：当天覆盖的城市（转场日两个）。
- `pace_of(request) -> Literal["标准","慢节奏","特种兵"] | None`：同时查 soft/hard，含 D6 同义词。
- `same_city(a, b) -> bool`：casefold、去空白、去尾部“市”，加一个仅含本项目已覆盖城市的小别名表（京都/Kyoto、大阪/Osaka、神户/神戸/Kobe、奈良/Nara …）。不做通用地名库。

```python
# domain/plans.py / itinerary.py
class HotelStay(BaseModel):
    check_in: date
    check_out: date
    hotel_evidence_id: UUID

PlanContent / ItineraryProposal:
    hotel_evidence_id: UUID | None = None      # 仅旧单城市
    hotel_stays: tuple[HotelStay, ...] = ()    # 新；与上者互斥
PlanPatch:
    hotel_stays: tuple[HotelStay, ...] | None  # 出现即整体替换（段数≤6，整体替换最简单）
```

`stays_of(content, request)`：旧 `hotel_evidence_id` → 单个 `HotelStay(start_date, end_date, id)`。validator、`content_view`、前端都只读 stays。

### 3.4 证据绑定

| kind | 条件 | 变化 |
| --- | --- | --- |
| place / article | `{city: request.city}` | **不变**（全局 city=首段，规划中稳定）。城市归属改由 validator 按天用 `cities_on` + `same_city` 检查 |
| route | `{city,start,end,transport,departure_time}` | **不变**。转场日跨城路段照常 estimate；查不到的跨城路段保持 `unknown`，不编造 |
| hotel_offer | 全局入住条件 | 按段：`evidence_conditions(segment_request(req, seg), "hotel_offer")`。`applicable()` 对 hotel_offer 判断“与任一有住宿的段匹配”；validator 再要求“与它所在 HotelStay 对应的那一段匹配” |

关键兼容要求：**单城市时 `evidence_conditions` 产出的字典必须与现在字节相同**，已存证据继续有效（T1.1 有专门测试）。
`invalidated_kinds` 增加：`segments` 变化 → `hotel_offer` + `route`。

### 3.5 规则（validator 内，复用 `ValidationCheck`/`feedback`/修复轮次机制）

- **住宿段**（conflict）：存在有住宿的段但没有对应 HotelStay → `hotel_stay_missing`；stay 日期与任何段不吻合或互相重叠 → `hotel_stay_scope`；报价条件与该段不符 → 沿用 `HOTEL_CONDITIONS_REASON`。单城市无酒店仍为现有的 `hotel_missing: unknown`（不收紧旧行为）。
- **每晚预算**（unknown）：报价每间每晚 > 预算上限 → `hotel_over_nightly_budget`，提示换段内更低价报价；不限或未设则不检查。`budget_checks` 的已知住宿成本改为各 stay 求和。
- **城市归属**（conflict）：`place.city` 不属于当天 `cities_on` → 沿用 code `city`，文案带当天允许的城市。
- **节奏密度**（unknown）：范围 慢节奏 2–3 / 标准 4–5 / 特种兵 6–8，按 `SIGHTSEEING_CATEGORIES` 计数（已有）。完整日：少于下限 `pace_too_sparse`、多于上限 `pace_warning`（沿用）。首日/末日/转场日：只查上限，下限放宽为 1。同一天相邻两项之间空档 > 3 小时且不是转场段 → `day_gap`。节奏未确认时只保留现有“密度较高”提醒，不查下限。
- **停留时长**（`visit_duration_range`）：只对 `SIGHTSEEING_CATEGORIES` 生效，酒店/餐饮/交通类跳过。按类别给宽松区间（建议值，写成一张表放 `domain/catalog.py`，执行者可微调）：museum/art_gallery/gallery 45–180；temple/shrine/place_of_worship 系 20–120；castle/heritage/historical_* 45–150；park/garden 30–180；viewpoint/observation_deck/scenic_spot 20–90；zoo/aquarium 90–240；theme_park/amusement_park 180–600；market/shopping_mall 30–180；其他景点类 20–180。偏离 → unknown；< 下限/2 或 > 上限×2 → conflict（D5）。营业时间缺失仍为 unknown，不新增爬虫。
- **重复景点**：保持 place_id 维度全程查重（已覆盖跨天、patch 后的整份内容）；多城市不改逻辑，补测试即可。酒店/餐饮/交通不在 SIGHTSEEING_CATEGORIES，不会被误判。

## 4. 任务表

依赖顺序自上而下。验收中的测试名为建议名，按仓库现有测试文件就近放置。

| ID | 内容 | 依赖 | 涉及模块 | 验收条件 | 状态 | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| T0.1 | 切换当前批次入口；记录基线检查结果 | — | AGENTS.md、docs/README.md | 链接指向本文件；§9 全量命令在基线上跑一遍，结果写进 §7（失败项记为“基线既有”） | done | `33df5fe` 已push；基线check299/三平台、test1408 passed、web119/构建、db Healthy、generate全部通过（§9.1/P-01） |
| T0.2 | 兼容读（回退保护）：读取 `PlanContent/ItineraryProposal/PlanPatch` 与 `request_details` 时能接受新字段（`hotel_stays`、`segments`、`lodging_budget_unlimited`），仅读取不写入；API 写入入口仍按旧契约 | T0.1 | domain/plans.py、domain/itinerary.py、services/travel.py、services/plans.py | ① PG：直接写入含新字段的行程/条件 payload，`get` 正常返回且旧字段不变 ② 现有全量测试通过 ③ 单独提交并 push，Railway 部署成功后再开始 T1.1 | done | `33df5fe` 已push；test1419 passed/1 skipped/4 deselected（305.62s）、check/生成/web119/构建退出0；独立审查通过；Railway API/Web同SHA SUCCESS、旧京都V1 GET200（P-03） |
| T1.1 | 条件模型：`TripSegment`、`segments`、`lodging_budget_unlimited`、派生函数、`same_city`、`pace_of`；`request_details` 读写；`invalidated_kinds` | T0.1 | domain/travel_request.py、services/travel.py(`request_from_row` 及写入处)、ADR-015 追加一节 | ① 段重叠/缺口/首末不符/非末段0晚 → 拒绝（失败路径）② `apply_request_patch` 设置/清除 segments、revision 正确递增 ③ 单城市 `evidence_conditions` 输出与基线字节相同 ④ `pace_of` 覆盖 soft/hard 与同义词 ⑤ PG：写入 segments 后重新读取一致 | done | `03701b1` 已push；先红PG1 failed/294 passed→最终1455 passed/1 skipped/4 deselected（310.24s）；check/生成/web119/构建通过，独立P2先红后修及复核通过（P-05/P-06） |
| T1.2 | 行程模型：`HotelStay`、`hotel_stays`、互斥校验、`stays_of`；移除 4 处 24 上限（改为一个宽松的防护上限，建议 200，并与 512 KiB 请求边界一起保留诊断日志） | T1.1 | domain/plans.py、domain/itinerary.py、services/plans.py(LockInput) | ① 同时给 `hotel_evidence_id` 与 `hotel_stays` → 拒绝 ② 旧 `hotel_evidence_id` 内容可读、`stays_of` 转为单段 ③ 30 项 PlanContent/patch/locks 通过模型校验 | done | `22b4ff9` 已push；先红1 failed→定向20 passed→全量1461 passed/1 skipped/4 deselected（310.85s）；check299/生成/web119/构建退出0；自审/独立复核无P1/P2（P-07） |
| T2.1 | 按段查询酒店：`HotelSearchInput` 增 `segment_arrive: date \| None`（多城市时必填，单城市省略）；服务端用 `segment_request` 调现有 `_quote`；`refresh` 沿用原报价的段 | T1.1 | tools/travel.py、services/hotels.py、domain/evidence.py(`applicable`) | ① 三段行程分别查两段酒店，证据条件各自匹配 ② 多城市不给 segment → 422 明确提示 ③ 查询后全局 request 未被修改（revision 不变） ④ 单城市调用参数与结果不变 | done | `66214cf` 已push；先红领域/PG各1 failed→定向62 passed→全量1465 passed/1 skipped/4 deselected（308.04s）；check299/生成/web119/构建退出0；自审/独立审查无P1/P2（P-08/P-09） |
| T2.2 | 校验与暂存/确认：validator 改按 stays、按天城市归属；`content_view` 返回 stays 与各自酒店卡；给模型读完整 `item_id`：`bounded_plan` 在 cards 截断时附带完整 `item_ids`（仅 UUID+日期+名称，受 RESULT_LIMIT 约束），或复用已有读取工具，二选一并在 §8 记录 | T1.2、T2.1 | domain/validator.py、services/plans.py、tools/travel.py | ① 三城市+两段住宿 草稿→confirm→get（PG）全程通过 ② 漏一段住宿、stay 日期与段不符、报价属于别的段 → 各自 conflict 且 confirm 被拒 ③ 30 项行程：stage→confirm→get→对第 27 项 patch→confirm（PG）④ 跨城市重复景点仍被 `require_unique_sightseeing` 拒绝；同城再次入住不报重复 ⑤ 旧单城市已保存数据（直接写入旧 payload）可 get、patch、confirm | done | 最终全量1488 passed/1 skipped/4 deselected（308.34s）、check300/生成/web119/构建退出0，PG38相关通过；自审及独立复核无P1/P2，已commit/push6262d2e（P-10—P-13） |
| T3.1 | 住宿预算确认：`task_missing` 按 D4 增 `lodging_budget`；条件提取写入 per_room_night/JPY 或 unlimited；改 persona.py:54；`update_travel_request` 描述只问每间每晚 | T1.1 | domain/conversation.py、tools/travel.py(描述)、agent/persona.py、agent/fixture_conditions.py | ① 有住宿且两者皆空 → itinerary 缺 `lodging_budget`；② 说“不限” → `unlimited=True`，不再缺；③ 已给金额 → 不重复问；④ 当日往返（0晚）不要求；⑤ 不新增全程预算/币种追问（fixture 对话测试断言回复不含这些问题） | done | `6f10d05` 已push；先红3 failed及审查4 failed→全量1507 passed/1 skipped/4 deselected（309.91s）；check301/PG Healthy/生成/web119/构建通过，自审/独立复核无P1/P2 |
| T3.2 | 节奏与密度：validator 用 `pace_of`；完整日/非完整日判定；`pace_too_sparse`、`day_gap`；conversation、fixture 统一用 `pace_of` | T1.1、T2.2 | domain/validator.py、domain/conversation.py、agent/fixture_conditions.py | ① 标准节奏完整日 2 个景点 → `pace_too_sparse` ② 转场日 2 个 → 不报 ③ 完整日 13:00–17:00 空白 → `day_gap` ④ 慢节奏 4 个 → `pace_warning` ⑤ 已说“轻松” → 不再追问节奏 | done | `0117374` 已push；先红8 failed/别名2 failed/审查2 failed→最终全量1554 passed（309.50s）；check303/PG/生成/web119/构建、自审/独立复核通过 |
| T3.3 | 停留时长：类别区间表 + `visit_duration_range` | T2.2 | domain/catalog.py、domain/validator.py | ① 博物馆 15 分钟 → conflict ② 神社 6 小时 → conflict ③ 博物馆 40 分钟 → unknown ④ 酒店/餐厅 10 小时不报 ⑤ 正常行程无此类检查失败 | done | `0117374` 已push；先红10 failed→最终全量1554 passed；真实PG极端时长拒confirm且零正式版本；check303/生成/web119/构建、自审/独立复核通过 |
| T4.1 | 提示词：删 persona.py:59“说明是模型概述、非来源核实”；`ProposedItem.note` description 改为“一句话简介”；多城市指引（按段 search_places 用段城市原文、按段查酒店、转场日留时间、跨城交通写成“建议”且不写未查询的车次/耗时/票价）；节奏/时长规则说明 | T2.2、T3.* | agent/persona.py、domain/itinerary.py、tools/travel.py | 提示词快照/现有提示词测试更新并通过；persona 不再含“非来源核实”；512 KiB 请求边界测试仍通过 | doing | 开始提示词/字段description先红 |
| T4.2 | 前端：按天显示城市与当晚住宿；转场日显示“转场建议（未查询车次与票价）”；顶部统一说明“行程简介由 AI 整理，游玩时间为建议安排”；历史 note 去掉末尾重复标记（只剥离固定后缀模式，不动正文）；条件面板展示城市段与“每晚预算/不限”；用现有命令重新生成 api-types | T2.2、T3.1、T4.1 | apps/web/src/lib/itinerary.ts、components/results.tsx、saved-trip.tsx、conditions.tsx、lib/pace.ts、api-types.ts（生成） | ① `web test`：3 城数据按天分组含城市与住宿；30 项可渲染；含“（模型概述，非来源核实）”等后缀的 note 被剥离、正常含“核实”字样的简介不被误删 ② `dev.py web-generate` 后 `web-check` 全过 ③ 浏览器手动走一遍三城市草稿与旧行程（截图进 docs/evidence） | doing | T4.1先红2 failed→66 passed；开始前端先红，截图并入T5集中验收 |
| T5.1 | 集中验证与交付：§9 全量；更新 §7/§8/§9；面试案例候选 | 全部 | — | ① §9 命令全部通过并贴输出摘要 ② 本地浏览器按 §9.2 #1/#3/#8 走通（截图入 docs/evidence）③ 真实模型 API 跑 1 次三城市对话到确认保存（预算按 .env 限制），记录轮次与结果；失败则开 P-条目修复后重跑，不以“离线通过”代替 ④ 独立只读审查复核回归、重复实现与过度设计 | todo |

## 5. 边界与不变量

- runtime 只用 Claude Agent SDK 现有循环与修复轮次；不新增模型循环、不新增依赖。
- 不通过临时修改全局 `city`/日期来查别的段；`segment_request` 只在内存中存在。
- 单城市路径（`segments is None`）的条件字典、证据有效性、validator 结果与基线一致——任何差异都算回归。
- 未查询的跨城车次、耗时、票价不得以事实形式出现在 note、校验文案或前端。
- 512 KiB 模型请求边界与请求大小诊断日志保留（P-99 产物）。
- 规则文案不声称按航班/车次时刻计算（抵达返程仍是自由文本）。
- 不改断言或跳过检查来过关；生成文件（`api-types.ts`、`web-openapi.json`）只用生成命令更新。

## 6. 发布与回退

- Railway 当前跟踪本分支（见上一批次 2026-10-09/10 记录）：**每次 push 都可能上线**。T1.1–T2.2 期间多城市入口尚未在前端暴露，旧路径不变，可正常 push；若某个提交导致单城市回归，`git revert` 该提交并 push。
- 无 DB 迁移，回退无需 downgrade。
- **回退安全采用“先兼容读、再写新格式”（T0.2）**：第一个 push 的提交只让读取路径能识别并容忍 `hotel_stays`、`segments`、`lodging_budget_unlimited`（读到即保留，不写），不改任何写入行为。之后所有提交都在它之上，任何回退只回到 ≥ T0.2 的提交，新格式数据仍可读取，不会 500。
- 新格式写入（T1.1/T1.2 起）上线前，T0.2 必须已在 Railway 部署成功（看部署日志与一次 `GET` 已存行程正常）。
- 修复优先“向前修”；确需回退时只用 `git revert` 回到 T0.2 之后的状态，不 force push。

## 7. 每日进展

（倒序，按 plans/README 模板）

### 2026-10-10
- 计划：依次执行 T0.1–T5.1，D1–D6 按推荐；T0.2 先部署再进入 T1.1。
- 完成：T0.1/T0.2（33df5fe）、T1.1（03701b1）、T1.2（22b4ff9）、T2.1（66214cf）、T2.2（6262d2e）、T3.1（6f10d05）、T3.2/T3.3（0117374）均已push；Railway兼容读部署/旧V1 GET200已验，§3.2源码核对无出入；全量结果见§9.1，P-01–P-15完成。
- 未完成及原因：T4代码和整批审查修复已通过全部检查（后端1558 passed、前端129 passed），提交恢复点中。Chrome预算问一次/不限后继续、单城市旧引用格式V1→刷新→修改V2→刷新已通过；真实三城市仅部分草稿确认恢复，Google places今日25次配额耗尽，完整三城#1验收未完成（P-18）。
- 下一步：费用本轮新增0.647704CNY、12HTTP，今日合计8.924630/15CNY；09:00JST日切后补齐三城景点再验收保存恢复。提出09:05单次自动续接授权请求（自动审批拒绝每日重复续接，尚未创建），不清账或扩大.env限制。最终完成才标T4.2/T5.1 done。

上一恢复点（2026-10-10 23:03 JST）：HEAD `6262d2e` 已push，T0.1–T2.2全部完成。未提交均是本agent的T3.1：conversation、fixture_conditions/runtime、persona、tools/travel描述、PG会话测试、新test_lodging_confirmation.py和本计划。预算先红3 failed后实现；相关125 passed，check301/三平台/3契约/10入口与生成已过。独立审查的同句赋值/清空问题4 failed→修复后相关109 passed（8.43s，含真实PG恢复与手填来源）。下一步复核、完整test与web-check、自审、T3.1单独commit/push；T3.2以后尚未开始，浏览器/真实API T5未做。CLI固定2.1.295，仅项目dev.py命令，Git同作者与共作者。

恢复点（2026-10-10 23:17 JST）：HEAD `6f10d05` 已push，T3.1完成（1507 passed/309.91s与全部检查）。当前未提交是T3.2（validator、conversation、fixture_conditions、新test_pacing_rules）及本计划；先红8 failed与提及边界2 failed→相关163 passed、真实PG50 passed；check302通过。T3.3先红10 failed→相关109 passed，check303/PG50通过；两P2先红修复后独立复核通过，真实PG极端时长confirm6passed/硬节奏17passed；生成退出0；完整test（session66802，t33-test-final.log）及web-check（session30772）运行中，两任务按§9.3合一可运行提交，需完整test/生成/web-check/审查后push。T4/T5仍未开始。

恢复点（2026-10-10 23:23 JST）：HEAD `0117374`已push，T0–T3全部完成；最新全量1554 passed/1 skipped/4 deselected（309.50s），check303/生成/web119/构建、PG及独立复核通过。刚提交工作区干净；后续未提交为T4.1/T4.2及本计划状态更新。下一步T4.1先红提示词/description，接着T4.2先红前端；按§9.3合一提交，最后T5本地Chrome三场景与真实模型直至用户确认保存。

## 8. 问题解决记录

（P-编号从本批 P-01 开始；遇到计划外问题按模板新开）

### P-01 [计划外/基线环境] CLI 自动更新与前端构建权限   状态：done   关联：T0.1 T0.2
- 现象：业务源码未修改时，全量离线测试 `4 failed, 1404 passed, 1 skipped, 4 deselected`（295.18s）；web typecheck/lint/test 119 passed，但生产构建报 Turbopack `creating new process / binding to a port / Operation not permitted`。
- 环境：macOS，HEAD `0e0bc71`，真实 PostgreSQL 17 已由项目 db-up 启动 Healthy；无真实模型/供应商请求。
- 假设与排除：
  1. ✓ CLI 更新导致能力门禁拒绝：PATH 当前 2.1.296；runtime 精确白名单仅 SDK0.2.163/CLI2.1.114、2.1.294、2.1.295；四项失败均为 blocked/auto_compaction_capability 且 0 请求（VERIFIED）。
  2. ✗ 数据库不可用：真实 PG 测试均已进入实际断言，失败集中在 SDK 关闭压缩变体，不是 PG setup。
  3. ? Turbopack bind 权限原因：沙箱内与受控授权的相同 web-check 均为同一 EPERM；未证明应用源码有问题。第一次额外权限审查超时，命令未启动；随后沙箱实际失败、授权重试仍失败。两次实际尝试无进展后转做兼容读，不改构建脚本或放宽检查。
- 方案对比：测试进程显式指定已保留且 CI 使用的 CLI2.1.295（采用，不改用户全局CLI或.env）/ 将2.1.296直接加入白名单或跳过测试（不采用，无独立能力证明）。前端构建稍后继续从 panic 日志和现有运行环境定位。
- 实现与验证：dev check 299文件三平台strict/3分层契约/10入口通过；web-generate退出0、生成文件净diff=0；首次dev test与web-check失败摘要如上。原始输出在 `.cache/multi-city-pacing/t01-baseline-*.log`（未提交）。
- 结果与遗留：显式选择已有CLI2.1.295后完整test `1408 passed, 1 skipped, 4 deselected`（297.16s）退出0；未来关卡与提交钩子必须沿用该进程级选定，不更改用户默认CLI。前端另有新证据：旧授权重试沿用首次沙箱构建的Turbopack磁盘缓存；将缓存可回退移动到ignored目录后相同授权web-check `119 passed`、生产build5路由全部退出0（VERIFIED：清理生成缓存后复核有效，不改变Next配置/依赖/检查）。基线所有命令现已通过。Railway API基线部署 `70856529-b452-4e5d-9281-35d71af968ac` / `0e0bc71` / SUCCESS已只读核验。
- 面试一句话：把运行环境版本变化与业务回归分开验证，保持能力门禁和质量检查原样。

### P-02 [T0.2/回退边界] 新字段与未来长行程必须先可读   状态：done   关联：T0.2
- 现象：基线 PlanContent/ItineraryProposal/PlanPatch 为 extra=forbid，且24项上限会使后续30项正式版本在回退时不可读；request_details读取目前不恢复segments/unlimited。
- 环境：`0e0bc71`，真实PG专用隔离测试库；前端入口尚未扩展。
- 假设与排除：1. ✓ 新字段会被模型拒绝（VERIFIED：真实PG GET报content.hotel_stays extra_forbidden，1 failed/189 passed/4 deselected，103.94s）。2. ✓ 只兼容字段仍不能保护后续30项数据（REASONED，新增长内容读取回归）。3. ✗ 可用extra=ignore忽略新值（违反“读到即保留”，不采用）。4. ✓ 独立审查确认仅检查request.segments会漏掉单城市新住宿；读取200项使旧patch合并结果突破24项；readOnly注解仍把不可写字段暴露为工具参数（REASONED，新增回归先红）。
- 方案对比：在已有模型中定义只读增量字段；持久化读取明确标记上下文，输入写入继续拒绝新字段/超过24项；默认空增量不序列化，保留单城市原payload（采用）。不建立第二套存储/模型循环。长内容仅预先开放读取，正式写入上限仍到T1.2才改。
- 实现与验证：首次先红1 failed/189 passed；首轮绿1414 passed/1 skipped/4 deselected（296.91s）。新增审查回归完整跑到300秒上限（记录4个F，无摘要），以maxfail=4获取明确失败：4 failed/1008 passed/4 deselected（280.86s），分别为单城市stays暂存未拒绝、长草稿错误理由非只读、工具字段集合改变、旧patch24→25未拒绝。修复：SkipJsonSchema隐藏只读工具字段；旧patch合并恢复24边界；暂存/确认/锁定统一检查新格式（包括不限预算），GET不写回。全量最终测试与独立复核中，尚无提交；没有修改既有断言或放宽检查。
- 结果与遗留：33df5fe独立commit/push，最终1419 passed/1 skipped/4 deselected（305.62s）退出0、独立复核通过；Railway及旧正式GET验收见P-03。兼容读取版本已发布，T1.1在其后启用条件写入。
- 面试一句话：回退保护既要覆盖新字段，也要覆盖后续合法数据的长度边界。

### P-03 [T0.2/验收环境] 中断后浏览器控制与旧格式验收样例   状态：done   关联：T0.2
- 现象：恢复额度后浏览器编号变动；Chrome扩展控制报Debugger unattached；旧格式离线样例生成报missing_fields: transport。
- 假设与排除：1. ✓ 原生Chrome可控（VERIFIED），继续遵守Chrome偏好。2. ✗ 已选步行即可保存：菜单点击与键盘两次均未改变控件，编辑版本仍1。截图显示条件面板滚动位置使交通控件在可见区域外，下一步滚动至控件再验证；先转兼容读回归修复，不连续盲试。
- 实现与验证：在既有Chrome身份中新建2026-11-03—05京都离线验收旅行；新建Chrome控制标签后扩展恢复（标签1646779643），使用语义控件选择步行并核对“交通·手动填写”后生成，确认保存V1。我的行程重新读取3天6景点、模拟住宿、0冲突8未知，截图见 `docs/evidence/2026-10-10-t02-legacy-before-deploy.jpg`。未调用真实模型，没有修改原2026-10-07旅行。
- 结果与遗留：`33df5fe` 已push；Railway API部署d62b5631-2d55-498f-ac76-9b25ddc720b6、Web部署a4ef3799-cd9a-40b9-8dfc-0e1be7491e7c均同SHA SUCCESS。API启动完成、/health200；Chrome刷新后旧京都V1 GET /plans/...200（VERIFIED），三天六景点/两晚住宿、已知15000、冲突0/未知8与发布前一致。截图 `docs/evidence/2026-10-10-t02-legacy-after-deploy.jpg`。发布关卡通过后开始T1.1；未改认证/权限或浏览器偏好。

### P-04 [T0.2/验证耗时] 全量测试触及项目300秒上限   状态：done   关联：T0.2
- 现象：审查修复后的完整测试已到96%，没有F，但dev.py在300秒终止；不能记为通过或提交。
- 假设与排除：1. ✓ 隔离重跑也在97%到test_travel_sdk_offline.py时被外层300秒终止，排除仅并行前端构建的解释。基线297.16/首轮296.91秒，只有约3秒余量；新增PG回归使整套预算不足（VERIFIED外层终止，修复后完整结束仍待证明）。2. ✗ 已有失败断言：两次进度均无F，前端119通过；不把未结束视为通过。3. ✗ 最后模块必然挂起：没有该证据，外层在它刚开始时已到总时限。
- 方案与验证：两次无进展后记录并完成独立旧格式浏览器保存/重读（P-03）；后续任务全部受发布关卡约束，无可越过的任务。回到根因：只为run_tests设有界的整套预算600秒，公共执行器默认300秒、SDK进程/请求期限、业务校验、测试集合与断言均不改；不添加重试/忽略失败。独立只读审查认为是可接受最小修复，风险是挂起时最长多等5分钟，仍有界。先补“310秒的完整失败运行仍返回原退出码且等待有界”回归，红阶段运行中；仅调整既有mock签名接受显式timeout，未改既有断言。
- 先红：`test_full_offline_suite_keeps_failure_exit_after_long_but_bounded_run` 实际失败（入口返回1而非原失败码7），项目test为1 failed/451 passed/4 deselected，261.03s；没有筛选测试。实现仅给run_tests外层600秒，回归mock保留失败码与有界等待要求；新测试一处101字符格式错误已拆行，不改断言。
- 结果与遗留：完整绿阶段会话45522退出0，1419 passed/1 skipped/4 deselected，305.62s（VERIFIED，原300秒确实不足）；日志t02-budget-green.log。独立只读审查复核三处业务问题修复及实际预算diff，均无剩余P1/P2；调整后check、generate/web-check退出0。实现与测试在 `33df5fe`，已push；预算仍有界，挂起时最多额外等5分钟。

### P-05 [T1.1/条件派生] 启用城市段与三态预算   状态：done   关联：T1.1
- 现象：T0.2刻意只读；RequestPatch不接受新字段，城市段连续性、共用城市/节奏派生及侧列写入尚未启用。
- 假设与依据：源码确认D1/D3可沿用JSONB和现有CAS/来源事务，不需迁移；必须保留旧conditions和四种证据条件字典。按计划将字段移到TravelConditions，派生只在apply_request_patch合并入口，酒店查询副本不写回。
- 验证：已补非法单段/重叠/缺口/首末不符/非末段0晚、不限与金额互斥、软硬节奏别名、小城市别名、旧条件字典以及真实PG侧列/失效回归，先红运行中。T0.2阶段的临时拒写断言在后续契约启用时需按本计划改为新契约测试，历史红绿证据保留，不放宽结构/来源/CAS校验。
- 先红已验证：新增PG回归在RequestPatch.set拒绝segments/unlimited，1 failed/294 passed/4 deselected，255.94s；会话44780退出1。实现城市段共用派生、侧列写入与失效，尚在全量绿阶段会话6825（t11-green.log）。T0.2本轮新增的阶段性拒写测试随T1.1启用更新为非法单段/字符串bool拒绝、持久化全局冲突拒绝；不是修改原有业务断言来掩盖失败，原CAS/金额/证据断言保留。ADR-015追加D1/D3契约；现有单城侧列/来源不新增空键，明确False不被省略。
- 最终验证：首轮1448 passed/1 skipped/4 deselected（307.42s）；含P-06及全部新增PG回归的完整test会话49983退出0，1455 passed/1 skipped/4 deselected（310.24s）。check299文件/三平台/3契约/10入口、生成、web119/type/lint/build退出0；自审及独立复核无剩余P1/P2。实现与回归在03701b1，已commit/push。

### P-06 [T1.1/独立审查] 城市段派生不能吞掉显式clear   状态：done   关联：T1.1
- 现象与根因：独立只读审查指出set.segments同时clear city/start/end会先清除再被派生覆盖，来源却可能标none（REASONED）；新增参数化回归实际1 failed/7 passed，city分支DID NOT RAISE（VERIFIED）。
- 方案：在既有RequestPatch.valid_operations拒绝这类结构冲突（采用，最小改动）；不重排事务或增加派生状态。旧单独clear segments仍保留全局单城值。
- 验证：仍用项目dev.py test，通过PYTEST_ADDOPTS仅选择领域模块观测审查红绿（不是全量结论）：1 failed/7 passed→50 passed，含三种clear、单段逆序、>6段、硬软节奏优先、False/幂等键。PG补读取条件/来源/revision不变；最终提交前完整check/test仍必须全过，不能用定向结果代替。完整绿阶段6825仍运行，其开始后新增回归必须再完整运行。
- 最终结果：全部新增回归随最终完整test实际运行，1455 passed/1 skipped/4 deselected，310.24s，退出0；独立只读复核确认P2修复完整、无新P1/P2。实现与回归在03701b1，已commit/push。

### P-07 [T1.2/模型契约] 住宿互斥与有界长行程   状态：done   关联：T1.2
- 现象：兼容读阶段仅保存新引用，缺互斥、统一旧段投影与整体patch，四处写入上限仍24。新增测试同给旧ID/stays实际DID NOT RAISE，1 failed（0.26s，t12-red.log），证明需模型约束。
- 根因与方案：沿用现有模型，单个PLAN_ITEM_LIMIT=200供content/proposal/patch/locks；stays_of投影旧已知日期；新住宿出现即整体替换，空列表清除，未提供保留。T2.2前旧服务仍拒写未接通validator的新内容，post-merge guard防止patch silently丢stays。不新增模型/存储/依赖。
- 阶段测试取舍：T0.2本批新增的“只读新字段/24项”测试是发布保护阶段契约；批准T1.2明确替换为读写段引用、互斥和200→201拒绝，旧契约历史证据保留P-02。不是放宽业务校验掩盖回归；基线既有patch/锁/确认/CAS/请求边界断言不变，非法201/210项、重复ID、双引用仍拒绝。
- 验证：定向20 passed（0.25s）；首次check发现新测试模型字典推断为metaclass/异构dict取值object，改为明确联合类型和typed局部列表，无ignore/Any扩散。完整dev test43700运行中，生成契约由命令更新；独立只读审查在运行。
- 最终验证：完整dev test1461 passed/1 skipped/4 deselected（310.85s）退出0；check299/三平台/3契约/10入口、生成、web119/构建退出0，自审/独立审查无P1/P2。已commit/push 22b4ff9；按段业务校验/30项持久化成功属于T2.2，不提前声称完成。

### P-08 [T2.1/按段证据] 查询与刷新必须保持全局条件   状态：done   关联：T2.1
- 先红：领域1 failed（按段hotel_offer.applicable=False）；PG1 failed（多城市漏segment仍成功，缺明确422），分别t21-red/t21-pg-red.log。HTTP为合成替身，保存/恢复使用真实PG。
- 根因：applicable仍只比较全局条件，search/refresh用全局城市/日期。采用segment_arrive选择有住宿段，内存segment_request副本复用_quote；refresh以原报价入住日与城市定位原段，未知/零晚/已删除段拒绝。全局request不写回；非hotel证据不改。
- 当前：首轮领域32 passed，PG推进到refresh时触及原动态quota（P-09）；修复后定向62 passed（0.70s），包含两段query/refresh、查后全局request/rev不变、原段删除422、第4次仍拒绝；完整test47473退出0：1465 passed/1 skipped/4 deselected（308.04s），check299三平台/3契约/10入口、生成、web119/构建退出0；独立审查无P1/P2，66214cf已commit/push。

### P-09 [计划外/T2.1配额] 动态酒店次数仍只按一个段计算   状态：done   关联：T2.1
- 现象：三城市两段各1晚查询成功，refresh第二段被“本轮rakuten调用已达上限”拒绝（1 failed/32 passed，t21-green-1.log）。
- 根因（VERIFIED）：Rakuten.search每次把DEFAULT的run_caps设为min(8,段晚数+1)，全局used累积；第二段将全程两晚预算错误降为2，一次refresh成为第3次而失败。四晚两段甚至在第二段逐晚查询中耗尽。
- 方案：沿用原min(8,晚数+1)保护，以当前全程住宿晚数给多城市查询共享预算（采用）；单城不传新增可选内部参数，原调用/配额精确不变。只为adapter.search增加可选budget_nights，服务从已知全程日期传入；不提高8次硬上限、不改.env每日预算或档位，不新增循环/依赖。改变的是计算输入的段范围，不改变D1–D6。
- 验证：失败路径不改断言，同一PG成功路径修复后通过；补2/1000晚共享budget输入仍为3/8，以及第4次调用拒绝。原单城三档动态配额测试保留。check定位旧测试adapter子类签名需接受新增可选kw，仅同步签名，不改断言。完整check/test退出0，1465 passed/1 skipped/4 deselected（308.04s），独立审查无P1/P2，66214cf已commit/push。

### P-10 [T2.2/端到端] 住宿段校验、恢复与长行程ID可见性   状态：done   关联：T2.2
- 范围：按天城市+stays校验、各段住宿成本与预算unknown、stage/confirm/get/locks保留住宿、PG30项修改第27项、旧单城结果与payload保留。
- 读取方案（REASONED）：采用复用既有get_saved_plan工具，增加items_only/item_offset紧凑分页（每页最多40个UUID+日期+名称），不新建工具。200项UUID加日期名称超过RESULT_LIMIT8000，不能假称一个完整item_ids数组总能放下；分页提供next_item_offset且名称有界，保留原结果上限。默认详细读取和页面API保持旧行为，模型按offset取得每个稳定ID。
- 先红：领域三城市实际conflict而非partial（1 failed，t22-domain-red.log）；PG新测试先修正set不带null的输入，实际stage被T0.2只读保护拒绝（1 failed，t22-pg-red-2.log）。单城市完整报告字节基线在实现前1 passed（t22-single-baseline.log）。
- 初轮：三城市5/30项、漏住宿/范围/错段/重复及领域共13 passed；剩余失败为T0.2本批临时视图/只读阶段契约。按批准T2.2启用转为新视图（引用不丢、未知hotel=null）、locks no-op保持旧JSONB及无报价/重复依旧拒绝，原基线业务断言不变。
- 附加先红：酒店卡用全程四晚金额判两晚价，7500/晚相对6000误报False（1 failed，t22-card-budget-red.log）；按匹配住宿段内存副本复用预算关系修复，旧单城卡片计算不变。最终定向35 passed/4.35s，含直接旧payload修改确认、同城再次入住、正常/转义名称200项连续ID分页（P-12）；check300三平台/生成/web119/构建退出0，完整test待最终重跑。

- 提交前验证：最终dev test1488 passed/1 skipped/4 deselected（308.34s），check300/三平台/3契约/10入口、生成、web119/构建退出0；相关38 passed，独立只读复核通过。已commit/push6262d2e。

### P-11 [计划外/T2.2隐性上限] 30项含路线超过单次50条证据   状态：done   关联：T2.2
- 根因依据：resolve_records保持单次50条，旧24项+相邻路线最多48；新30项+25个同日路线+两住宿需要57条。仅无路线30项测试会漏掉实际保存失败。
- 先红：PG30项先按现有PlanningService.routes（每次≤6）查询全部同日路线，再暂存；完整引用>50的断言保留，实际evidence_over_50拒绝（t22-route-limit-red.log）。
- 方案：validate_proposal在同一已有事务与会话锁内按50条分批调用resolve_records，全部收齐再hydrate/validate，不放宽公共单次50边界；行程模型200和请求512KiB边界继续生效。不增加模型循环/工具/依赖。

- 提交前验证：最终dev test1488 passed/1 skipped/4 deselected（308.34s），check300/三平台/3契约/10入口、生成、web119/构建退出0；相关38 passed，独立只读复核通过。已commit/push6262d2e。

### P-12 [T2.2/独立审查] 未知报价绑定、转义分页与日期时区   状态：done   关联：T2.2
- 依据：只读审查定位hotel_cost未知来源提前返回，导致任意段适用报价可挂错stay；40条名称80字符未经JSON转义尺寸计算；紧凑日期截字符串忽略日本时区。
- 先红：未知报价跨段领域1 failed（partial而非conflict）；真实PG转义名称1 failed（result_too_long）；UTC跨日1 failed（日期11-02而非日本11-03）。原始日志t22-review-source-red/t22-review-page-red-2/t22-review-day-red.log。
- 排除：首次使用零字符被PG JSONB拒绝22P05，属于合成输入问题，换合法换行后实际复现尺寸根因；不改数据库/校验。
- 方案：stay先复用record.applicable(scoped,now)，旧单城hotel_cost不动；紧凑视图复用RESULT_LIMIT按真实payload尺寸缩页、next_item_offset跟随实际条数；日期复用KYOTO时区。补PG错误来源confirm拒绝与200项分页连续完整ID验证；默认正常名称仍每页40，转义名称按上限可少于40。

- 提交前验证：最终dev test1488 passed/1 skipped/4 deselected（308.34s），check300/三平台/3契约/10入口、生成、web119/构建退出0；相关38 passed，独立只读复核通过。已commit/push6262d2e。

### P-13 [计划外/工具回执] 新条件缺少中文标签   状态：done   关联：T1.1 T2.2 T3.1
- 根因（VERIFIED）：TravelToolExecutor更新成功后调用update_message；LABELS没有segments/unlimited，直接条件PG入口不走这一步，未暴露KeyError。纯领域回执失败1 failed（t22-receipt-red.log），并补真实PG工具入口写入/恢复，不替代服务层测试。
- 方案：在原condition_labels补两项中文标签与值格式；城市段按城市/日期显示，不限显示不限；旧字段文案和读写行为不变。不新增解释层或框架。
- 独立复核再发现不限→金额的bool=False回执显示未知，与金额矛盾；补先红1 failed后False复用原金额格式，未知只用于金额确实为空。工具PG合成入参明确声明explicit_fields=segments，手填守卫保持；没有修改断言或来源校验。刚启动的旧代码全量主动终止，待相关绿与复核后跑一次最终全量。先前完整1482/1485 passed为过程证据。

### P-14 [T3.1/预算确认] 行程必需确认与酒店比较可选分离   状态：done   关联：T3.1
- 先红：task_missing漏预算、fixture预算追问入口缺失、金额未清除互斥不限，真实失败3 failed/5 passed（t31-red-2.log）；初次合成输入修正为ConversationRequestPatch并解包apply_request_patch返回，不修改断言。
- 方案：只在itinerary且有住宿/预算未答时增加lodging_budget；Question加入预算，纯派生trip_segments判断晚数；金额/不限/0晚不重复问，hotel_comparison仍可选。persona与更新工具仅问每间房每晚JPY，不主动全程/酒店总额/币种。
- 有限离线：fixture_patch仅在当前预算问题允许裸不限，明确住宿不限也可写；金额/不限互斥旧值按明确变更清除；同句矛盾不任选。missing_question可接已有task，FixtureRuntime复用已有business_context的pending/awaiting，短答不靠助手历史猜测，不新增模型循环。
- 原会话回归fixture调整：原“住宿没有单独上限”只存prompt没有执行事实更新，新增预算必需后导致missing_fields多一项。保留全部原断言，模拟这一明确答案真正调用update工具，后续patch用实际revision；transport-only样例明确设置不限，从而继续只检验transport追问，不放宽服务规则。
- 过程：领域/fixture/persona76 passed；既有真实PG会话42 passed（13.24s）；新增PG问预算→不限→恢复→继续，含手填False来源守卫，相关125 passed（13.51s）；check301与生成通过。
- 独立审查根因（VERIFIED）：赋值不限后清空只看旧unlimited，旧False/True导致不同结果；补金额/不限×旧False/True四例，同句冲突均须澄清，4 failed（t31-review-red.log）→不产生任何patch，相关109 passed（8.43s，t31-review-green.log）。不改既有断言。最终全量1507 passed/1 skipped/4 deselected（309.91s），check301三平台/3契约/10入口、PG Healthy、生成、web119/构建退出0，自审/独立复核无P1/P2；已独立commit/push `6f10d05`。

### P-15 [T3.2/兼容边界] 新密度规则与旧单城校验不变   状态：done   关联：T3.2 T3.3
- 核实（REASONED）：sightseeing_checks只查过多且soft前缀；visit_checks只查正时长；conversation与fixture各自认节奏。行号漂移以函数名核实，范围与§3.2一致。
- 执行边界：§5强制旧单城市validator报告完全一致，因此新增稀疏/空白/时长规则及validator新节奏识别仅在segments非空启用；旧分支保留原比较和提示。会话及fixture按D6统一pace_of。首末/转场日按§3.5“只查上限”不报稀疏；跨城相邻段不报空白。没有改变D1–D6。
- T3.2先红8 failed/10 passed（t32-red-2.log）→相关161 passed；自审补别名只是提及不设事实，两例2 failed→修复后163 passed（t32-green-2.log）。fixture仍有限词汇，不推断正常营业/咖啡馆名字为节奏。PG会话/行程50 passed（11.78s）；静态check302/三平台/3契约/10入口通过，保留原单城黄金报告及全部断言。T3.3时长先红10 failed/12 passed（t33-red.log）→相关109 passed（0.74s），check303三平台/3契约/10入口与PG50 passed（11.98s）通过。补真实PG极端时长拒绝确认，检查零正式版本/草稿未确认；全部原断言保持。独立审查发现两P2：日期无跨度上限，逐日分配会放大；硬节奏优先后显式改软节奏无效。先红2 failed（t32-review-red.log，1年生成367检查、硬轻松仍慢节奏）→按有界项目/段边界汇总空白完整日区间，复用remove_hard_constraints+explicit_fields仅移除已识别硬节奏，保留其他硬事实/来源守卫。相关166 passed（12.04s）；新增到9999年及手填硬节奏PG17 passed（0.43s，t32-hard-pg.log）。最终check303/独立复核通过；最终全量1554 passed/1 skipped/4 deselected（309.50s）；check303/三平台/3契约/10入口、生成、web119/构建均退出0，自审/独立复核无P1/P2。已按§9.3合一commit/push `0117374`。

### P-16 [T4.1/T4.2展示] 分段指引与统一说明   状态：doing   关联：T4.1 T4.2
- T4.1先红：prompt缺segment_arrive/hotel_stays且每项要求重复标记，2 failed/9 passed（t41-red.log）→按段原文查询、派生日期、转场建议/未知交通、规则修复说明与一句话简介，相关66 passed。512KiB原有守卫测试沙箱bind失败，按同一项目命令正常权限重跑，不修改断言或请求边界。
- T4.2先红：格式检查先拦住新增测试，修正位置/格式未改断言；实际4 failed/119 passed（t42-red-3.log）→127用例验证中，覆盖三城30项/住宿/只剥固定后缀/节奏硬优先/不限改金额。共享PlanResults使草稿与saved-trip同视图；旧单城只按报价日期读当晚住宿。条件摘要同步segments/不限，手填金额清互斥不限，显式手填节奏保留其他硬事实。生成命令更新8处description，无手改生成文件。
- 自审边界先红：住宿数组反序且缺place.city时转场提示漏报，1 failed/126 passed（t42-order-red.log）→取最早入住日期而非数组首项；保留原项目/报价顺序。check303通过；最终前端与独立复核进行中，浏览器仍待执行。
- 独立审查：普通对象aliases继承constructor/toString/__proto__，合法自由条件被识别为节奏并在手填编辑中误删。新增currentPace/mergePace/conditionPatch回归实际2 failed/127 passed（t42-review-red.log）→仅Object.hasOwn后取别名；独立只读复核无剩余P1/P2，最终全量检查仍运行。
- 环境问题：最终web-check两次均129 passed/0 failed、type/lint通过，但Next构建CSS worker绑定端口EPERM（含正常权限重跑）；不记作整套通过。记录后先转独立check/完整PG测试。假设残留沙箱失败产物被Turbopack增量缓存复用，保留旧.next到ignored缓存后重建核实；不改构建参数/代码/断言。
- 环境根因验证：保留.next到ignored缓存后同一命令重建退出0，129 passed/0 failed、type/lint/5路由构建全过（t42-review-green-fresh.log，VERIFIED）；证明失败缓存残留，未改构建配置。真实PG17 Healthy；本地API relaxed日费守卫开启，前端启动后Chrome验收。
- 更正上一条根因表述：VERIFIED的是保留缓存后重建成功；缓存残留只是REASONED，单次重建不能排除间歇权限影响。最终生成后再次web-check也退出0，129 passed/type/lint/5路由构建通过（t4-web-final.log），未更改命令/配置。

### P-17 [T5/整批审查] 历史城市与多住宿模型读取边界   状态：doing   关联：T2.2 T4.2 T5.1
- 现象与根因：新格式保存后clear segments会让历史卡片city消失；bounded_plan只缩cards/changes，6张住宿卡仍10822字符。新增真实PG与工具结果回归2 failed/47 deselected（t4-review-batch-red.log），VERIFIED。
- 方案：新格式hotel_stays且无旧hotel_evidence_id保留历史city；旧混合只读兼容载荷继续原输出。模型结果超8000时紧凑住宿卡，保留全部段日期/证据ID与名称/offer_id/总价/币种/来源模式/有效期，页面API完整卡不变，不提高上限、不改源对象。首轮48 passed/1 failed定位旧混合兼容输出，按旧ID识别修复，既有断言原样保留；最终检查中。
- 兼容识别尝试两次仍有同一旧读取断言失败：样例旧ID也为None，不能据ID区分；停止该假设，先完成独立Chrome不限保存/刷新并创建单城验收。返回后以已存地点实际城市与当前城市是否一致识别多城历史，保持单城兼容输出原样，待先前失败断言复核。
- 最终方案与证据：show_cities依据当前segments或新stays且已存Place城市与当前城市不一致（same_city）；旧单城/混合兼容载荷保持完整cards断言不变。完整领域/真实PG计划49 passed（4.29s），check303/三平台strict/3契约/10文档退出0；独立只读复核无剩余P1/P2，最终全量测试中。
- 最终全量：1558 passed / 1 skipped / 4 deselected（307.89s），项目test实际退出0（t4-test-reviewed.log）。前端129 passed、类型/lint/5路由构建退出0，生成命令退出0；整批独立只读复核两项修复，无剩余P1/P2。仍不将这些检查替代完整三城市浏览器/真实API验收。

### P-18 [T5/外部配额] 三城市真实对话的地点配额不足   状态：doing   关联：T4.2 T5.1
- 环境：本地真实PG，DeepSeek真实API、Google/Rakuten，relaxed档保留15CNY每日守卫；自建验收session `1fb65c90-05d1-494d-bb0e-b0e61300c991`，未修改历史用户旅行。
- 实测：首轮2a61bca3提取3段/人数/房型，漏记慢节奏，浏览器既有表单补正后回答单独“不限”；95988858不再追问预算，2次段酒店查询、1次validate、1次stage，0模型修复轮。真实乐天大阪2晚22680JPY，神户完整总价未知；Google places今日25次额度已耗尽，两城无景点，京都回退历史快照3项，草稿明确披露部分可用。
- 证据与结果：Chrome预算问一次/不限后继续已验证；部分草稿确认V1成功（3段条件、2段真实住宿、仅京都3景点），正在刷新恢复。截图budget-question-local/unlimited-partial-draft-local；不能将这一部分草稿升级为完整三城市#1验收。UTC日切09:00JST后才可在不扩大.env配额下重跑地点补全；不清计数、不改预算/供应商限制。继续独立审查修复与旧单城浏览器验收。
- 后续VERIFIED：部分V1刷新恢复成功，见partial-restored-local截图；单城市旧hotel_evidence_id引用格式（自建session fe27928d-fa31-417e-b969-3ea4bff5ce19）6景点/2晚住宿V1保存刷新→第二天下午14:00改15:00→V2保存刷新，其余5项目/酒店保持。真实PG只读核对V1/V2均无hotel_stays、保留旧酒店ID；截图legacy-v1-restored-local/legacy-v2-restored-local。真实费用/调用/未完成条件见2026-10-10-multi-city-live-partial.json；初次validate1次，模型修复0轮，人工补正节奏1次，不能称无需补正。
- 续接：每日重复自动化创建被auto-review拒绝（缺该具体持久重复任务的授权），没有绕过或创建替代定时；已通过异步问题请求明早09:05JST单次续接授权，待用户回复。若没有回复，仅保留恢复点与未完成项，不能声称已安排自动续接。
- 恢复操作：本任务启动的本地API与web开发服务已停止，PG保留。先核对本分支/HEAD/工作区，运行项目db-up；以进程级TRAVEL_CLAUDE_CLI选定2.1.295启动既有本地live relaxed API及dev.py web，保留每日守卫。Chrome仅恢复本条自建三城session，09:00JST日切后请求补齐大阪/神户景点、刷新过期酒店报价、重新validate并确认；避免重复景点，跨城交通保持未知。完成全部城市的草稿→保存→刷新后再将T4.2/T5.1标done；预算/旧引用格式截图与检查不用无故重跑。

## 9. 验证与交付

- T2.2提交前验证：dev test1488 passed/1 skipped/4 deselected（308.34s），check300/三平台/3契约/10入口、生成、web119/构建退出0；相关38 passed，独立只读复核通过。已commit/push6262d2e。

### 9.1 必需命令（项目自有，不得自造）

```bash
uv run python scripts/dev.py check        # ruff check / format --check / 类型 / 文档检查
uv run python scripts/dev.py test         # 离线测试（排除 live）
uv run python scripts/dev.py db-up        # 真实 PostgreSQL，供保存/恢复测试
uv run python scripts/dev.py web-generate # 契约变更后重新生成 api-types
uv run python scripts/dev.py web-check    # typecheck / lint / test / build
```

执行前用 `uv run python scripts/dev.py --help` 核对子命令名；PG 测试的运行方式以 docs/execution/verification.md 为准。

已运行输出摘要（VERIFIED，原始输出在ignored `.cache/multi-city-pacing/`）：

| 阶段 | check | test | db-up | web-generate | web-check |
| --- | --- | --- | --- | --- | --- |
| T0.1 基线 `0e0bc71` | 299文件、三平台strict、3契约、10文档入口，退出0 | 1408 passed / 1 skipped / 4 deselected，297.16s，退出0 | PostgreSQL17 Healthy，退出0 | 退出0，无净差异 | 119 passed / 0 failed，类型/lint/5路由构建退出0 |
| T0.2 兼容读 `33df5fe` | 同上，预算修复后check退出0 | 1419 passed / 1 skipped / 4 deselected，305.62s，退出0 | 同一真实PG，事务与恢复回归实际运行 | 退出0，契约由命令生成 | 119 passed / 0 failed，类型/lint/5路由构建退出0 |
| T1.1 条件写入 `03701b1` | 299文件、三平台strict、3契约、10入口，退出0 | 1455 passed / 1 skipped / 4 deselected，310.24s，退出0 | 同一真实PG，侧列/CAS/来源/恢复实际运行 | 退出0，契约由命令生成 | 119 passed / 0 failed，类型/lint/5路由构建退出0 |
| T1.2 行程模型 `22b4ff9` | 299文件、三平台strict、3契约、10入口，退出0 | 1461 passed / 1 skipped / 4 deselected，310.85s，退出0 | 同一真实PG，原事务/恢复回归实际运行 | 退出0，契约由命令生成 | 119 passed / 0 failed，类型/lint/5路由构建退出0 |
| T2.1 按段酒店 `66214cf` | 299文件、三平台strict、3契约、10入口，退出0 | 1465 passed / 1 skipped / 4 deselected，308.04s，退出0 | 同一真实PG，两段查询/刷新/拒绝及旧单城回归实际运行 | 退出0，无净生成差异 | 119 passed / 0 failed，类型/lint/5路由构建退出0 |
| T2.2 住宿与长行程 `6262d2e` | 300文件、三平台strict、3契约、10入口，退出0 | 1488 passed / 1 skipped / 4 deselected，308.34s，退出0 | PostgreSQL17 Healthy，真实PG保存/恢复/失败与200项分页实际运行 | 退出0，契约由命令生成 | 119 passed / 0 failed，类型/lint/5路由构建退出0 |
| T3.1 预算确认 `6f10d05` | 301文件、三平台strict、3契约、10入口，退出0 | 1507 passed / 1 skipped / 4 deselected，309.91s，退出0 | PostgreSQL17 Healthy，预算追问/不限/手填来源/恢复实际运行 | 退出0，契约由命令生成 | 119 passed / 0 failed，类型/lint/5路由构建退出0 |
| T3.2/T3.3 规则 `0117374` | 303文件、三平台strict、3契约、10入口，退出0 | 1554 passed / 1 skipped / 4 deselected，309.50s，退出0 | 同一健康PG，极端时长拒保存/硬节奏显式来源/旧单城恢复通过 | 退出0，无净生成差异 | 119 passed / 0 failed，类型/lint/5路由构建退出0 |
| T4.1/T4.2代码及P-17修复（提交恢复点中） | 303文件、三平台strict、3契约、10入口，退出0 | 1558 passed / 1 skipped / 4 deselected，307.89s，退出0 | PostgreSQL17 Healthy，历史城市恢复/旧单城回归、真实保存/恢复测试实际运行 | 退出0，8处description由命令生成 | 129 passed / 0 failed，类型/lint/5路由构建退出0 |

Python全量使用进程级 `TRAVEL_CLAUDE_CLI` 选定已安装/CI锁定的2.1.295；未改全局CLI/.env/白名单。1 skipped为既有平台专属测试，4 deselected为既有live标记，未新增跳过。

当前四项交付判定（2026-10-10，尚未完成T5.1）：

1. §9.1全部项目命令：通过，数字见最后一行；原始完整测试t4-test-reviewed.log、检查t4-review-batch-check-final.log、生成t4-generate-final.log、前端t4-web-final.log。
2. 本地Chrome：#3预算只问一次、回答不限继续通过；#8自建旧引用格式V1保存恢复/修改V2恢复通过，实际旧payload另由PG黄金回归覆盖；#1只有三段条件/两住宿/京都3项目的部分草稿保存恢复，完整三城未通过。截图见P-18，不把部分结果升级。
3. 真实模型：DeepSeek两轮12 HTTP、0模型修复轮、手动补正节奏1次；部分V1确认恢复成功，本轮0.647704CNY，完整三城市真实验收仍未完成（Google每日配额日切后续接）。
4. 整批自审/独立审查：回归、重复实现、过度设计检查和P-17修复复核通过。对照§1：PG三城市两住宿/旧payload/长行程链路通过，代码范围与不做项保持；§4的T4.2浏览器验收和T5.1完整真实验收尚缺，done means尚不满足。

### 9.2 必要测试清单（精简，核心成功+失败路径）

| # | 场景 | 层 |
| --- | --- | --- |
| 1 | 三城市（大阪2天→神户2天→京都1天）两段住宿：草稿→确认→恢复 | PG 集成 |
| 2 | 段重叠 / 缺口 / 漏住宿 / 报价属于别的段 | 单元 + 1 条 PG |
| 3 | 每晚预算：未回答→追问一次；给金额→不问；“不限”→继续；0 晚不问 | 单元（conversation + fixture） |
| 4 | 跨城重复景点被拒；同城再次入住不误报 | 单元 |
| 5 | 博物馆 15 分钟、神社 6 小时 → conflict；酒店长时不报 | 单元 |
| 6 | 转场日 2 景点不报过少；完整日过少/空白报 unknown | 单元 |
| 7 | 30 项行程：stage→confirm→get→patch 第 27 项→confirm；模型能拿到第 27 项 item_id | PG 集成 + 工具结果单元 |
| 8 | 旧单城市行程（旧 payload、旧证据）读取/修改/保存，结果与基线一致 | PG 集成 |
| 9 | 前端：按天城市+住宿、长行程渲染、历史 note 标记剥离 | web test |

### 9.3 建议提交切分（每个都可运行、可 push）

0. T0.1 + T0.2 兼容读（单独 push，部署成功后再继续）
1. T1.1 条件模型与兼容（含 ADR-015 追加）
2. T1.2 行程模型 + 取消 24 上限
3. T2.1 按段查询酒店
4. T2.2 校验/暂存/确认/恢复 + item_id 可见性（本批最大的一次，约 5–7h）
5. T3.1 住宿预算确认
6. T3.2 + T3.3 节奏密度与停留时长
7. T4.1 + T4.2 提示词与前端（含生成物）；随后 T5.1 只改文档

### 9.4 风险与工期影响

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 城市名不一致（神户/神戸/Kobe） | 多城市大量误报 city conflict，模型反复修正耗尽轮次 | T1.1 的 `same_city` + 工具描述要求“search_places 的 city 用段里的原文” |
| 模型看不到第 9 条以后的 item_id | >24 条甚至 >8 条的局部修改实际做不了 | T2.2 必做，验收 #7 明确断言 |
| 修复轮次不够 | 新增规则 + 多城市使一次规划的冲突数变多，3 轮修不完 | 新规则默认 unknown（D5）；只有极端时长是 conflict；真实 API 抽检 1–2 次看轮次消耗 |
| 乐天按段查询的调用量翻倍 | 真实 API 预算 | 实测只跑 1 次三城市；其余用 fixture |
| 回退后读不了新格式 | 回退后新行程 500 | T0.2 先兼容读并先部署，已消除（§6） |
| fixture 目录只有京都 | 多城市离线测试缺地点数据 | 测试里直接构造 Place/证据记录，不扩充正式 fixture 文件 |

工程量（Codex 实际执行，含测试与记录）：T1 约 3–4h，T2 约 6–8h，T3 约 3–5h，T4 约 3–4h，T5 约 1–2h，合计 **约 16–24h**。比原粗估 6–10h 高，主要多在：证据按段绑定与 validator 改造（T2.2）、item_id 可见性、前端按天重排与历史数据兼容、真实 PG 端到端测试。
