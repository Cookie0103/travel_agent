# 02 Agent 架构与实现设计

本文说明 Agent 怎么运行：一次请求经过哪些模块，状态存在哪里，出错时怎么办。
领域字段见 [03](03-data-tools.md)，测试标准见 [05](05-validation.md)，上游依据见 [06](06-sources.md)。

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

2026-10-03 用户确认：**Claude Agent SDK 负责通用运行时，旅行业务和工具由本项目实现；commerce-agents 用来理解机制和参考接入。** 决策记录见 [ADR-003](../adr/003-claude-agent-sdk-runtime.md)。本页为目标架构，实际实施状态见[执行计划](../execution/travel-agent.md)。

```text
用户发消息 → FastAPI：身份检查、消息去重、创建 TaskRun
  → agent：读取当前 TravelRequest / Evidence，组装旅行上下文
  → providers：Claude Agent SDK 适配边界 → SDK 驱动模型与工具循环
      → mcp：进程内旅行工具桥接
      → ToolExecutor：参数、权限、证据、版本、次数检查
      → services / domain：查询、校验、草稿与模拟 hold
      → persistence / adapters：记录业务结果、事件；返回工具结果给 SDK
  → SDK 事件经适配 → 应用事件 → SSE / CLI 展示
用户点「确认保存 / 预订」→ 独立 API → 业务事务，不让模型直接提交
```

SDK 管消息往返、工具结果回填和会话上下文；应用管业务状态、预算、权限、校验和用户确认。SDK 类型不进入 domain、services 或 API 公共接口。

## 2. 从 Commerce Agents 学什么、实现什么

| 上游 | 本项目怎么处理 |
| --- | --- |
| `shopping_agent_runtime/orchestrator.py`、`commerce_common/turn.py` | 阅读 Messages API 版本，理解循环、流式工具参数、调用 ID 配对、停止和中断；不再重写同一套运行时 |
| `shopping-agent/runtime-agent-sdk/shopping_agent_sdk/agent.py` | 参考 `make_options → run_turn`：配置 SDK、接入工具、收集本轮结果 |
| `commerce_common/agent_sdk.py` | 参考进程内 MCP 工具桥接和结果收集；钩子、成本字段与 Skills 加载按锁定版本验证，不照搬 |
| `commerce_common/execution.py`、`presentation.py`、`shopping_agent/gates.py` | 独立实现旅行 ToolExecutor、Evidence 引用检查与按 ID 补卡片；这些检查不交给 prompt |
| `examples/travel/api/itinerary.py` | 学习卡片补全；本项目将展示和写入分开，展示不自动保存 |
| `examples/demo_common/host.py` | 不采用旧 turn 用新版本覆盖写入的策略；本项目用条件更新 |
| merchant 的 stage/apply | 借鉴预览后由页面确认的业务边界；预订幂等由数据库和供应商共同保证 |

上游是应用参考实现，不等于 Claude Code 二进制内部源码。能解释公开的循环机制与 SDK 行为，不宣称读懂了未公开实现。仅参考，不复制上游代码；复制须另有 ADR 许可。

## 3. 一次执行与停止

1. 按 `client_message_id` 去重，加载服务端身份、当前旅行条件、有效证据和最近的业务摘要。
2. 建立或恢复当前用户的 SDK 会话，固定计费来源与模型；每个业务会话同一时刻仅一个执行者。
3. SDK 驱动模型选择已注册工具；全部工具经本项目 ToolExecutor，不能直达数据库或供应商。
4. ToolExecutor 顺序检查 schema、前置条件、所属用户、Evidence / revision、工具次数与业务预算。错误以结构化结果返回。
5. 业务结果与应用事件落库，工具桥接把结果交回 SDK。SDK 会话记录与数据库事务分开管理（§6.1）。
6. 根据 SDK 结束信号及业务状态映射为 `completed / partial / awaiting_user / cancelled / failed`。超时、轮次上限或取消时保留已有结果，停止继续调用；不额外花一次模型请求“收尾”，不伪造成功。

**有界执行**：配置 SDK 的轮次上限、应用超时和工具调用上限；SDK 轮次不等于 HTTP 请求数，隐藏重试和压缩请求也必须受费用控制（§8.2）。

**并发**：ToolExecutor 默认串行；只有明确只读、无依赖的工具才可有界并行。写操作排他执行，读取检查 request_revision；不靠 SDK 并发提示保证业务顺序。

**工具权限**：首版禁用内置文件、Shell、网络搜索和子 Agent 工具，显式注册旅行工具；`allowed_tools` 只是自动批准列表，不是完整隔离。结合 `tools`、拒绝规则和受控配置目录验证最终工具集。SDK 配置不得继承开发者机器上的 MCP、插件或账号凭据。工具列表限制之外，业务校验始终在 ToolExecutor 中执行。依据见 [官方权限说明](https://code.claude.com/docs/en/agent-sdk/permissions)。

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

## 4. SDK 接入与模型边界

### 4.1 SDK 适配，而非另造模型协议

- 采用 Python `claude-agent-sdk`；`anthropic` 是直接调用 Messages API 的客户端，两者不是同一个库。旧 probe 继续作为独立历史实验。
- `backend/providers/` 管 SDK 配置、生命周期、取消、resume 和事件转换；`backend/agent/` 管旅行上下文与执行策略。M0.3 定义最小应用事件契约，首版不建设跨厂商原始消息转换平台。
- `backend/mcp/` 用 SDK 的进程内工具机制接入本项目 handlers，工具 schema 与业务检查仍属于 `backend/tools/`。SDK 使用的本地 MCP 桥接不要求 DeepSeek 支持 Messages API 的服务端 `mcp_servers` 字段。
- 前端只收到应用事件和经核验的业务结果，不依赖 SDK 消息类。会话引用绑定 user_id、业务 session_id、SDK session_id、runtime / CLI 版本、计费来源和模型。

官方依据：[SDK 概览](https://code.claude.com/docs/en/agent-sdk/overview)、[自定义工具](https://code.claude.com/docs/en/agent-sdk/custom-tools)。

### 4.2 DeepSeek 兼容性关卡（M0.2）

DeepSeek 官方提供 [Claude Code 接入配置](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/claude_code/)；Anthropic 则说明不支持通过网关将 Claude Code 路由至非 Claude 模型（[官方说明](https://code.claude.com/docs/en/llm-gateway)）。本项目选择将 DeepSeek 作为**待验证的兼容线路**，不把它写成 Anthropic 官方保证。

现有 [协议探针](../protocols/protocol-deepseek.md) 只完成了两次 Messages 请求。SDK 还多了 CLI 进程、环境配置、工具注册、停止和会话行为，必须单独验收：

| 项目 | 验收证据 |
| --- | --- |
| Windows 启动与版本 | Python SDK、实际使用的 Claude Code CLI、MCP 依赖版本固定；离线检查进程启动与错误退出 |
| 线路和模型 | 子进程只拿本次所需凭据；明确 DeepSeek 模型名，核实实际返回模型；禁用未验证的 fallback 与辅助调用 |
| 最小工具往返 | SDK 调用本地合成工具 → 工具结果回填 → 正常结束；流式文本与工具事件可辨认 |
| 失败与中断 | 非法参数、失败结果正文 status、取消、限次均有离线故障测试；SDK 续接实测按授权与费用单独安排 |
| 成本与次数 | 先证明请求计数和预算约束覆盖 SDK 实际请求，再允许 live；不能用 max_turns 当请求上限 |

不再为与当前业务无关的每个协议字段追加付费实验；强制 tool_choice、原始 thinking 块和缓存字段的旧探针结论保留，但不自写这部分 SDK 内部逻辑。未测的行为明确标注，不能算通过。

### 4.3 模型范围

当前目标是 Claude 原生线路与 DeepSeek 兼容线路；二者分别验证。OpenAI / Gemini 保留为后续扩展需求，Claude Agent SDK 不视为通用多模型适配层，不能承诺只换 key 即可接入。要增加其他 runtime 或网关时单独 ADR，不在本次引入。

同一 SDK 会话固定模型与来源；切换模型新建会话，重新注入服务端旅行条件及有效证据，不跨供应商重放原始推理或未完成工具调用。DeepSeek 验证失败时记录限制，不静默改回手写循环、LangGraph 或收费 Claude 线路。

## 5. 上下文与记忆

- **三类状态分开**：SDK 会话记录用于模型续接；应用事件用于 UI / Trace；PostgreSQL 领域状态是 TravelRequest、Evidence、行程和预订的事实来源。
- **旅行条件不靠 SDK 记忆**：每次开始/恢复从服务端重新读取 revision 和有效 Evidence。模型提交条件修改仍走 `update_travel_request`，不能因会话文本较新就覆盖数据库。
- **澄清进度不靠助手全文**：同一快照读取有限待办、原任务用户文本与当前追问；缺项从当前条件派生。房型枚举输入投影到原条件，SDK 原生 Stop 仅一次纠正可执行而未完成的任务，费用/工具边界不变；契约见 [ADR-014](../adr/014-session-history.md)、[ADR-015](../adr/015-lodging-budget-and-condition-source.md)。
- **压缩由 SDK 处理**：应用控制注入内容与工具结果长度；M3.1 验证压缩后硬条件、证据引用与工具结果仍正确，不手工重写 SDK transcript / thinking 块。
- **Skills**：首版保留注册制 `load_skill` 旅行工具，从受控资源读取；不自动加载用户主目录、仓库开发规则或上游 Skills。若改为 SDK 原生 Skill，需单独验证所需权限与配置，不同时维护两套加载器。
- **长期偏好（B 档）**：仅从用户表达提取，用户可查看、修改、删除；当前旅行条件优先。不能从攻略或工具结果提取偏好。
- SDK 会话文件视为可能含完整上下文的私有运行数据：隔离用户、限制访问、排除 Git，不作为公共日志或评测报告上传。

## 6. 状态与可靠执行

本项目只做 **Agent 特有** 的可靠性。任务队列的多 worker 竞争、压测等放在后端项目里做。

### 6.1 业务断点与 SDK 会话恢复

- 第一版仍是单进程 asyncio 后台执行；SDK 子进程生命周期由适配层管理。
- PostgreSQL 事务保存工具业务结果、幂等记录、应用事件和 TaskRun 业务进度。SDK session_id 只作关联引用；SDK transcript 与数据库**不是同一个原子事务**。
- 进程退出后先核对业务状态，再决定恢复 SDK 会话或以业务快照新建会话。支持哪些中断位置由 M2.4 故障实验确认；“会话可 resume”不等于业务恰好执行一次。
- 只读结果仍有效时可复用；过期则重新查询。写操作按稳定的业务幂等键返回已提交结果，不能只依赖 SDK tool_use_id 去重，恢复后模型可能生成新 ID。
- 预订状态 unknown 必须先按 client_ref 对账；SDK 不决定能否重复下单。半条流或会话损坏不能被当作完整结果；无法安全恢复则标 partial / awaiting_user 并展示已核验状态。
- 恢复可能产生新的模型请求，仍检查授权、次数和费用。业务写入已提交而 SDK 尚未记到结果，以及相反顺序，均需覆盖崩溃测试。
- SDK 会话存储需持久化；仅保存 session_id 不足以跨进程恢复。M2.4 验证存储丢失、隔离和版本兼容，M4.1 配置持久卷。文件回滚能力不等于数据库回滚。
- SSE 重连只读已保存的应用事件/快照，绝不重跑模型或工具。

依据：[SDK 会话](https://code.claude.com/docs/en/agent-sdk/sessions)。多 worker、租约和竞争仍属 C 档。

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
| `GET /sessions` | 当前用户旅行摘要，有界分页；新增规划契约见 [ADR-014](../adr/014-session-history.md)，实施与验收见批次 T1.1 |
| `GET /sessions/{id}/runs` | 当前旅行轮次历史，只读恢复不重跑模型；分页/归属见 ADR-014 |
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
- SDK 执行、工具调用、校验和预订操作各有 span；模型子调用仅在 SDK 提供可核验信息时单独记录，否则明确观测缺口，不伪造逐请求 Trace；
- span 上记录：模型名（实际返回的）、token 用量、耗时、工具参数摘要、结果状态、TravelRequest 的 revision、关联的 Evidence ID。

公共日志和 Trace 不存 API 密钥、完整 prompt 或模型内部推理原文；SDK 私有会话存储按 §5 单独管理。

### 8.2 预算

- DeepSeek 使用 `DAILY_BUDGET_CNY`；Anthropic 使用 `DAILY_BUDGET_USD`，后续 OpenAI 若接入共用美元线路。独立记账，不自动换汇或借用余额。
- 缺失、空白、非法、0 或不足均拒绝相应真实调用。预算不是调用授权；此前两请求授权已使用；新 SDK 实验使用执行计划中记录的本轮整体授权，不逐次询问。
- SDK `max_budget_usd` 是自身美元估算上限，不是 DeepSeek 人民币额度，也不是每日账本；返回的美元估计不能直接当作 DeepSeek 账单。
- M0.2 先离线核实内部重试、压缩和其他辅助模型请求的边界，设置输入/输出限制、工具次数、轮次与总时限。若无法保证用户的请求上限和保守费用上界，live 入口拒绝运行并记录待解决项，不能只在任务结束后看 usage。
- DeepSeek 按明确模型及有效人民币价表记账；未知 usage 的失败请求保守计费，不当作免费。已验证的限次与预算状态跨重启保留。

依据：[SDK 成本说明](https://code.claude.com/docs/en/agent-sdk/cost-tracking)。C 档仍只讨论多 worker 预算预留/结算，不影响首版必须有的费用保护。

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
backend/agent/         旅行上下文、prompt、skills、执行策略（不重写 SDK 循环）
backend/providers/     Claude Agent SDK 适配、配置、会话、事件转换；旧 probe 隔离
backend/tools/         工具注册、执行器、schema
backend/domain/        request、evidence、itinerary、booking、validator
backend/mcp/           SDK 进程内工具桥接；M3.3 对外只读 MCP server
backend/persistence/   迁移、仓储、事务
mock_supplier/         假酒店供应商（可注入故障）
data/                  Wikivoyage / OSM 导入脚本与快照
tests/                 协议、领域、事务、集成
eval/                  用例、评分器、实验配置、报告
docs/                  工程日志、ADR、复用记录
```
