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
