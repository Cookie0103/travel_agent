# 修复：已确认的长期交通偏好仍被文字追问（2026-10-19）

## 现象

线上 5a6ba9f（DeepSeek）：账号有已确认长期偏好 节奏=特种兵、交通=公共交通。合并选择卡正确省略了节奏与交通，但随后助手在文字里问“行程中的市内交通想怎么走，是公共交通、步行还是打车？”。条件面板显示“节奏：特种兵（长期偏好）”，没有交通行。

## 假设与排除

- 合并卡逻辑漏了交通：排除。`MEMORY_COVERS` 已让 transport 组在长期事实存在时省略。
- 节奏同样会被追问：排除。`task_missing` 从不把节奏列为缺项（可选偏好，按标准假设），面板的“长期偏好”是前端读 memory 派生的显示。
- 模型没把长期交通写进 request：属实，但不应靠模型自觉。persona 原先要求模型把长期交通写进 request，DeepSeek 没做。

## 根因

`task_missing` 对 itinerary 在 `request.transport is None` 时把 `transport` 列入 `missing_fields`，不看长期事实；节奏没有这一项，所以只有交通被追问。卡片、缺项两处对“长期交通已知”的判断不一致。路线估算（`estimate_routes`）和校验也在 `request.transport is None` 时拒绝，同样不认长期值。

## 方案

采用：读取时派生默认，不写入 request。
- 新增 `persistence.memory.transport_default`：取 active 的交通事实，本会话 trip 优先于长期，返回(值, scope)。
- `conversation_view/task_missing` 增加 `transport_default`：request 没有交通且有默认时，不列 transport；视图多返回 `defaults.transport = {value, label, source}`，模型可见“交通（长期偏好）：公共交通”。
- 路线估算用默认交通；路线证据 conditions 仍按原 request（transport 为空），不冒充用户本次所说。校验器的路段交通比较用 `request.transport or 默认`。
- 本次聊天明说的交通写入 request，覆盖默认，只对本次有效，长期事实不变（既有行为）。
- persona 与 conversation guidance：不把长期交通写入 request，不在文字里问交通。

不采用：
- 把长期值静默写入 request：违背来源诚实（explicit_fields 落地），也会在面板里伪装成用户本次所说。
- 只改 persona 文案：模型不可靠，服务端缺项仍会列交通。
- 在 `resolve_records` 里全局套用默认：证据 conditions 含 transport，会牵动酒店、预订、计划多处，改动面过大；改为 conditions 保持原 request。

## 实现

- `backend/domain/conversation.py`：`task_missing(..., transport_default=)`、`conversation_view(..., transport_default=(值, scope))`、`defaults` 字段。
- `backend/persistence/memory.py`：`transport_default`。
- `backend/services/conversation.py`、`backend/services/travel.py`：两处视图调用传入默认（上下文快照与 `update_conversation_state` 结果）。
- `backend/services/planning.py`：`routes` 用有效交通；`validate_proposal` 传 `transport_default`。
- `backend/domain/validator.py`：`validate_itinerary(..., transport_default=)`，`route_checks` 比较有效交通。
- `backend/agent/persona.py`、`backend/services/conversation.py` guidance：文案。

## 测试

新增 `tests/integration/test_transport_long_term.py`（真实 PG，离线）：
- 单元：`task_missing` 仅在 request 无交通且有默认时省略 transport。
- 有长期交通：`missing_fields` 不含 transport；合并卡不含 transport 组；`defaults.transport` 为 公共交通/long_term；request.transport 仍为 None；业务上下文的 conversation 一致。
- 无长期交通：仍列 transport，合并卡含 transport 组，无 `defaults`。
- 路线：无本次交通时估算为 transit；本次设 walk 后为 walk；长期事实仍是 transit/long_term/active。

## 改动的既有测试及理由

`tests/test_user_facing_text.py::test_route_missing_transport_message_is_chinese`：`routes` 现在会查询已确认的交通偏好，原测试的服务桩没有 database；改为桩掉 transaction 与 `memory.transport_default`（返回无默认）并传入桩上下文，断言不变（仍是中文“缺少交通”错误）。

## 遗留

- 校验器的路段交通比较使用默认的路径只经 `check` 与路线测试间接覆盖，没有单独的“默认交通下 plan 暂存”集成用例。
- 路线证据 conditions 不含默认交通：用户中途确认了新的长期交通时，旧路线靠校验器的 `route_scope` 冲突发现并重估，而非 stale。
- 前端交通行的“（长期偏好）”展示属前端侧，未改。
