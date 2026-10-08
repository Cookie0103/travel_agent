# ADR-014：归属隔离、有界分页的旅行与对话历史

状态：接受，2026-10-08；依据用户 D2、批次 R1 与 design/02 §5–§7。本 ADR 先确定契约，T1.1 起实施；不新增依赖、表或运行时，不自动重放消息。

## 背景与选项

当前服务端已有 sessions、task_runs、run_events、正式行程及归属索引；浏览器只缓存一个 run/plan，无法列出旅行或恢复完整多轮。选择两个增量只读接口，复用 services → persistence 与现有事件/行程读回；不选 localStorage 全历史（两份真相、换设备丢失），不选重跑模型恢复（重复费用/写入）。

## 契约

- `GET /sessions?limit=20&cursor=…`：Bearer 当前用户；返回 `{items, next_cursor}`。items 含 `session_id, created_at, city, start_date, end_date, plan_id, current_version, last_activity_at`。无条件字段为 null；只有正式版本存在时返回 plan_id/current_version（否则 null），不将未确认草稿当已保存旅行。
- 列表按 `(created_at DESC, session_id DESC)` 排序，以不可变创建键作 keyset 分页；后续对话/确认不改变分页位置。`last_activity_at` 是已有可核实时间的最大值：会话创建、轮次创建/结束、当前正式版本 saved_at；没有独立的手填更新时间，不冒称覆盖所有条件编辑。UI 显示为“最近对话/保存”，不是完整审计时间。
- `GET /sessions/{id}/runs?limit=20&before=…`：先验证 session 归属；返回 `{items, next_before}`。按 `(created_at DESC, run_id DESC)` 取最近页，页内按正序返回供渲染；翻页读取更早轮次，前端按 run_id 合并、排序。
- 每轮含现有 RunView 字段，加 `prompt` 与可选 `draft_id`；包括运行中、失败、取消轮次，不仅 completed。presentations 使用既有持久化事件读取，维持现有每轮最多 4 项的界限；draft_id 从本轮草稿 presentation 推导，不能取当前 session 的全局草稿。历史读回不调用工具或模型。
- limit 范围 1–50；游标为版本化 base64url 的时间/UUID 边界，最大 256 字符；非法类型、时间、UUID 或越界 limit 返回 422。游标不是授权凭据，SQL 始终带当前 user_id 与 session_id 约束。相同时间的 UUID 决定稳定顺序，limit+1 判断下一页；空列表 items=[]、游标 null。
- 未认证/过期身份返回 401；未知或其他用户的 session 统一 404，不泄漏存在性。数据库不可用沿用现有 503/unavailable，不能转为空列表。

## 实现边界与兼容性

- 查询归属、聚合和 keyset 位于 persistence；services 负责认证后用例/DTO；API 不越层访问数据库。保持已有 /sessions/{id}、/runs/{id}、SSE、正式行程读取接口原契约。
- localStorage 只保留 token 与当前 session_id；身份有效性以服务端认证为准。未获接受回执的 pending message（client_message_id/text/mode）迁移到当前标签的 sessionStorage 临时 outbox，绑定身份与 session_id；401 后失效，不能转发到新身份；刷新仍保留原幂等键；服务端接受后清除，切旅行不错误重放。新标签从服务端历史恢复，不自动重试其他标签的 outbox。不存第二份历史轮次或正式行程列表。
- 旧前端 + 新后端不受两个增量接口影响；新前端遇旧后端的新增接口 404 时显示“当前服务版本暂不支持旅行历史”，保留已有条件/对话入口，不冒充空历史、不新建身份来恢复。完整历史能力待前后端均更新。
- **已知限制（REASONED）**：RunService 对实时 answer 有内存保留/落库固定说明的现有策略。历史接口只能返回已持久化内容，不能把 live_answers 当跨重启事实；T1.2 须实际核对实时回复/卡片恢复与来源数据保留边界，不把“列出轮次”冒称“原回复完整恢复”。本 ADR 不授权额外保存供应商原始数据或 SDK transcript。

## 必须验证

真实 PG：两用户隔离/未知 session、空 session/空历史、两页含相同时间键、不重复不漏旧轮次、页间新增消息、limit/游标错误、数据库失败。前端：多轮刷新/导航、确认后回复仍可见、历史前插去重、不重跑模型、(session,run) 迟到事件丢弃。轮次读取不能因草稿过期而删除整条历史或正式版本。

## R2 补充：轮次业务结果（2026-10-08，T2.1 前确定）

- `RunView` / `HistoricalRun` 增量可空字段 `business_result`，既有 runtime `status/error_code` 不变。结果是带 kind 的对象：`answer_only`；`draft_staged` 含 draft_id、plan_id、validation_status（complete/partial/conflict）；`stage_failed` 含应用 ErrorCode 与安全 reason（plan_exists/patch_invalid/repair_limit/other）；`confirmed` 含 plan_id、version。没有模型回复文本或供应商原始结果。
- 可信来源是共用 execute_observed 的 stage_plan_change 返回结果，写入既有 tool_finished 事件的新可空 business_result 元数据；成功必须有合法草稿/计划UUID及服务端validation状态，失败取工具应用码和白名单原因。普通 get_saved_plan/present/read工具不能把读取已有计划冒充本轮确认；回复出现“已保存”不能产生 confirmed。SDK和离线沿同一事件转换，不写新运行时。
- Run GET/history 从本轮最后一次 stage 事件推导（失败后成功以最后一次为准）；最后是 tool_started 而没有结果时返回null，草稿事务可能已提交，不能推断answer_only或借用前次结果。无 stage 才 answer_only，运行尚未产生业务结果时可为空。新事件有结构化结果；旧 stage失败只能给应用码/other；旧 stage成功没有新结构化元数据时为空，不能拿presentation猜其草稿（展示可指向同session另一run，且不保证对应最后stage）。不回填旧成功，不能冒称回答完成或确认。
- 确认是独立用户API动作，确认事务不依赖模型run。读取业务结果时，只有原本轮草稿的 PlanDraftRow 在同user/session且confirmed_version非空，才投影 confirmed(plan_id,confirmed_version)；不是当前旅行另一个草稿/当前计划版本。不追加确认事件、不反复确认、不回放工具。草稿报告显示的是暂存时的validator结论；草稿有效期和实时引用仍由现有读回/确认再校验约束。
- 复用 run_events JSONB 和 PlanDraftRow，不加表/列/迁移。事件私有且与run归属一致；event_metadata保持这组小元数据，公共trace仍不导出业务ID/回复。列表分页、最多4项presentation与供应商内容保留策略不变。
- 前端状态从该字段显示“回复完成/草稿已暂存未保存/校验冲突不能确认/草稿未生成/已确认Vx”，runtime取消/失败仍可独立显示；不会从模型文字推断保存。新前端遇缺字段旧服务显示业务状态未提供，不用客户端猜结果；旧前端忽略增量字段。conflict确认继续由服务端拒绝。
- 验证：阶段失败但runtime成功、conflict草稿、普通查询、失败→成功/成功→失败、无presentation但stage成功、最新stage中断没有结果必须未知、旧多stage/错序展示必须未知、确认后GET/history与重启一致、其他run/其他session引用不能确认；真实PG版本不增、无副作用/付费调用。工具元数据单测与实际服务/PG/浏览器验收分别记。

## R4 补充：酒店分组与现有报价上限（2026-10-08，T4.1 前确定）

- 复用现有平面offers/cards与hotel_id；不增加接口/字段/表，不扩大每次工具最多6条报价或供应商调用次数。search limit现表示不同酒店数（1–6），按首晚/本地目录上游顺序选择；每家最多展示2条不同rate_id，整体最多6条。先保每家第一条，再用剩余容量保第二条；重复rate_id不占名额。不够如实显示实际酒店/套餐数量，不宣称供应商所有套餐已覆盖。
- 页面用hotel_id分组，一家一张卡，房型/套餐选择只改变本地所选offer；价格、来源、过期、预算与行动都绑定所选完整offer_id/evidence_id，不混用同酒店另套餐。新报价到达时旧offer不再存在就回退该组第一条，不自动hold/choose/confirm。名称不同同ID仍同一家，名称相同不同ID仍不同家。
- 多晚依旧按同rate_id逐晚核对，保未知总价/现有调用与8K工具输出上限；整体报价超长仍以整条截断且告知数量不足。输出压缩不能偷偷按价格排序（D7），其余保持上游顺序。旧前端仍能读平面cards，新前端可分组旧cards；无存储迁移，回退不改报价事实。
- 取舍：不把max报价扩成12或增加酒店调用来保全所有套餐；在现有6条上限内先覆盖不同酒店，再保有限第二套餐。本批最多酒店数不变，下一批8家/完整排序留附录A。验证同酒店两套餐、同名不同ID、重复rate、不够四家、多晚同计划与无额外请求、卡内切换价格/ID/过期/行动绑定。
