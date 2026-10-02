# 02 Agent 架构与实现设计

本文说明 Agent 怎么运行：一次请求经过哪些模块，状态存在哪里，出错时怎么办。
领域字段见 [03](03-数据工具与外部API.md)，测试标准见 [05](05-评测与验收.md)，上游依据见 [06](06-来源与待验证事项.md)。

## 0. 先读这 6 个概念

| 概念 | 一句话解释 | 例子 |
| --- | --- | --- |
| TravelRequest | 用户当前的旅行条件，结构化存储，带版本号 `revision` | `{city: 京都, nights: 2, adults: 2, child_ages: [6], revision: 3}` |
| Evidence | 一条有来源、有时效的事实 | 「某酒店 11/3 两晚总价 ¥42,000」，来源 fixture，有效到 11/1 |
| Itinerary / PlanPatch | 行程，以及对行程的一次局部修改 | 「把第 2 天 14:00 的 item_7 换成 place_32」 |
| TaskRun | 一次用户消息引发的一次 Agent 执行，有状态和断点 | `running`，已完成 3 步，断点在第 4 步 |
| Booking | 一次模拟预订，是一个状态机 | `quoted → held → confirmed → booked`（或 `failed` / `unknown`） |
| Trace | 一次执行中每次模型调用和工具调用的记录 | 在 Langfuse 里看到的时间线 |

## 1. 一次请求的主调用链

```text
用户在网页发消息
  → FastAPI：消息去重，创建 TaskRun，返回 run_id
  → Agent Runtime（后台 asyncio 任务）
      ┌─ 组装上下文：system prompt + 工具列表 + 当前 TravelRequest + 近期消息
      ├─ 调模型（ModelProvider）
      ├─ 模型要调工具 → ToolExecutor 校验 → 执行 → 结果写库、登记 Evidence
      ├─ 模型提出行程 → Validator 校验 → 不通过就把冲突反馈给模型修正
      └─ 每完成一步：写断点、写事件
  → SSE 把事件推给网页
用户点「确认」/「预订」→ 走独立的 API，不经过模型
```

分工原则：**模型决定下一步做什么；代码保证做的事是对的。**
- API 负责身份和收发；
- Runtime 负责循环和上下文；
- ToolExecutor 负责工具调用合不合法；
- Domain 负责业务规则（预算、营业时间、预订状态）。

## 2. 从 Commerce Agents 沿用什么、改什么

| 上游 | 本项目怎么处理 |
| --- | --- |
| `shopping_agent_runtime/orchestrator.py` 的有界工具循环 | 沿用思路：循环上限、最后一轮强制不调工具、中断时补齐未配对的工具结果。替换购物相关的预取、prompt 和结束条件 |
| `commerce_common/execution.py`、`presentation.py` | 参考统一执行入口和「模型给 ID、服务端补数据」的展示方式 |
| `shopping_agent/gates.py` | 沿用「代码守门」思路：只能用本次会话查到过的 ID，预订必须有页面确认标记 |
| `commerce_common/skills.py`、`prompt_assembly.py` | 沿用：静态 prompt 和工具列表固定不变，动态内容单独一段 |
| `examples/travel/api/itinerary.py` | 学习按 ID 补全行程卡片；注意它在补全时会调用 `note_trip_plan` 写后端（itinerary.py:171-173），本项目把展示和写入分开 |
| `examples/demo_common/host.py` | **不沿用**它的冲突策略：旧 turn 会用新版本号覆盖写入（host.py:209-210）。本项目用条件更新，新请求优先 |
| `merchant_agent` 的 stage/apply | 借鉴「先预览、再由页面确认、最后执行」，用于保存行程和预订 |
| 购物车会话锁 | 只在单进程内有效，不能保护本项目的写入；本项目靠数据库条件更新 |

复制上游代码时保留 Apache-2.0 许可声明，并在 `docs/reuse.md` 记录来源文件和 commit。

## 3. 单轮循环

1. 收到用户消息，按 `client_message_id` 去重；重复消息直接返回原来的 run_id。
2. 加载上下文：当前 TravelRequest、有效 Evidence、近期消息、已加载的 Skill。
3. 调模型。模型可以：追问用户、调用工具，或者提出行程。用户说出新条件时，模型调用 `update_travel_request` 提交修改。
4. 工具调用先过 ToolExecutor 检查，顺序是：参数 schema → 前置条件 → 是否属于当前用户 → 引用的 Evidence 是否有效 → 是否超出预算。
5. 工具执行完，结果写库，和对应的工具调用配对后交回模型。
6. 结束条件满足任一即停：模型给出最终回答且没有待执行工具；达到轮次上限（最后一轮强制不调工具，让模型收尾）；用户取消。结束状态分 `completed` / `partial` / `awaiting_user`。

**并发**：默认逐个执行工具。只有标记为「只读且互不依赖」的工具可以并行。写操作执行时，其他工具等待。

### 3.1 反思循环：生成 → 校验 → 修复

这是本项目最核心的 Agent 机制：

```text
模型提出行程 → validate_itinerary（纯代码）
  ├─ 全部通过 → 进入确认流程
  ├─ 有 conflict（如两个景点间隔不够、闭馆）→ 把具体冲突作为工具结果交回模型 → 模型修正 → 再校验
  └─ 最多修正 N 轮（默认 3）；仍不通过就展示部分结果，并说明冲突在哪
```

为什么修正次数要设上限：模型可能在两个互相冲突的约束之间来回改。到了上限就停下，把冲突交给用户决定。

### 3.2 什么放在哪里

| 内容 | 位置 | 理由 |
| --- | --- | --- |
| 通用规则：事实必须有来源、硬条件优先、未知要说明 | 固定 system prompt | 每轮都要用 |
| 角色设定与语气规则 | 固定 system prompt | 每轮都要用；同一份规格也是语气评测的依据（05 §3.1） |
| 工具的用途、参数、前置条件 | 工具描述和 schema | 模型选工具时看 |
| 低频的复杂步骤：酒店退款比较、局部改程 | Skills：`hotel-comparison`、`itinerary-revision` | 需要时才加载，节省上下文 |
| 身份、来源、预算上限、版本、预订确认 | 代码（执行器和领域层） | 不能靠模型「尽量遵守」 |

`load_skill` 只接受注册过的名称，同一个 Skill 在一段上下文里只加载一次。Skill 只是指令，不授予任何权限。

### 3.3 展示卡片

酒店比较、行程时间轴等卡片由 `present_travel_result` 工具触发：模型只传组件类型和对象 ID，服务端按 ID 填入价格、名称和来源。保留这个工具而不是由代码自动渲染，是为了让模型决定「什么时候给用户看什么」，这和上游的设计一致。代价是多一轮工具调用，这个代价在评测里统计。

## 4. 模型协议

### 4.1 中立消息格式

数据库里存的是**中立格式**的消息，不存某一家供应商的原始格式：

```python
# 本项目内部契约（不是任何 SDK 的原签名）
class Message:
    role: Literal["user", "assistant", "tool"]
    text: str | None
    tool_calls: list[ToolCall]      # 名称、参数、call_id
    tool_results: list[ToolResult]  # call_id、status、内容
    usage: Usage | None
    provider_meta: dict             # 某家专有的字段（如 thinking 块），换模型时可以丢弃

class ModelProvider(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...
    # ModelEvent：text_delta / tool_call_ready / usage / completed / error
```

每个供应商写一对转换函数（中立格式 ↔ 供应商格式）。第一版实现 `AnthropicProvider`（DeepSeek 和 Claude 共用，只是 base_url 和模型名不同）；做模型对比时再加 `OpenAIProvider`。

**为什么这样设计**：如果直接存 DeepSeek 的原始消息，切到 Claude 时旧会话里的专有字段会出错。存中立格式，换模型时只丢 `provider_meta`。这是面试时可以讲的一个取舍。

### 4.2 DeepSeek 兼容接口的已知差异（M0 必须逐项实测）

DeepSeek 提供 Anthropic 兼容接口（`https://api.deepseek.com/anthropic`），但不是全部字段都支持。官方文档列出的差异，以及对本项目的影响：

| 差异 | 影响 | 处理 |
| --- | --- | --- |
| `tool_result.is_error` 被忽略 | 模型分不清「查无结果」和「接口失败」 | 在工具结果正文里放 `status` 字段，不依赖 `is_error` |
| 思考模式下强制指定工具会报 400（Chat Completions 文档写明；Anthropic 兼容接口文档未说明，待实测） | 上游第 0 轮会强制调工具（orchestrator.py:171） | 强制工具的那一轮关闭思考模式，或改为服务端预取 |
| 思考模式 + 工具时，之前的推理内容必须原样回传（Chat Completions 文档写明；Anthropic 兼容接口待实测） | 漏传会报 400 | 推理内容存进 `provider_meta`，续接时带上 |
| `cache_control` 被忽略 | Anthropic 的 prompt 缓存在 DeepSeek 上无效 | 缓存收益只在 Claude 上测；DeepSeek 有自己的自动前缀缓存，看 `prompt_cache_hit_tokens` |
| `disable_parallel_tool_use` 被忽略 | 模型可能一次返回多个工具调用 | 由 ToolExecutor 控制并发，不依赖这个参数 |
| `claude-*` 模型名会被静默映射到 DeepSeek 模型 | 以为在用某个模型，实际不是 | 配置里写明 DeepSeek 模型名，并记录响应中返回的实际模型 |
| `budget_tokens`、`mcp_servers`、`document` 块等不支持 | 不能用这些特性 | 本项目不依赖它们 |

M0 的退出条件：用真实 DeepSeek 跑通一次多轮工具往返，以上每一项都有测试结果记录。

## 5. 上下文与记忆

- **三类数据分开存**：
  - 模型续接用的消息（中立格式，工具调用必须配对完整）；
  - 给用户和 Trace 看的事件（进度、耗时、卡片，不展示模型内部推理）；
  - 领域状态（TravelRequest、行程版本、Evidence）。
- **旅行条件不靠聊天记录**：条件存在 TravelRequest 里，每次修改 `revision` 加 1。压缩上下文时只压缩历史消息，不压缩条件。这样长对话后条件也不会丢。
- **压缩规则**：只在完整轮次之间压缩；先裁剪过长的工具结果，再摘要旧对话；保留当前条件、待办事项、Evidence 引用，以及所有未完成的工具调用配对。
- **长期偏好（B 档）**：比如「不喜欢太早起床」。用户可以查看、修改、删除。当前旅行条件优先于长期偏好。只从用户自己说的话提取偏好，不从工具结果或攻略文本里提取（防止文章里藏的指令写进记忆）。

## 6. 状态与可靠执行

本项目只做 **Agent 特有** 的可靠性。任务队列的多 worker 竞争、压测等放在后端项目里做。

### 6.1 任务断点与恢复

- 第一版用单进程：FastAPI 进程内用 asyncio 后台任务执行 TaskRun。
- 每完成一个工具调用，就在同一个数据库事务里写入：工具结果、模型续接状态、事件、断点。
- 服务重启时，扫描状态为 `running` 的 TaskRun，按情况恢复：
  - 模型响应没有完整保存：丢弃半成品，重新请求模型（多花的 token 照实记账）；
  - 只读工具已完成：Evidence 仍有效就复用，否则重新查询；
  - 写操作已提交：读出保存的结果，不再执行一次；
  - 预订状态不明：不自动重试，走 §6.3 的对账流程。
- SSE 只负责推送，断线不影响任务执行。重连时用 `Last-Event-ID` 补发事件；缺口太大就返回完整快照。**重连绝不重新调用模型或工具。**

> 为什么不做多 worker、租约竞争：这是通用后端问题，后端项目专门处理。ADR 里写明「如果要多 worker，需要加租约和 attempt 号，旧 worker 的写入用条件更新拒绝」。

### 6.2 保存行程：条件更新

用户点确认时，在一个事务里检查：草稿属于当前用户、草稿未过期、`base_version` 等于当前行程版本、`request_revision` 没变。全部满足才保存新版本。

- 检查和写入必须在同一条 SQL 或同一个事务里完成，不能先在 Python 里查、再无条件写。
- 幂等键 = 用户 + 草稿 ID。同一个键重复确认，返回第一次的结果。

### 6.3 模拟预订：状态机 + 幂等 + 对账

```text
quoted ──hold──▶ held ──用户点确认──▶ confirmed ──下单──▶ booked
                  │                       │                │
              过期释放                  失败 ──▶ failed     │
                                          └─超时/无响应─▶ unknown ──对账──▶ booked / failed
```

关键规则：
1. **模型不能直接下单。** `hold_hotel` 是模型可调用的工具；`book` 只能由用户点击页面上的确认按钮触发（`POST /bookings/{id}/confirm`）。模型在对话里说「已确认」不算数。这个设计参考上游的 gates：审批标记只能由页面设置。
2. **幂等**：每次下单请求带一个 `client_ref`（预订 ID 生成，固定不变）。假供应商对同一个 `client_ref` 只创建一个订单。用户重复点击，或服务重启后重发，都不会重复下单。
3. **状态不明时不盲目重试**：下单超时，不知道供应商那边成没成功，就进入 `unknown`，然后用 `client_ref` 查询供应商（对账），根据结果转到 `booked` 或 `failed`。
4. **限流与重试**：供应商返回 429 时按 `Retry-After` 等待；重试次数和总时长都有上限。重试只在一层做（预订服务内部），模型不负责重试。
5. **hold 过期**：hold 有有效期（如 15 分钟），过期自动释放。用户过期后再确认，提示重新报价。

## 7. API

| API | 说明 |
| --- | --- |
| `POST /sessions/{id}/messages` | 发消息；`client_message_id` 去重；返回 `run_id` |
| `GET /runs/{id}` | 读任务状态和当前快照（SSE 断开时用） |
| `GET /runs/{id}/events` | SSE 订阅；支持 `Last-Event-ID` 补发 |
| `POST /runs/{id}/cancel` | 取消；重复取消没有副作用 |
| `GET /plans/{id}` | 读行程及版本，标出需要刷新的报价 |
| `POST /plan-drafts/{id}/confirm` | 确认保存行程（§6.2） |
| `POST /bookings/{id}/confirm` | 用户确认预订（§6.3） |
| `GET /bookings/{id}` | 查预订状态 |
| `GET/PATCH/DELETE /preferences` | 查看、修改、删除长期偏好（B 档） |

所有接口和工具都检查当前用户是否拥有该资源。测试中至少用两个用户验证互相看不到对方数据。

## 8. Trace、预算与失败归因

### 8.1 Trace

用 OpenTelemetry 记录，发送到自托管的 Langfuse 查看：
- 一次 TaskRun 是一个 trace；
- 每次模型调用、工具调用、校验、预订操作各是一个 span；
- span 上记录：模型名（实际返回的）、token 用量、耗时、工具参数摘要、结果状态、TravelRequest 的 revision、关联的 Evidence ID。

不存 API 密钥，不存模型的内部推理原文。

### 8.2 预算

- 每个 TaskRun：模型轮次、工具调用次数、总 token 都有上限。
- 每天：总费用上限，超过就拒绝新任务。
- 超时没有返回 usage 的调用，按估计值记账，不当成零。

> 更复杂的预算预留与结算、准入控制（429/503）放到 C 档，只写 ADR。

### 8.3 失败归因

工具错误码描述「这次调用发生了什么」：`validation`、`blocked`、`unavailable`、`timeout`、`rate_limited`、`provider_error`、`conflict`、`cancelled`。查无结果不是错误，是一个成功返回的空列表。

归因标签描述「任务为什么失败」，用 5 类：
- `request_understanding`：理解错了用户条件；
- `tool_selection_or_args`：选错工具或传错参数；
- `supplier_failure`：供应商出错；
- `stale_evidence`：用了过期的事实；
- `state_commit`：状态写入出错。

归因要有 Trace 证据支持，证据不够就标 `unknown`。注入故障只用来验证归因流程本身能用；简历和面试讲的是真实 dev 用例中出现的失败。

## 9. 编排对照实验

### 9.1 固定流程 vs 模型自主选工具（B 档，必做）

- **A 组**：代码写死流程：抽取条件 → 搜景点 → 查酒店 → 排行程 → 校验。模型只负责每一步内部的生成。
- **B 组**：本项目的主设计，由模型自己决定调用哪些工具、按什么顺序。

同模型、同数据、同用例，比较完成率、工具调用次数、token 和延迟。目的是回答「这个场景到底需不需要 Agent 自主编排，在哪类任务上值得」。

### 9.2 受限规划子 Agent（C 档，只写 ADR）

写清楚：如果加一个只负责排行程的子 Agent，它的输入、只读权限、预算如何从父任务扣除、结果如何由主 Agent 重新校验，以及什么证据出现时才值得加。是否实现，由 9.1 的结果决定。

## 10. 目录（拟建）

```text
apps/web/              演示前端
backend/api/           接口
backend/agent/         循环、prompt、skills、上下文
backend/providers/     中立消息格式与各供应商适配
backend/tools/         工具注册、执行器、schema
backend/domain/        request、evidence、itinerary、booking、validator
backend/mcp/           只读工具的 MCP server
backend/persistence/   迁移、仓储、事务
mock_supplier/         假酒店供应商（可注入故障）
data/                  Wikivoyage / OSM 导入脚本与快照
tests/                 协议、领域、事务、集成
eval/                  用例、评分器、实验配置、报告
docs/                  工程日志、ADR、复用记录
```
