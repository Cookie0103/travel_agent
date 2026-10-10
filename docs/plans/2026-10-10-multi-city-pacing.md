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
| T0.1 | 切换当前批次入口；记录基线检查结果 | — | AGENTS.md、docs/README.md | 链接指向本文件；§9 全量命令在基线上跑一遍，结果写进 §7（失败项记为“基线既有”） | doing | 分支/HEAD VERIFIED：`batch/2026-10-10-frontend-restyle` / `0e0bc71`；仅本计划未跟踪，用户已授权纳入首个提交 |
| T0.2 | 兼容读（回退保护）：读取 `PlanContent/ItineraryProposal/PlanPatch` 与 `request_details` 时能接受新字段（`hotel_stays`、`segments`、`lodging_budget_unlimited`），仅读取不写入；API 写入入口仍按旧契约 | T0.1 | domain/plans.py、domain/itinerary.py、services/travel.py、services/plans.py | ① PG：直接写入含新字段的行程/条件 payload，`get` 正常返回且旧字段不变 ② 现有全量测试通过 ③ 单独提交并 push，Railway 部署成功后再开始 T1.1 | doing | PG首次读取先红；审查回归4 failed/1008 passed→最终1419 passed/1 skipped/4 deselected（305.62s），check/生成/web119/构建退出0；独立审查无剩余P1/P2；等待提交与发布关卡 |
| T1.1 | 条件模型：`TripSegment`、`segments`、`lodging_budget_unlimited`、派生函数、`same_city`、`pace_of`；`request_details` 读写；`invalidated_kinds` | T0.1 | domain/travel_request.py、services/travel.py(`request_from_row` 及写入处)、ADR-015 追加一节 | ① 段重叠/缺口/首末不符/非末段0晚 → 拒绝（失败路径）② `apply_request_patch` 设置/清除 segments、revision 正确递增 ③ 单城市 `evidence_conditions` 输出与基线字节相同 ④ `pace_of` 覆盖 soft/hard 与同义词 ⑤ PG：写入 segments 后重新读取一致 | todo | |
| T1.2 | 行程模型：`HotelStay`、`hotel_stays`、互斥校验、`stays_of`；移除 4 处 24 上限（改为一个宽松的防护上限，建议 200，并与 512 KiB 请求边界一起保留诊断日志） | T1.1 | domain/plans.py、domain/itinerary.py、services/plans.py(LockInput) | ① 同时给 `hotel_evidence_id` 与 `hotel_stays` → 拒绝 ② 旧 `hotel_evidence_id` 内容可读、`stays_of` 转为单段 ③ 30 项 PlanContent/patch/locks 通过模型校验 | todo | |
| T2.1 | 按段查询酒店：`HotelSearchInput` 增 `segment_arrive: date \| None`（多城市时必填，单城市省略）；服务端用 `segment_request` 调现有 `_quote`；`refresh` 沿用原报价的段 | T1.1 | tools/travel.py、services/hotels.py、domain/evidence.py(`applicable`) | ① 三段行程分别查两段酒店，证据条件各自匹配 ② 多城市不给 segment → 422 明确提示 ③ 查询后全局 request 未被修改（revision 不变） ④ 单城市调用参数与结果不变 | todo | |
| T2.2 | 校验与暂存/确认：validator 改按 stays、按天城市归属；`content_view` 返回 stays 与各自酒店卡；给模型读完整 `item_id`：`bounded_plan` 在 cards 截断时附带完整 `item_ids`（仅 UUID+日期+名称，受 RESULT_LIMIT 约束），或复用已有读取工具，二选一并在 §8 记录 | T1.2、T2.1 | domain/validator.py、services/plans.py、tools/travel.py | ① 三城市+两段住宿 草稿→confirm→get（PG）全程通过 ② 漏一段住宿、stay 日期与段不符、报价属于别的段 → 各自 conflict 且 confirm 被拒 ③ 30 项行程：stage→confirm→get→对第 27 项 patch→confirm（PG）④ 跨城市重复景点仍被 `require_unique_sightseeing` 拒绝；同城再次入住不报重复 ⑤ 旧单城市已保存数据（直接写入旧 payload）可 get、patch、confirm | todo | |
| T3.1 | 住宿预算确认：`task_missing` 按 D4 增 `lodging_budget`；条件提取写入 per_room_night/JPY 或 unlimited；改 persona.py:54；`update_travel_request` 描述只问每间每晚 | T1.1 | domain/conversation.py、tools/travel.py(描述)、agent/persona.py、agent/fixture_conditions.py | ① 有住宿且两者皆空 → itinerary 缺 `lodging_budget`；② 说“不限” → `unlimited=True`，不再缺；③ 已给金额 → 不重复问；④ 当日往返（0晚）不要求；⑤ 不新增全程预算/币种追问（fixture 对话测试断言回复不含这些问题） | todo | |
| T3.2 | 节奏与密度：validator 用 `pace_of`；完整日/非完整日判定；`pace_too_sparse`、`day_gap`；conversation、fixture 统一用 `pace_of` | T1.1、T2.2 | domain/validator.py、domain/conversation.py、agent/fixture_conditions.py | ① 标准节奏完整日 2 个景点 → `pace_too_sparse` ② 转场日 2 个 → 不报 ③ 完整日 13:00–17:00 空白 → `day_gap` ④ 慢节奏 4 个 → `pace_warning` ⑤ 已说“轻松” → 不再追问节奏 | todo | |
| T3.3 | 停留时长：类别区间表 + `visit_duration_range` | T2.2 | domain/catalog.py、domain/validator.py | ① 博物馆 15 分钟 → conflict ② 神社 6 小时 → conflict ③ 博物馆 40 分钟 → unknown ④ 酒店/餐厅 10 小时不报 ⑤ 正常行程无此类检查失败 | todo | |
| T4.1 | 提示词：删 persona.py:59“说明是模型概述、非来源核实”；`ProposedItem.note` description 改为“一句话简介”；多城市指引（按段 search_places 用段城市原文、按段查酒店、转场日留时间、跨城交通写成“建议”且不写未查询的车次/耗时/票价）；节奏/时长规则说明 | T2.2、T3.* | agent/persona.py、domain/itinerary.py、tools/travel.py | 提示词快照/现有提示词测试更新并通过；persona 不再含“非来源核实”；512 KiB 请求边界测试仍通过 | todo | |
| T4.2 | 前端：按天显示城市与当晚住宿；转场日显示“转场建议（未查询车次与票价）”；顶部统一说明“行程简介由 AI 整理，游玩时间为建议安排”；历史 note 去掉末尾重复标记（只剥离固定后缀模式，不动正文）；条件面板展示城市段与“每晚预算/不限”；用现有命令重新生成 api-types | T2.2、T3.1、T4.1 | apps/web/src/lib/itinerary.ts、components/results.tsx、saved-trip.tsx、conditions.tsx、lib/pace.ts、api-types.ts（生成） | ① `web test`：3 城数据按天分组含城市与住宿；30 项可渲染；含“（模型概述，非来源核实）”等后缀的 note 被剥离、正常含“核实”字样的简介不被误删 ② `dev.py web-generate` 后 `web-check` 全过 ③ 浏览器手动走一遍三城市草稿与旧行程（截图进 docs/evidence） | todo | |
| T5.1 | 集中验证与交付：§9 全量；更新 §7/§8/§9；面试案例候选 | 全部 | — | ① §9 命令全部通过并贴输出摘要 ② 本地浏览器按 §9.2 #1/#3/#8 走通（截图入 docs/evidence）③ 真实模型 API 跑 1 次三城市对话到确认保存（预算按 .env 限制），记录轮次与结果；失败则开 P-条目修复后重跑，不以“离线通过”代替 ④ 独立只读审查复核回归、重复实现与过度设计 | todo | |

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
- 完成：开工分支/HEAD 核验；用户确认未跟踪计划可纳入首个 T0.1/T0.2 提交；§3.2 逐项源码核对仍为 REASONED，14 项与基线一致；T0.1 基线全部命令已运行，最终 check 299文件/三平台/3契约/10入口，test 1408 passed/1 skipped/4 deselected（297.16s），web 119 passed/type/lint/生产build全部退出0，db-up Healthy，web-generate无净差异。
- 未完成及原因：T0.2审查回归先红4 failed/1008 passed（280.86s），已修复；P-04整套预算回归先红1 failed/451 passed→最终完整1419 passed/1 skipped/4 deselected（305.62s）退出0；独立复核无剩余P1/P2。尚未提交，Railway首个兼容版本发布关卡未通过。
- 下一步：T0.2提交/push → Railway 成功部署与已存行程 GET 核验；该关卡通过前不得开始 T1.1。

恢复点（2026-10-10 JST再次恢复额度后）：HEAD `0e0bc71`，未提交；入口/计划、domain itinerary/plans/travel_request、services plans/travel/views、两份plans测试、生成契约及旧行程证据截图均有本轮改动，另有scripts/dev.py与tests/test_dev.py的整套预算修复（P-04）。T1.1尚未开始。审查回归已先红并修复，独立复核无新增P1/P2；check（会话87735）、generate、web-check（119测试/生产build）退出0。两次完整test因300秒外层终止不可记通过；新增预算回归已1 failed/451 passed先红，显式600秒后完整绿阶段会话45522（t02-budget-green.log，CLI2.1.295）。下一步读取真实退出码及摘要、提交/push、核验Railway及已存行程GET。Chrome为1/Ke，新标签1646779643已markHandoff；旧格式京都验收旅行已确认V1并从我的行程重读，截图已落盘（P-03）。原始输出在 `.cache/multi-city-pacing/`（不提交）；意外中断先核对Git与相关进程及退出码，不能从“命令已启动”推断成功。

## 8. 问题解决记录

（P-编号从本批 P-01 开始；遇到计划外问题按模板新开）

### P-01 [计划外/基线环境] CLI 自动更新与前端构建权限   状态：done（环境复核，待首个提交）   关联：T0.1 T0.2
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

### P-02 [T0.2/回退边界] 新字段与未来长行程必须先可读   状态：doing   关联：T0.2
- 现象：基线 PlanContent/ItineraryProposal/PlanPatch 为 extra=forbid，且24项上限会使后续30项正式版本在回退时不可读；request_details读取目前不恢复segments/unlimited。
- 环境：`0e0bc71`，真实PG专用隔离测试库；前端入口尚未扩展。
- 假设与排除：1. ✓ 新字段会被模型拒绝（VERIFIED：真实PG GET报content.hotel_stays extra_forbidden，1 failed/189 passed/4 deselected，103.94s）。2. ✓ 只兼容字段仍不能保护后续30项数据（REASONED，新增长内容读取回归）。3. ✗ 可用extra=ignore忽略新值（违反“读到即保留”，不采用）。4. ✓ 独立审查确认仅检查request.segments会漏掉单城市新住宿；读取200项使旧patch合并结果突破24项；readOnly注解仍把不可写字段暴露为工具参数（REASONED，新增回归先红）。
- 方案对比：在已有模型中定义只读增量字段；持久化读取明确标记上下文，输入写入继续拒绝新字段/超过24项；默认空增量不序列化，保留单城市原payload（采用）。不建立第二套存储/模型循环。长内容仅预先开放读取，正式写入上限仍到T1.2才改。
- 实现与验证：首次先红1 failed/189 passed；首轮绿1414 passed/1 skipped/4 deselected（296.91s）。新增审查回归完整跑到300秒上限（记录4个F，无摘要），以maxfail=4获取明确失败：4 failed/1008 passed/4 deselected（280.86s），分别为单城市stays暂存未拒绝、长草稿错误理由非只读、工具字段集合改变、旧patch24→25未拒绝。修复：SkipJsonSchema隐藏只读工具字段；旧patch合并恢复24边界；暂存/确认/锁定统一检查新格式（包括不限预算），GET不写回。全量最终测试与独立复核中，尚无提交；没有修改既有断言或放宽检查。
- 结果与遗留：首个push仍只做兼容读；T0.2必须部署并读取已存行程后，才能进入新格式写入。
- 面试一句话：回退保护既要覆盖新字段，也要覆盖后续合法数据的长度边界。

### P-03 [T0.2/验收环境] 中断后浏览器控制与旧格式验收样例   状态：done（待发布后复读）   关联：T0.2
- 现象：恢复额度后浏览器编号变动；Chrome扩展控制报Debugger unattached；旧格式离线样例生成报missing_fields: transport。
- 假设与排除：1. ✓ 原生Chrome可控（VERIFIED），继续遵守Chrome偏好。2. ✗ 已选步行即可保存：菜单点击与键盘两次均未改变控件，编辑版本仍1。截图显示条件面板滚动位置使交通控件在可见区域外，下一步滚动至控件再验证；先转兼容读回归修复，不连续盲试。
- 实现与验证：在既有Chrome身份中新建2026-11-03—05京都离线验收旅行；新建Chrome控制标签后扩展恢复（标签1646779643），使用语义控件选择步行并核对“交通·手动填写”后生成，确认保存V1。我的行程重新读取3天6景点、模拟住宿、0冲突8未知，截图见 `docs/evidence/2026-10-10-t02-legacy-before-deploy.jpg`。未调用真实模型，没有修改原2026-10-07旅行。
- 结果与遗留：旧格式发布前读取已成立，发布后GET门槛仍待完成。不改认证/权限或浏览器偏好；误用旧编号打开的临时内置浏览器只读页不作为验收证据。

### P-04 [T0.2/验证耗时] 全量测试触及项目300秒上限   状态：doing   关联：T0.2
- 现象：审查修复后的完整测试已到96%，没有F，但dev.py在300秒终止；不能记为通过或提交。
- 假设与排除：1. ✓ 隔离重跑也在97%到test_travel_sdk_offline.py时被外层300秒终止，排除仅并行前端构建的解释。基线297.16/首轮296.91秒，只有约3秒余量；新增PG回归使整套预算不足（VERIFIED外层终止，修复后完整结束仍待证明）。2. ✗ 已有失败断言：两次进度均无F，前端119通过；不把未结束视为通过。3. ✗ 最后模块必然挂起：没有该证据，外层在它刚开始时已到总时限。
- 方案与验证：两次无进展后记录并完成独立旧格式浏览器保存/重读（P-03）；后续任务全部受发布关卡约束，无可越过的任务。回到根因：只为run_tests设有界的整套预算600秒，公共执行器默认300秒、SDK进程/请求期限、业务校验、测试集合与断言均不改；不添加重试/忽略失败。独立只读审查认为是可接受最小修复，风险是挂起时最长多等5分钟，仍有界。先补“310秒的完整失败运行仍返回原退出码且等待有界”回归，红阶段运行中；仅调整既有mock签名接受显式timeout，未改既有断言。
- 先红：`test_full_offline_suite_keeps_failure_exit_after_long_but_bounded_run` 实际失败（入口返回1而非原失败码7），项目test为1 failed/451 passed/4 deselected，261.03s；没有筛选测试。实现仅给run_tests外层600秒，回归mock保留失败码与有界等待要求；新测试一处101字符格式错误已拆行，不改断言。
- 结果与遗留：完整绿阶段会话45522退出0，1419 passed/1 skipped/4 deselected，305.62s（VERIFIED，原300秒确实不足）；日志t02-budget-green.log。独立只读审查复核三处业务问题修复及实际预算diff，均无剩余P1/P2；调整后check、generate/web-check退出0。等待首个提交及发布。

## 9. 验证与交付

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
| T0.2 兼容读待提交 | 同上，预算修复后check退出0 | 1419 passed / 1 skipped / 4 deselected，305.62s，退出0 | 同一真实PG，事务与恢复回归实际运行 | 退出0，契约由命令生成 | 119 passed / 0 failed，类型/lint/5路由构建退出0 |

Python全量使用进程级 `TRAVEL_CLAUDE_CLI` 选定已安装/CI锁定的2.1.295；未改全局CLI/.env/白名单。1 skipped为既有平台专属测试，4 deselected为既有live标记，未新增跳过。

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
