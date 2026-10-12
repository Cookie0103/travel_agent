# 03 数据、工具与外部 API

本文定义领域对象、工具契约和数据来源。执行流程见 [02](02-architecture.md)，来源依据见 [06](06-sources.md)。

## 1. 数据来源

| 数据 | 来源 | 处理方式 |
| --- | --- | --- |
| 攻略文章 | Wikivoyage 京都条目（CC BY-SA），可补少量自写 | 导入脚本切成段落，存原文版本和署名信息 |
| 景点 | OpenStreetMap（ODbL），通过 Overpass 导出京都范围的快照 | 名称、别名、坐标、类别、`opening_hours`；存快照日期 |
| 路线 | 自制路段表 | 两点间步行、公交的估算时间；标为「估算」 |
| 酒店与报价 | 虚构：约 6 家酒店、≥12 种房型 / 日期 / 退款组合 | 界面标「模拟」 |
| 预订 | `mock_supplier` 假供应商 | hold、下单、按 `client_ref` 查询，可注入故障 |

- 数据都是**导入后的本地快照**，开发和评测时不实时调外部服务，保证结果可复现。
- 每条数据都带 `data_mode`（`fixture` / `snapshot`）和获取时间。
- 不生成虚假的真实报价或预订链接。
- 许可条款在导入前核对：Wikivoyage 要求署名并以相同协议共享；OSM 要求署名。

## 2. 领域对象

| 对象 | 关键字段与规则 |
| --- | --- |
| TravelRequest | city、日期与时区、adults / child_ages / rooms、全程预算与币种、可选住宿预算区间/口径、字段来源、交通方式、兴趣、硬条件 / 软条件、`revision`；新增契约见 [ADR-015](../adr/015-lodging-budget-and-condition-source.md)，实施见批次 T3.3/T3.7 |
| RequestPatch | `expected_revision`、来源轮次、字段操作（set / clear）。没写的字段表示不变；版本不符返回 conflict |
| Article | article_id、标题、段落、提到的地点、标签、来源与版本、署名信息 |
| Place | place_id、OSM id、原名 / 别名、坐标、类别、营业时间、字段级来源 |
| HotelOffer | offer_id、酒店、房型、入住条件、币种、基础价 / 税 / 费 / 总价、早餐、退款条件、`quoted_at` / `expires_at` |
| Itinerary | plan_id、`version`、`request_revision`、日期、items、选中的报价、假设、校验报告 |
| ItineraryItem | 稳定的 `item_id`、place_ref、开始 / 结束时间、停留时长、路段引用、是否被用户锁定 |
| PlanPatch | `base_version`、增 / 改 / 删（按 item_id）、修改理由；新 item 的 ID 由服务端生成 |
| PlanDraft | draft_id、owner、base_version、request_revision、patch、改动对比、校验报告、过期时间、状态 |
| Booking | booking_id、offer_id、`client_ref`、状态（quoted / held / confirmed / booked / failed / unknown / expired）、hold 到期时间、供应商订单号、状态变更历史 |

规则：
- 查攻略时条件可以不完整；查酒店报价必须有准确日期、人数、孩子年龄和房间数，不能用「假设」代入。
- 金额用 `Decimal`，第一版统一日元。
- 只有日期、人数、房间数和价格口径（是否含税）都相同，才能比较总价；早餐和退款的差异单独列出。
- 缺少税费时，不能说「最便宜」；成本未知时，不能判定「满足预算」。

## 3. Evidence：事实的来源和时效

```text
EvidenceRecord: evidence_id, entity_id, field_path, value, provider, source_ref,
                content_version, retrieved_at, valid_until, data_mode
```

- 模型只引用 `evidence_id`，服务端按 ID 填入实际值和来源。
- 每条 Evidence 记录它适用于哪个 TravelRequest revision。

条件变化时，哪些 Evidence 失效：

| 变化 | 处理 |
| --- | --- |
| 日期 / 人数 / 房间变了 | 酒店报价失效，重新查询生成新的 offer 和 evidence |
| 交通方式 / 出发时间变了 | 相关路段失效，重新估算 |
| 换了某个景点 | 重新校验这个景点和前后路段，其他不动 |
| 用户只是追问解释 | 条件不变，revision 不变，什么都不刷新 |
| 打开历史行程 | 先检查是否本人的；历史报价标为「当时价格」，要用于新推荐必须重新查询 |

## 4. 工具清单

每个工具声明：参数 schema、类型（read / state / draft / presentation / side_effect）、前置条件、超时、返回长度上限。用户身份、run_id 由系统注入，不由模型传。

| 工具 | 输入 → 输出 | 关键规则 | MCP |
| --- | --- | --- | --- |
| `update_travel_request` | 用户明确说出的条件 → 更新后的条件和差异 | set / clear；检查 expected_revision | 否 |
| `update_conversation_state` | 已授权任务与当前追问 → 有界待办状态 | 本人当前运行、expected_revision；仅追问实际缺项，完成由工具结果确定；见 ADR-014 | 否 |
| `load_skill` | 注册名 → 指令文本和版本 | 只接受白名单；同一段上下文只加载一次 | 否 |
| `search_content` / `get_article` | 关键词 + 城市 / 类别过滤 / 文章 ID → 段落及引用 | 城市是硬过滤；关键词 + 别名匹配 | 是 |
| `search_places` / `get_place_facts` | 关键词 / 类别 / 地点 ID → 属性及来源 | 保留原名；营业时间未知时返回 unknown | 是 |
| `search_hotel_offers` / `refresh_hotel_offer` | 已确认的入住条件 / offer ID → 报价 | 参数必须完整；明确有效期；区分空结果和不可用 | 否 |
| `estimate_routes` | 起点、终点、方式、时间 → 路段 | 限制一次查询的路段数 | 否 |
| `validate_itinerary` | 行程草案或 patch → 校验报告 | 纯代码；展示和保存前都会再调一次 | 否 |
| `present_travel_result` | 组件类型、对象 ID → 卡片 | 只读补全；比较价格由服务端算；ID 无效时报错，不悄悄丢掉 | 否 |
| `stage_plan_change` | 初始草案 / PlanPatch → 草稿、改动对比、校验报告 | 不改正式行程 | 否 |
| `get_saved_plan` | 自己的 plan ID → 历史行程、需要刷新的项 | 检查归属 | 否 |
| `hold_hotel` | offer ID → Booking（held） | 只能用本会话查到过的 offer；返回 hold 到期时间 | 否 |

- 正式保存和下单**没有对应的模型工具**，只能通过页面确认 API（02 §6.2、§6.3）。
- 表中「MCP」仅指 M3.3 的对外服务；标「是」的只读工具对外提供。SDK 内部的进程内 MCP 桥接也可调用条件修改、草稿、模拟 hold，但仍经过同一 ToolExecutor；确认保存和下单只走独立 API。内部桥接、对外服务和直接调用共用业务实现与测试。

工具统一返回格式：

```json
{"status": "ok", "data": {}, "evidence_ids": [], "data_mode": "snapshot", "warnings": [], "error": null}
```

- `status` 取值：`ok` / `empty` / `error`。因为 DeepSeek 会忽略 `is_error`，所以状态必须写在正文里。
- 出错时 `error` 包含错误码（见 02 §8.3）和下一步建议（如 `missing_fields: ["child_ages"]`）。
- 返回给模型的数据有长度上限；完整结果存在服务端，模型拿到的是摘要和 ID。

## 5. 行程校验与局部修改

模型负责选景点、排顺序；代码负责检查以下内容：
1. 日期和时区、开始 / 结束时间、停留时长、路段时间够不够、有没有重复安排。
2. 营业时间：用 OSM 的 `opening_hours` 判断。查不到营业时间时标「未知」，不能当成「营业」。
3. 预算：分已知、估算、未知三类；住宿晚数和入住条件要对得上。住宿预算是全程分项，按用户原话保存；关系由 validator 现算，下限超全程为 conflict，仅上限超为 warning，数量/币种不可比时 unknown；冲突先追问、解决前不比较酒店，草稿不可确认。区间/来源/兼容规则唯一详述见 ADR-015。
4. patch：`base_version` 是否最新、item_id 是否存在、是否动了用户锁定的项。
5. 局部修改后：重新检查改动处前后的路段，以及整体的日期、预算和重复安排。

每项检查结果标 `verified` / `unknown` / `conflict`，汇总为 `complete` / `partial` / `conflict`。模型不能改写校验结果。
- 节奏密度提醒沿用 `unknown`/`partial`：标准每天4–5、佛系/轻松（记录为慢节奏）每天2–3、特种兵每天6–8个不同景点为完整游玩日目标；首末日按抵达/返程可用时段调整，不为凑数重复。已核实景点按日本日期统计，超过各档上限才提醒；节奏未说明先追问，不写成标准。2026-10-10用户要求全程不重复：同place_id游览两次及以上（同日/跨日/不同Evidence）为 `conflict`，保留旧 `repeated_place_warning` 检查码兼容前端，中文标“重复景点冲突”。Python校验在暂存（含幂等回放）与确认时重新检查并阻止重复候选；模型按反馈选全程未用的有来源候选，重估相邻路线与时刻，再校验。缺候选/超修复额度时说明未完成，校验器不随机改行程。住宿、餐食、交通往返排除；Google完整types按共享类别规则识别，明确非游览用途优先。未知类别/来源保留未知，不能宣称已核实去重；已确认历史版本不回写。
- 有未知项可以保存，但要标明；
- 有硬冲突必须修正，或者由用户放宽条件。

酒店、餐食和中转地点可能必要往返，且局部修改必须精确定位，所以用 `item_id` 而不是 `place_id` 标识行程项；游览景点仍按全程 `place_id` 去重。没被修改的项由服务端原样保留，不让模型重写整份行程。

## 6. 假供应商（mock_supplier）

一个独立的小 FastAPI 服务，模拟酒店供应商：

| 接口 | 行为 |
| --- | --- |
| `POST /holds` | 锁房，返回 hold_id 和到期时间 |
| `POST /orders` | 带 `client_ref` 下单；同一个 `client_ref` 只会生成一个订单 |
| `GET /orders?client_ref=` | 按 `client_ref` 查订单状态（用于对账） |

故障注入（通过请求头或配置开启，只用于测试和演示）：
- 延迟 N 秒；
- 返回 429 和 `Retry-After`；
- 返回 500；
- **订单已创建但响应丢失**：最关键的场景，用来验证对账流程。

## 7. 测试数据准备

M0 先准备小规模数据：约 12 段攻略、20 个景点、6 家虚构酒店、≥12 种报价组合。之后按失败用例扩充。

数据中必须包含这些边界情况：
- 空结果、同名地点；
- 过期报价、缺税报价；
- 闭馆日、跨午夜；
- 缺少孩子年龄；
- 攻略段落里藏着「忽略之前的指令」之类的恶意文本。
