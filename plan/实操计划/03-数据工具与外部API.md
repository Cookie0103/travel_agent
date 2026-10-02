# 03 数据、工具与外部 API

本文定义领域字段与工具契约；供应商端点以获准使用的官方文档为准，来源集中见 [06](06-来源与待验证事项.md)。

## 1. 数据选择

| 数据 | 开发时来源 | 实际接入候选 |
| --- | --- | --- |
| 攻略与内容 | 自写/授权文章、段落、标签与原文版本 | 可获授权的内容服务 |
| 地点 | 自制地点 fixtures、少量有来源的真实条目 | Google Places |
| 路线 | 自制有时间和方式维度的路段 | Google Routes；目标城市覆盖待实测 |
| 酒店 | 明确虚构的房型/日期/退款组合 | Booking Demand 或 Agoda Demand，先接一家 |
| 个人条件与方案 | 用户输入、自有数据库 | 不依赖外部平台 |

接入约束：Booking 需要合作方身份、合同和凭证；Agoda 按合作模式获取权限；Places 使用 FieldMask 并遵守缓存/归因政策；路线按城市、方式和时间实测。对应官方文档见 06。

先跑 fixtures，M4 争取接入一个真实地点/路线适配器；酒店资格可并行申请。逐供应商标记 fixture/sandbox/live/not_connected 和获取时间，不生成虚假报价或预订链接。

## 2. 领域模型

| 类型 | 关键字段与规则 |
| --- | --- |
| TravelRequest | city、日期与时区、adults/child_ages/rooms、预算/币种、交通方式、兴趣、已订住宿、硬/软条件、revision |
| RequestPatch | expected_revision、source_turn、字段操作 set/clear；省略表示不变；冲突返回 conflict |
| Article | article_id、标题、正文段落、地点引用、标签、语言、source/version、权利信息 |
| Place | place_id、provider_id、原名/别名、坐标、类别、字段级 evidence |
| HotelOffer | offer_id、provider_hotel_id、room/rate_ref、入住条件、币种、base/tax/fee/total、餐食、退款条件、quoted_at/expires_at |
| Itinerary | plan_id、version、request_revision、日期、items、selected_offer_refs、assumptions、检查报告 |
| ItineraryItem | 稳定 item_id、place_ref、开始/结束、停留估计、route_refs、用户锁定标记 |
| PlanPatch | base_version、add/update/remove(item_id)、修改字段、理由；新增 ID 由服务端生成 |
| PlanDraft | draft_id、owner、base_version、request_revision、patch、diff、report、expires_at、status |

用户条件保留来源/轮次。文章查询允许条件不完整；酒店查询必须有准确日期、人数、儿童年龄和房间数，不以规划假设代入报价。

金额使用 Decimal；第一版统一 JPY。相同日期、入住人、房间数和价格口径才可比较总价；餐食/退款差异单列。缺少税费时不能按基础价声称最便宜，未知成本也不能通过“满足硬预算”校验。

## 3. 证据记录与生命周期

EvidenceRecord：`evidence_id, entity_id, field_path, value_or_allowed_ref, provider, source_ref, content_version, retrieved_at, valid_until, applicability, retention_policy, data_mode`。

EvidenceBinding：`evidence_id, run_id, applicability_fingerprint`，记录当前 run 的读取授权和适用条件。模型选 ID，服务端补事实值/URL；原始内容按来源政策留存，恢复优先用允许保存的 ID 重新查询。

| 变化 | 处理 |
| --- | --- |
| 日期/人数/房间变化 | 酒店报价失效；刷新后产生新 offer/evidence ID |
| 交通方式/出发时间变化 | 相关路段失效，重新估算 |
| 景点更换 | 重新校验新景点及相邻路段，不清空无关文章 |
| 仅追问解释 | 不改 request revision，不无条件刷新全部事实 |
| 恢复历史方案 | 先验证 ownership；历史事实可标“当时记录”，用于当前推荐前重新核验并绑定到新 run |

拒绝跨用户和未授权证据；共享公开数据、历史自有计划通过受控读取重新绑定，不能一概拒绝跨 run 恢复。

## 4. 工具清单

每项 ToolSpec 声明 schema、effect(read/state/draft/presentation)、前置条件、timeout、结果上限、成本和调度规则；身份、run、attempt 与幂等上下文由宿主注入。

| 工具 | 输入与输出 | 关键规则 |
| --- | --- | --- |
| update_travel_request | 用户明确条件 → 已提交 request/差异 | set/clear、不变保留、检查 expected revision |
| load_skill | 注册名 → 指令与版本 | 白名单、去重，不扩权 |
| search_content / get_article | 查询/文章 ID → 段落及引用 | 城市硬过滤，先关键词和别名，软偏好可显式放宽 |
| search_places / get_place_facts | 查询/地点 ID → 可核验属性 | 保留原名、提供字段级来源 |
| search_hotel_offers / refresh_hotel_offer | 已提交入住条件/offer ID → 报价 | 参数完整、明确有效期、区分空结果和不可用 |
| estimate_routes | 起终点、方式、时间 → 路段 | 限制边数；候选改变需重新计算 |
| validate_itinerary | 草案或 patch → ConstraintReport | 确定性校验，可被展示/保存再次调用 |
| present_travel_result | 组件类型、对象 ID、建议 → 卡片 | 只读补全；报价比较由服务端计算；错误 ID 不静默消失 |
| stage_plan_change | 初始草案/PlanPatch → draft/diff/report | 不修改正式计划；原子保存草稿 |
| get_saved_plan | 自有 plan ID → 历史方案/待刷新项 | ownership，重新绑定证据 |
| delegate_plan（M3 实验开关） | 固定请求、计划与候选 → proposal/PlanPatch | 只读白名单、父级共享预算、输出由主端重验；关闭时不注册 |

正式保存走宿主确认 API，委派权限见 [02](02-Agent架构与实现设计.md)。供应商可用后，宿主用核验过的 offer 生成跳转 URL，不由模型生成。

统一结果：
```json
{"status":"ok","data":{},"evidence_ids":[],"data_mode":"fixture","warnings":[],"error":null}
```
错误类别沿用 [02](02-Agent架构与实现设计.md)。错误包含可执行的 next_action/missing_fields；返回模型的数据有字段和长度上限，完整大结果放允许的服务端存储。

## 5. 行程校验与局部修改

模型负责选择候选和安排顺序；代码负责：
1. 日期/时区、开始结束、停留和交通间隔、重复项。
2. 已知开放时间及覆盖日期；没有查到不等于已确认营业。
3. 预算已知项、估计项与未知项；住宿晚数和入住条件匹配。
4. patch 的 base_version、item_id、锁定项和变更范围。
5. 应用局部改动后重新检查相邻路线，以及全局日期、预算和重复安排。

检查项标 verified/unknown/conflict，汇总 complete/partial/conflict，模型不得覆盖。未知项标明后可保存部分方案；硬冲突须修正或由用户改条件，修正轮数有上限。

相同地点可能多次访问，因此不能用 place_id 代替 item_id。未涉及的 item 内容由服务端保留，不让模型重写整份已保存方案。

## 6. 数据与成本准备

M0 小规模即可：建议 12 篇自制短文、20 个测试地点、6 家虚构酒店及不少于 12 种报价组合，后续按失败用例扩充。测试数据包含空结果、同名地点、过期/缺税报价、闭馆、跨午夜、少儿条件缺失和恶意描述。

内部适配器：`HotelProvider.search/refresh/handoff`、`PlaceProvider.search/details`、`RouteProvider.estimate`。Fixture 测内部契约，真实适配器另做 contract/smoke。

接入时核实价格、免费额度、供应商日/月预算以及响应留存/评测权限；费用控制见 02。评测使用自制或获授权数据。
