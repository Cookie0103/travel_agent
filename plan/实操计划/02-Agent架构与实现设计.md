# 02 Agent 架构与实现设计

本文定义执行契约；领域字段见 [03](03-数据工具与外部API.md)，测试判定见 [05](05-评测与验收.md)，上游依据见 [06](06-来源与待验证事项.md)。

## 1. 沿用哪些设计，改造哪些代码

一个主 Agent 持有对话，配合 Skills、执行器、业务后端和展示工具；不按内容/酒店/路线分发多个 Agent。M3 的受限规划契约见第 9 节。

| 上游落点 | 本项目处理 |
| --- | --- |
| `commerce_common/skills.py`、prompt 分层 | 优先复用小模块；业务 skill 自写，使用固定名称索引 |
| `execution.py`、`presentation.py`、事件契约 | 参考执行框架，适配旅行结果及错误；保留对应不变量测试 |
| Shopping Messages `orchestrator.py` | 阅读并保留有界工具循环思路；替换购物预取、prompt、注册、grounding、结束条件与宿主状态 |
| `StorefrontBackend` / Product / cart | 建立独立 TravelServices 与领域对象，文章不伪装成带价格的商品 |
| travel 的 `itinerary.py` | 学习 ID 补全和组件扩展；重新实现无副作用的旅行展示 |
| `MemoryStore` / `DelegateExtension` | 契约参考；持久化、模型配置和旅行权限由本项目落实 |
| 示例 host/session | 不继承其“版本冲突后旧任务强行写回”策略；采用下面的事务协议 |
| Merchant stage/apply | 借鉴预览与宿主确认模式；第一版只用于保存行程变更 |

M0 复用清单记录 commit、原文件/符号、保留/替换行为、测试与许可；复制代码保留原许可通知。

上游购物车会话锁不保护旅行工具或跨 worker 写入；本项目调度和提交遵循第 3、6 节。

## 2. 分层与主调用链

```text
Next.js → FastAPI → TaskHost / PostgreSQL
                         ↓ worker
                    TravelAgent
                  ↙             ↘
       ModelProvider          ToolExecutor
         DeepSeek          → TravelServices → Adapters
                                  ↓
                        Evidence / Validator / Plans
                                  ↓
                      已提交事件 → SSE → 白名单组件
```

API 管身份和收发，TaskHost 管生命周期，模型选择行动，Executor 校验调用，领域服务保证业务不变量。

researching/drafting/validating 是进度，不强制依次执行；工具前置条件见 03。

## 3. 单轮循环与 Skills

1. 接收用户消息，绑定 principal、session、turn_seq，创建 TaskRun；重复消息 ID 返回原 run。
2. 加载结构化旅行条件、有效证据、必要近期消息、已加载 skill 和运行预算。
3. 主模型可澄清、调用工具或提出方案；明确的新条件通过 `update_travel_request` 提交 patch。
4. 执行器检查 schema → 前置条件 → ownership → evidence → 当前执行资格 → 预算。
5. 完整工具参数通过校验后执行；结果持久化、登记证据、配对回传模型。
6. 展示与保存草稿经过校验；失败反馈具体冲突，允许有限次修正。
7. 无待处理工具且结果完成，或达到执行上限时结束；区分 completed/partial/awaiting_user，建议按钮不作为完成标志。

默认串行；只有注册为独立读取、使用同一已提交 request snapshot 的调用可有界并发。写操作形成屏障，依赖新条件的读取等待提交。

| 内容 | 放置位置 |
| --- | --- |
| 常用规则、事实引用、未知处理、硬条件优先 | 固定 system prompt |
| 工具输入、返回语义和前置条件 | 工具描述与 schema |
| 低频酒店退款比较、复杂局部改程步骤 | `hotel-comparison`、`itinerary-revision` Skills |
| 身份、来源、费用上限、版本与写入条件 | 执行器和领域代码 |

`load_skill` 只接受可信注册名；同一 skill 每个上下文段加载一次，记录版本和指纹。Skill 不创建 Agent 或授予权限。

工具列表按部署能力和角色固定排序；缺参数返回 missing_fields，永久不可用能力从配置关闭。静态前缀与动态状态分离，缓存收益实测。

## 4. 模型协议与上下文

M0 先测 DeepSeek Anthropic 兼容接口，不满足时再测 Chat Completions；最终只维护一种接口。主循环、摘要、记忆与委派共用 ProviderConfig，并冻结思考模式与强制工具行为。

```python
# 拟建内部契约，不是供应商 SDK 原签名
class ModelProvider(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...

# ModelRequest: messages_wire, tool_specs, config, limits
# ModelEvent: text_delta / tool_call_ready / usage / response_completed / error
# response_completed 含完整 assistant_message_wire、stop_reason 和 provider 元数据
```

必须分开保存：
- **模型续接消息**：工具 ID、结果、供应商要求的 thinking/continuation 字段，schema 版本齐全。
- **UI/Trace 事件**：进度、参数摘要、耗时、用量、错误和最终卡片；不向用户输出内部推理内容。
- **领域状态**：TravelRequest、计划版本与证据，不依赖自由文本摘要恢复。

未完成 JSON 或截断轮次不能派发写操作；下一次模型请求前，工具调用必须配对结果。完整消息包含供应商续接字段，不能只由 text/tool 事件重建；协议测试覆盖见 05 的 R01–R02、R12–R13。

压缩只在完整轮次边界进行：先裁剪大工具结果，再摘要旧对话；保留当前请求、待办、必要近期消息、skill 版本、证据引用及合法调用配对。重建上下文段须使用已验证的供应商消息形式。

当前旅行条件优先于长期偏好。长期记忆在 M3 加入：用户可查看/修改/删除；提取写入在同一数据库事务中比较记忆 generation，避免清空后旧任务回写。不将工具文本提取成用户偏好。

## 5. 运行状态与 API

下表只定义运行对象；TravelRequest、计划和证据字段统一见 03。

| 对象 | 关键字段与职责 |
| --- | --- |
| Conversation | owner、turn_seq、current_run_id、messages；控制哪次回复当前可见 |
| TaskRun | run_id、input_revision、attempt、status、lease_until、budget、checkpoint、last_event_seq、queue_expires_at、deadline_at、next_attempt_at |
| TaskStep | run_id、逻辑 step_id、attempt、工具参数摘要/指纹、状态、结果引用 |

TaskRun 生命周期：queued → running → completed/partial/awaiting_user/awaiting_approval/failed/cancelled/expired。等待用户的 run 不占 worker；用户下一次输入产生新 run，并关联旧任务。进程故障的 running run 可在租约过期后重新领取，attempt 递增。

每条新消息递增 turn_seq，替换当前生成任务；纯解释提问不递增 TravelRequest.revision，也不自动让报价失效。条件 patch 提交时原子更新 request 与当前 run 的 input_revision；同一批旧 snapshot 读取结果不能沿用。

| 拟建 API | 语义 |
| --- | --- |
| POST /sessions/{id}/messages | client_message_id 去重；返回 run_id；身份由服务端认证绑定 |
| GET /runs/{id} | 读取自己的任务状态与已提交快照，供 SSE 回退恢复 |
| GET /runs/{id}/events | SSE 订阅；Last-Event-ID 重放已提交事件 |
| POST /runs/{id}/cancel | 标记取消，撤销提交资格；重复取消幂等 |
| GET /plans/{id} | 读取自己的计划版本与待刷新提示 |
| POST /plan-drafts/{id}/confirm | 绑定 draft/base_version/revision，检查后事务保存 |
| GET/PATCH/DELETE /preferences | M3 的个人记忆查看、修改与删除；写入比较 generation |

接口/工具均校验服务端身份与 owner；两个测试用户必须隔离。

## 6. 事务、幂等与任务恢复

先用 PostgreSQL + 一个 worker：SQL 条件领取 queued/租约过期任务，递增 attempt 并续租；隔离重启前的迟到调用。固定执行槽位测并发请求与排队，多 worker 单独对比。

一次结果提交必须同时匹配：当前 run、attempt、未取消状态、有效租约、预期 request revision；修改计划还必须匹配 base_version。按固定锁顺序在短事务中检查并更新，不能先在 Python 检查、再无条件写 DB。

| 操作 | 同一事务中完成 |
| --- | --- |
| 接收消息 | 幂等消息记录、turn_seq、current_run、旧 run 取消及 queued 事件 |
| 更新旅行条件 | RequestPatch、revision、当前 run 绑定、需失效的证据标记 |
| 提交工具结果 | 当前执行资格检查、step 结果、允许保存的证据、模型续接状态、事件与 checkpoint |
| 用户确认计划 | owner/版本/过期校验、计划新版本、草稿状态、幂等结果与事件 |

业务事件写入 events 表后才发布。事件表兼作重放来源，暂不引入额外消息队列。数据库事务不跨越模型或外部 API 调用。

确认是独立宿主事务，检查身份、草稿状态/有效期、base_version 与 request_revision，不依赖已结束的 worker 租约。幂等键绑定 principal + draft_id + 操作：同键同指纹返回原版本，不同指纹返回 conflict。任务恢复不代替用户确认。

恢复按故障位置处理：
- 模型响应尚未完整保存：丢弃半成品，可重新请求，记录重复用量；不要求模型输出逐字一致。
- 读取已完成：证据仍有效则复用，否则刷新；在租约/attempt 变更后重新绑定。
- 本地写入已提交、进程随后退出：读取事务内保存的幂等结果，不再次写入。
- 数据库没有提交：从最后完整 checkpoint 重试允许重试的步骤。
- 外部副作用状态不明：不自动重试；第一版没有外部预订写入。

SSE 连接不驱动任务生命周期。持久化业务事件和最终文本；细粒度临时文本可不持久化，重连用完整快照替换临时内容。序号缺口或超出保留窗口返回 snapshot_required，前端读取快照后续订阅。重连绝不重新发起工具调用。

## 7. 预算、Trace 与失败归因

执行前预留调用预算，主模型、摘要、记忆提取、子任务和重试共享同一任务账本。预留与结算原子处理；超时无 usage 的调用记未知/估计消耗，不立即释放成可再次花费的额度。限制模型轮次、工具次数、并发、输出和总期限；重试只有一个责任层。

Trace 支持从失败现象找到首个偏离点，关联证据、修复与回归。

| 记录 | 最小内容 |
| --- | --- |
| 关联与配置 | trace/span/parent_span、session/turn/run/attempt、request revision、case_id、模型/prompt/skill/schema/数据版本 |
| 输入与选择 | 条件 patch 前后值及用户轮次、模型可见上下文的受控引用/指纹、工具名称/参数摘要、Skills 和压缩变更 |
| 工具与证据 | tool_call/step ID、供应商请求 ID、每次重试/错误码、evidence ID/有效期/条件指纹、校验报告 |
| 提交与产物 | 预期/实际版本、资格检查结果、draft/plan ID、状态 diff、确认或取消事件、最终结果引用 |
| 时序与费用 | 接收/准入/领取/首进度/首有效结果/结束时间，预算预留和结算、usage、费用及未知项 |

业务状态、关键事件和提交审计同事务；失败后另记拒绝诊断。模型/工具 span 可异步写，标明丢失/采样；评测保留完整允许记录。哈希仅校验一致性，复现还需受控快照或 fixture。

模型协议原文、脱敏调试记录与用户进度分开；不展示内部推理，不存密钥或禁止留存的内容，无法重建时注明缺口。

归因记录 `primary_cause + contributing_causes + evidence_refs + confidence/status`。最小分类：`request_understanding`、`tool_selection_or_args`、`supplier_failure`、`stale_evidence`、`state_commit`；另有 `context_loss`、`planner_constraint`、`runtime_or_capacity` 和 `unknown`。分类是证据支持的诊断，不能仅凭最后一个异常由模型猜测。

已恢复的 429、被拒绝的旧 attempt 不直接算最终失败根因；结合前后状态区分故障与保护生效。归因用例和评分见 05 第 6 节。

工具错误仍统一为 validation、blocked、unavailable、timeout、rate_limited、provider_error、conflict、cancelled。错误码描述执行结果，归因标签描述任务为什么失败，两者不混用；零结果是成功读取的空集合。

## 8. 有界执行与过载处理

配置 worker/执行槽位、全局/每用户队列上限、供应商并发/速率、等待上限、任务绝对期限和日预算；初期使用 PostgreSQL 队列。

1. **准入**：先识别重复 message ID，返回原任务；新消息在短事务中预留队列容量。容量不够时不创建任务、不取消用户原任务；多 API 实例不能靠进程内计数控制全局容量。
2. **拒绝**：用户请求限额返回 429，服务队列容量不足返回 503，均给 Retry-After。接收成功返回 run_id 与 queued；即时 ACK 不当作首个有效反馈。
3. **等待**：排队不占模型并发额度；超过等待上限变为 expired，用户取消后不再领取。过期/取消与领取竞争使用同一条件更新，并释放容量。
4. **供应商限流**：尊重 Retry-After，退避加抖动；受次数、总期限和预算限制。长等待在事务中保存 checkpoint/next_attempt_at 并从 running 回到 queued、释放租约和执行槽位；再次领取递增 attempt。逻辑 step_id、累计重试次数和预算账本保持不变，不能创建无限新任务或重置额度。
5. **降级**：不可用的信息标缺失，允许返回部分成果；过期报价不当新事实。终止后释放槽位及未使用预留；未知 usage 仍保守记账。迟到调用检查资格，崩溃后对账预算与容量。

SSE 重连不重复排队；流量恢复后队列应排空并继续服务。负载与指标见 05 第 7 节。

## 9. 受限规划子 Agent 实验

M3 必做实验，默认 `planner_delegate_enabled=false`；子 Agent 只提出行程候选，主 Agent 负责对话、条件和展示。开启条件见 05 第 5 节。

| 项目 | 契约 |
| --- | --- |
| 输入 | 任务 ID、冻结的 request revision、当前 plan/base_version、候选及有效 evidence refs、硬/软条件、锁定项、剩余预算/期限 |
| 允许能力 | `estimate_routes`、`validate_itinerary` 的只读受限入口；只操作传入候选与快照，不再查另一批更丰富资料 |
| 输出 | 结构化 proposal/PlanPatch、证据引用、assumptions、未解决冲突；所有输出均视为待校验建议 |
| 禁止能力 | 改条件、写计划/偏好、创建正式草稿、展示给用户、获取主对话之外的数据、嵌套委派 |
| 控制 | 最多一个子任务、深度 1；ProviderConfig 与主循环一致；总账本预留子预算及主 Agent 收尾额度，重试不能绕过限制 |
| 接受结果 | 主端重新查 revision/attempt/期限、schema、候选引用及约束，再进入原有草稿确认链；子结果不能自证正确 |
| 超时与恢复 | 父任务取消或失效则取消子任务，拒绝晚到结果；完成结果可从 checkpoint 复用。中断重算仍计预算；主端只在预算/期限内回退，否则保留部分成果 |

采用直接 Python 调用，通过父 span 关联模型、工具和预算；不新建可写用户会话，不提供数据库写权限或通用 executor，只注入只读白名单。对照方法见 05。

## 10. 独立扩展与拟建目录

可选 MCP 仍经过同一执行器；运营 Agent 属于独立业务入口。扩展条件统一见 04。

```text
apps/web/                 页面、SSE、组件
backend/api/              认证、消息、确认、查询
backend/agent/            loop、prompt、skills、context
backend/providers/        选定的 DeepSeek 协议
backend/tools/            registry、executor、schema
backend/domain/           request、offer、evidence、plan
backend/services/         task_host、validator、memory
backend/adapters/         fixtures、已连接的数据服务
backend/persistence/      migrations、repositories、transactions
tests/                    协议、领域、事务、交互
eval/                     快照任务、graders、实验配置
docs/                     工程日志、重要 ADR、复用清单
```
