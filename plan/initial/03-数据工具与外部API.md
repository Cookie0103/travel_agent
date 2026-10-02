# 03 数据、工具与外部 API

状态：接口设计与候选服务清单；尚无供应商凭证或真实接入结果。API 的事实来自官方文档，具体端点/版本/权限在获得账号后依据对应文档锁定。

## 1. 哪些数据是必要的

| 数据层 | 支持的任务 | 第一版来源 | 时效与边界 |
| --- | --- | --- | --- |
| 内容层 | 根据兴趣与人群找文章、提取可用建议 | 自写或授权示例内容；自制评测文本 | 记录权利、原文版本与适用范围 |
| 地点层 | 位置、地点身份、开放时间及适用事实 | 自有核验条目；可选 Google Places | 缺失事实保持未知，不能由文章推导实时开放状态 |
| 路线层 | 两个地点之间的时间、出行方式 | 自制路线 fixtures；可选 Google Routes | 测试值、估计值和服务结果分开 |
| 酒店供给层 | 日期/人数条件下的房型、价格、退款政策 | 自制报价 fixtures；获授权 OTA API | 每次报价绑定完整入住条件与取得时间 |
| 用户层 | 当前旅行、偏好与已保存方案 | 用户输入及自有数据库 | 身份隔离，允许修改/删除 |
| 运营层 | 内容覆盖、搜索缺口、草稿变更 | 自有内容与自制/实际匿名化事件 | 模拟经营数据明确标记；不冒充真实公司数据 |

MCP 是工具连接方式，不是旅游数据库。可以把自己的内容查询封装成 MCP；数据仍由自有存储或上表供应商提供。MCP 本身不要求购买一个旅游 API。[W04](06-来源与待验证事项.md#w04)

## 2. 供应商选择

### 优先级

1. 自有内容 + fixture 酒店/路线：保证 Agent、界面和评测能完整开发。
2. 如愿意开通地图账单，选择 Google Places/Routes 的最小字段集做受控在线核验。
3. 酒店优先评估 Booking Demand 与 Agoda Demand 的查询和跳转合作模式；先选一个可实际取得权限的供应商。
4. Expedia Rapid 为可替代供给，不在第一阶段同时集成三家。
5. 通用网页搜索、天气、门票、航班与跨城交通均为后续可选项，只有场景和评测需要时添加。

不把 Rakuten Travel 作为优先供应商，也不把“国家在哪”作为 API 选择标准。选择标准是日本目标城市覆盖、准入、字段、重定向能力、使用权和成本。

### Booking.com Demand API

官方 prerequisites 要求 Managed Affiliate Partner 身份、合同与 Partner Centre 访问，使用 API key 和 affiliate ID。不能假设只注册个人账号即可调用全部接口。[W05](06-来源与待验证事项.md#w05)

官方区分内容、查询后跳转、查询并预订等集成能力；可用产品与权限以合同及 API 版本为准。POC 拟采用查询后跳转，不接收付款、不持有真实预订责任。[W06](06-来源与待验证事项.md#w06)

获得权限后检查目标城市的住宿检索、房型/费用/取消字段、报价确认、可用跳转链接、测试环境及配额。没有权限时只实现自有内部适配契约与测试替身，状态写 `not_connected`。

### Agoda Demand API

官方 Demand 文档区分 affiliate/MSE Search 与不同预订履约模式，并描述合作、凭证、认证到上线的过程。Search-only 模式适合先做查询与跳转；沙箱仍需要凭证，不能假定对匿名用户开放。[W07](06-来源与待验证事项.md#w07) [W08](06-来源与待验证事项.md#w08)

不要把 Agoda Supply/YCS 的酒店渠道库存管理接口当成面向游客的全平台酒店搜索接口。[W09](06-来源与待验证事项.md#w09)

本项目先验证拿到的合作模式是否返回满足比较需要的字段与合法跳转 URL，再编写对应 serializer。不要把不同 Agoda 产品文档中的请求字段和端点拼在一起。

### Expedia Rapid

Rapid 的正式接入需要合作与上线审核，其 lodging 产品提供住宿相关数据与预订链路。作为备选，不承诺免费权限或当前所有合作模式的可用性。[W10](06-来源与待验证事项.md#w10)

### Google Places 与 Routes

Places 可提供地点数据；Place Details 需要 FieldMask，字段会影响 SKU。Routes 支持路线计算，公交功能与计费按对应文档和区域支持核验。地点接口不能替代酒店日期报价接口。[W11](06-来源与待验证事项.md#w11) [W12](06-来源与待验证事项.md#w12) [W13](06-来源与待验证事项.md#w13)

本项目按候选查需要的字段：先匹配地点身份，只对最终候选补必要详情，明确哪些字段会升级收费档位。第一版不调用评论/照片，不做无界区域扫库或全组合路线矩阵。

Places 对存储/缓存和展示归因有限制，place ID 存储有例外；地图展示也有相应要求。RAG 不永久收集 Places 结果，保存计划优先存 ID 和自身安排，第三方事实按允许方式重新获取。[W14](06-来源与待验证事项.md#w14)

Google Maps 条款限制将其内容用于训练、测试、验证或微调 AI/ML 模型。离线 Agent 基准使用自制/明确授权材料，不把 Google 响应制作成模型 benchmark。在线产品核验的方式应在实际使用前核对适用合同和条款。[W15](06-来源与待验证事项.md#w15)

### 当前无需购买的东西

不需要为 MCP 协议付费，也不需要第一天拥有所有 OTA 权限。需要的费用可能来自模型调用、地图请求、部署和具体合作条款。可用免费额度不能替代账单开通要求，也不能当作永远零成本。[W04](06-来源与待验证事项.md#w04) [W16](06-来源与待验证事项.md#w16)

## 3. 内部供应商契约

以下方法是本项目的内部接口，**不是 Booking/Agoda 的官方端点名**：

```python
class HotelProvider(Protocol):
    async def search(self, criteria: HotelSearch) -> OfferSearchResult: ...
    async def details(self, hotel_ref: ProviderHotelRef) -> HotelDetailsResult: ...
    async def refresh_offer(self, offer_ref: ProviderOfferRef) -> OfferResult: ...
    async def handoff(self, offer_ref: ProviderOfferRef) -> HandoffResult: ...
```

Adapter 将内部请求翻译为已获授权的供应商协议；不支持的能力返回 unavailable，不伪造字段。认证、重定向签名和凭证都在后端处理。

`FixtureHotelProvider` 实现相同业务契约，用于确定性测试。`BookingHotelProvider`/`AgodaHotelProvider` 在合同和凭证到位后实现。测试替身通过不代表真实供应商契约验证成功；真实接入必须有对应 contract/sandbox 记录。

不轻易合并跨供应商同名酒店。使用各自原始 ID，只有足够地址/坐标/名称证据时建立经审查 mapping；酒店 identity 相同也不表示房型和 rate plan 相同。

## 4. 核心领域类型

### SourceRef / EvidenceRecord

`source_id, provider, url_or_record_ref, retrieved_at, content_version, data_mode, rights_policy, retention_policy, request_scope, valid_until`。

`EvidenceRecord` 还记录 `entity_type, entity_id, field_path, value_or_allowed_ref, applicability, derivation`。原始响应是否能存储由权利策略决定；禁止持久化时仅存允许的引用与本系统必要审计信息。

### TravelRequest

`city, start_date, end_date, timezone, adults, child_ages, rooms, hotel_budget, total_budget, currency, transport_mode, interests, booked_stay, hard_constraints, soft_preferences, revision`。

每个用户条件包含 `value, source=user/default/memory, source_turn, confidence`。未知使用 null，不用“默认两个成人”冒充已知人数。相对日期解析附基准日期与时区，跨月/跨年含糊时确认。

### Article / Place

- Article：原文/版本、标题、语言、城市、标签、人群、章节、发布时间、核验时间、rights。
- Place：内部/供应商 ID、原名/别名、坐标、类别、字段级 evidence、开放时间覆盖、适用条件。
- 编辑自有描述与第三方属性分别存储；冲突不强行覆盖，记录两条来源与采信理由。

### HotelOffer

`provider, provider_hotel_id, room_ref, rate_ref, checkin, checkout, occupancy, room_count, currency, base_amount, tax_amount, fee_amount, payable_total, price_scope, meal_plan, cancellation_terms, refundable_status, quoted_at, expires_at, data_mode, source_ref`。

退款状态为 yes/no/unknown，不能看到“免费取消”四个字就忽略截止时间、时区或条件。价钱用 Decimal 和货币单位，禁止 float 累加造成报价误差。

报价比较键包含入住日期、入住人/儿童年龄、房间数、计价范围、餐食与退款条件。税费不全显示“总价未完整确认”，不能拿未知税费的基础价排出“最便宜”。POC 只展示 JPY 同币种比较，缺少实际汇率时不做换汇。

### Itinerary / ConstraintReport

`plan_id, version, request_revision, dates, items, selected_offer_refs, assumptions, evidence_refs, created_at`。

每个 item 有 place/article refs、计划开始与结束、停留估计、route refs；检查结果为 `verified / partial / unknown / conflict`，附冲突代码和依据。这里只是对已知约束的验证，不是对现实旅行安全或完全可行的保证。

### ContentChangeDraft

`draft_id, owner_principal, article_ids, source_versions, changed_fields, diff, rationale, evidence_refs, expires_at, status, idempotency_key`。禁止 Agent 设置审批主体或已批准状态。

## 5. 拟提供的工具

| 工具 | 最小条件 | 返回内容 | 级别及关键检查 |
| --- | --- | --- | --- |
| `search_content` | 查询或当前兴趣；可选城市 | 文章 ID、摘要、相关性依据 | read；权利和地区过滤、结果上限 |
| `get_article` | 当前允许访问的 article ID | 授权章节、版本及 sources | read；访问隔离、内容大小限制 |
| `search_places` | 地区和检索意图 | 候选地点 refs | read；范围、配额、来源策略 |
| `get_place_facts` | 地点 ref、所需字段 | 开放时间等 nullable facts | read；FieldMask、时效与归因 |
| `estimate_routes` | 有效地点 refs、交通方式/时间 | 路段结果、覆盖和来源 | read；限制边数，禁止无界矩阵 |
| `search_hotel_offers` | 日期、人数/儿童年龄、房间数 | 报价 refs 和可比较字段 | read；先校验 request，不静默补人 |
| `refresh_hotel_offer` | 已见且当前适用 offer ref | 新报价/不可用/变化 | read；核对适用条件与变化 |
| `compare_offers` | 至少两个当前 offer refs | 确定性价差与条件差异 | read；同币种/口径、缺失字段检查 |
| `plan_itinerary` | request snapshot + 合法候选 | 受限委派的结构化方案 | read/compute；共享预算、不能写入 |
| `validate_itinerary` | 结构化草案 | 冲突、未知项和检查范围 | compute；确定性逻辑 |
| `present_travel_result` | 合法对象/证据 ID | 服务端补全卡片 | presentation；不接受任意事实 URL/金额 |
| `save_plan` | 已校验草案、当前 revision、用户保存意图 | 保存版本与内部访问地址 | local write；ownership、幂等、旧请求隔离 |
| `get_saved_plan` | 自己的 plan ID | 历史计划及待刷新项 | read；不能读取别人的计划 |
| `get_booking_handoff` | 有效 offer ref、已启用供应商 | 供应商允许的跳转链接 | read；后端生成/校验，不冒充订单 |
| `analyze_content_coverage` | 运营角色、时间/地区范围 | 自有汇总与内容证据 | read；匿名化、无模拟成绩冒充 |
| `stage_content_change` | 已读原文、字段白名单与版本 | 草稿与 diff | draft；证据与范围 gate |
| `discard_content_change` | 自己有权管理的草稿 | 撤销结果 | local write；状态检查 |

`apply_content_change` 只供带身份的宿主确认入口调用，默认不出现在模型工具集合。模型不能通过把工具名写出来获得这个动作。

工具集合按角色/阶段/权限裁剪；对普通读者不暴露运营工具，对测试模式不暴露真实预订操作。注册表与执行器同时验证，不只依赖 prompt 告诉模型不要调用。

## 6. 测试、沙箱与真实模式

| 模式 | 数据来源 | 能证明什么 | 不能宣称什么 |
| --- | --- | --- | --- |
| `fixture` | 自制确定性数据 | Agent 逻辑、来源约束、异常恢复、交互 | 实时库存、真实价格或供应商认证 |
| `sandbox` | 获授权的供应商测试环境 | 对应测试协议和错误处理 | 已上线或真实可订 |
| `live` | 正式凭证及允许接口 | 当次查询的数据与集成结果 | 持续准确、价格不变、全量覆盖 |

界面在结果层显示数据模式与取得时间，不仅在 README 写小字。fixture 酒店名称和报价必须明确为虚构，不能编造成真实酒店的当日房价；路线数值标为测试值。

种子规模建议：40 篇自制短文、50 个测试地点节点、12 个虚构酒店、40 个日期/退款组合报价、若干查询和运营日志。数量是开发用建议，实际构建时记录最终规模；真实 Kyoto 地点事实另用来源明确的少量核验条目，不与虚构报价混为一体。

第一批 fixture 特意覆盖：结果为零、条件冲突、地点别名、未知时间、跨午夜、儿童政策缺失、税费缺失、不可退/可退价差、过期报价、库存变化、同名不同酒店和恶意描述。

## 7. 成本控制

预算以配置限制，不在文档承诺特定月费：模型调用/token、每轮读取次数、每个供应商请求数、每日和每月额度都可独立设置。达到预算停止新增请求，输出部分结果；不将供应商账单告警当作已经实施的硬限额。

模型成本估算为各调用输入/输出/缓存类别用量乘以当天锁定的价格表；地图成本按实际字段、请求种类和当前 SKU 计算。子任务、记忆、评测调用都计入，不能只报主 Agent 的一次回答成本。

Google 当前价格和免费额度按官方 SKU 页面查，不沿用旧版“统一月赠金额”的印象。[W16](06-来源与待验证事项.md#w16) 模型价格在实际 P0 调用前重新查询，[DeepSeek 官方定价](https://api-docs.deepseek.com/quick_start/pricing)。OTA 合作费用、流量限制和展示条款目前未知，写入待验证清单，不填猜测数字。

## 8. 凭证到位前后的工作边界

现在可完成：内部契约、fixtures、Agent 与 UI、故障模拟、离线评测、来源策略、接口申请清单。

有凭证后完成：确认可用 API/版本 → 按授权文档实现 → 测试环境契约测试 → 审核要求 → 受控真实查询 → 记录覆盖/字段/成本 → 更新接入状态。

这次计划编写不执行申请、支付或供应商网络调用。未来开发中的真实接入以获得的授权为准，不采用抓取登录页面来假装 API 已接通。
