# 上游阅读与复用清单

本文件记录阅读与复用依据；下方旧批次说明仅代表当时的事实。未运行或复制上游应用。当前 SDK 验证见 [接入记录](../protocols/protocol-agent-sdk.md)，实施状态见 [执行计划](../archive/execution/travel-agent.md)。

## 项目长期方法约定（2026-10-21）

用户明确要求：Travel Agent 参考以下两篇文章建立；本项目后续新旧对话中的分析、开发、讲解和求职材料都以其方法为起点。本节是该偏好的持久记录，入口为根目录 [AGENTS.md](../../AGENTS.md)。它约束协作者，不是写入旅行应用的记忆库，也不是新的功能计划；业务设计唯一来源仍为 [docs/design](../design/README.md)。

### 参考来源与边界

- [A guide to the anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)：单主 Agent 与 Skills、业务工具、结构化展示、上下文、记忆、代码安全边界与评测。阅读核对日期：2026-10-21。
- [Writing effective tools for agents — with agents](https://www.anthropic.com/research/writing-tools-for-agents)：围绕真实任务设计工具，以原型、运行记录和可核验评测迭代工具契约。阅读核对日期：2026-10-21；[engineering 入口](https://www.anthropic.com/engineering/writing-tools-for-agents)亦可访问同文。
- 采用方法，不复制文章全文、上游应用代码或收益数字。具体 SDK、CLI、模型和 API 能力查锁定版本与当前官方接口；文章不是 DeepSeek 兼容性保证。
- 用户后续明确决定优先；与既定产品目标、SDK 路线或安全不变量冲突时，说明冲突并按现有工作流处理。不得借“按文章做”自动重构、增加功能或放开付费调用。

### 在本项目中如何运用

**架构与上下文。** 优先沿用一个主 Agent 和按需业务 Skill；工具调用已有服务，通用循环复用 Claude Agent SDK。常用规则与低频步骤分开，稳定提示与每轮变化的业务快照分开；减少无用上下文。考虑预取、并行、缓存或更换模型前，先检查当前权限、依赖与实测瓶颈。当前执行器串行不是遗漏，不因文章提倡并行就擅自修改。

**工具契约。** 从真实用户任务选择少量职责清晰的工具，不逐个包装所有接口。名称、参数、前置条件、对象引用和错误后的下一步要明确；schema 与执行检查共用定义。结果只返回下一步需要的事实，支持有界查询与必要的分页、摘要或详情；精简时保留后续操作所需 ID，不能再次截断局部改程需要的项目引用。

**事实、展示与副作用。** 模型提出方案，服务端检查身份、证据、版本和限额；展示按已核验 ID 补齐数据。保存与模拟下单经真实确认入口。外部文字按不可信材料处理。主流程的强制发卡、酒店选择与本地修复是本项目实现，不把它们说成文章原样提供。

**记忆。** 区分模型上下文与数据库事实，核对提取、确认、存储、读取和实际生效。文章中的异步提取方案不等于当前的用户确认式记忆；主流程的长期偏好范围也不等于所有通用入口已强制收紧。隐私、遗忘与来源检查以代码和既定决定为准。

**评测与迭代。** 用真实任务、初始状态和正反例构造可核验终态，允许合理的不同解题路径；只在安全或明确契约需要时限定调用路径。保留故障、状态变化与跨会话场景，读实际对话、工具结果和 trace 定位失败，不能只信 Agent 自述或总分。调整工具描述、schema、返回内容后做相关回归；调优集与留出集分开，不能把当前无留出集的结果讲成泛化能力。

### 回答、开发与审查时的固定检查

1. 先说明用户要完成的任务，再定位实际调用链、状态和代码边界；不先堆框架或术语。
2. 依次区分原文建议、项目已实现行为、运行验证与未证实推断。按问题自然解释，不要求每个短答机械套完整模板。
3. 提建议时先找已有函数、SDK 公共能力和失败证据，再提出最小改动、取舍与验证方法。不为了“更像 Agent”增加工具、子 Agent 或另一套 runtime；这不禁止工作流中已授权的独立代码审查。
4. 工具审查同时检查用途重叠、schema 与实现一致、参数语义、失败反馈、结果长度、必要引用及是否误报已提交写入为失败。
5. 指标说明样本、分母、检查规则、统计单位和版本。任务成功率、稳定通过率、回答相关性、事实准确性与 judge 体验分分别解释；未测量或未校准的项不补造成绩。
6. 耗时说明是模型 HTTP、单轮、首展示还是整个多轮 trial，是否包含评审，以及分位算法和样本数。成本区分保守预算记账与供应商实付；缓存、折扣和计费区间未对账时不推算实际单任务费用。
7. 修复后的部分重跑、拼接、人工改判和已知短板必须披露。文章中的效果、缓存命中率或收入收益不能成为本项目指标；不上传私有正文、密钥或模型内部推理。

### 现有代码与证据入口

| 关注点 | 阅读入口 |
| --- | --- |
| SDK、工具接入与上下文 | [runtime](../../backend/providers/claude_agent/runtime.py)、[桥接](../../backend/mcp/bridge.py)、[业务快照](../../backend/providers/claude_agent/database_tools.py) |
| 工具契约、结果与不可信文字 | [旅行工具](../../backend/tools/travel.py)、[工具契约](../../backend/tools/contracts.py)、[围栏](../../backend/tools/fencing.py) |
| 流程、事实与保存 | [选择卡](../../backend/services/choices.py)、[证据](../../backend/domain/evidence.py)、[校验](../../backend/domain/validator.py)、[修复](../../backend/domain/repair.py)、[行程事务](../../backend/services/plans.py) |
| 确认式记忆 | [记忆服务](../../backend/services/memory.py)、[记忆规则](../../backend/domain/memory.py) |
| v3 评测与结果限定 | [运行器](../../eval/v3_run.py)、[评分](../../eval/v3_score.py)、[judge](../../eval/v3_judge.py)、[结果与拼接](../proposals/eval-redesign/results-2026-10-20.md) |
| 时延统计与预算记账 | [分位统计](../../eval/report.py)、[usage 计价](../../backend/providers/claude_agent/response.py)、[预算账本](../../backend/providers/claude_agent/budget.py) |

本节在仓库中可版本化共享。新会话须先读取；已打开的旧会话如果仍持有旧版指令，需要重新读取 AGENTS.md 和本节，不声称修改文件就能自动刷新所有运行中的上下文。其他电脑或 worktree 需同步包含本节的提交。

## 2026-10-03：SDK 优先、简洁复用

再次阅读用户本地 commerce-agents 的 SDK 路径，并核对 [官方仓库](https://github.com/anthropics/commerce-agents)、[SDK Python 文档](https://code.claude.com/docs/en/agent-sdk/python)、[当前发行版 v0.2.163](https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.163)。项目已锁定这一 SDK 版本；不因此替换已验证的 CLI。

| 已读入口（相对上游根目录） | 采用的做法 | 本项目的边界 |
| --- | --- | --- |
| shopping-agent/runtime-agent-sdk/shopping_agent_sdk/agent.py：make_options / run_turn | 配置集中构造，一次 query 后收集 SDK 结果，入口保持短 | 不复制 Messages API 循环；应用只适配需要的事件 |
| 同目录 shopping_tools.py：tool_contracts / build_shopping_server | 一份工具契约生成注册项与允许列表 | 旅行 schema 和业务执行器只维护一份 |
| commerce-common/commerce_common/agent_sdk.py：build_sdk_tools / collect_turn | 小型桥接复用 SDK tool、MCP server、消息类型 | 不创建另一套 MCP 协议或通用转换框架 |
| commerce-common/commerce_common/execution.py：execute / dispatch | 把业务路由与校验收敛到同一入口 | 旅行业务校验不能靠 SDK 权限提示代替 |

不会照搬的部分：多运行时共存、演示用户身份、全局配置加载、尚未验证的 PostToolBatch hook。上游 Any 较多也不能替代本项目的类型边界。
费用守卫与 Windows 进程清理有已复现的失败依据，作为 SDK 外的必要保护；后续适配复用这套边界，不再复制一份。实际简化结果随代码审查记入 M0 集中记录。

## 固定版本与获取证据

| 上游 | 固定 commit | 本次结果 |
| --- | --- | --- |
| [Commerce Agents](https://github.com/anthropics/commerce-agents/tree/fd4d59224ab96b43c6dc6888207c67b3bd5a24cf) | fd4d59224ab96b43c6dc6888207c67b3bd5a24cf | 获取脚本打印 ready 并核对 HEAD；仅只读参考 |
| DataMind（内部） | d57bb79e3cb16377fa2f6587f110f79ccd5141e1 | 获取脚本打印 ready 并核对 HEAD；本批未读取或复制内部原文 |

获取命令：`uv run python scripts/fetch_upstream.py`，本次退出码 0，完整输出见操作日志。
`vendor/` 被 Git 忽略；Commerce 的 Apache-2.0 声明不等于允许自行复制：本仓库另要求 ADR 授权，本次没有复制行为。

## 官方材料的阅读结论

- 单个主 Agent 在共享会话中调用工具、按需读取 Skills；安全约束应由代码执行层落实。工具模式表达展示卡片，再由服务端校验和补齐。来源：[架构文章](https://claude.com/blog/the-anatomy-of-effective-commerce-agents)。
- 官方提供 retail、travel 等示例，支持 Messages API、Agent SDK、Managed Agents 三种运行方式；M0.1 当时按旧设计参考手写循环；2026-10-03 已转为 SDK 实现，见下方新阅读顺序。来源：[发布文章](https://claude.com/blog/claude-for-commerce-agents)。
- 文章里的质量、收入、速度或缓存数字都不是本项目测量结果，不写进本项目的完成证据。

## 2026-10-03：学习循环，使用 SDK

本轮只读核对用户提供的同级 commerce-agents，HEAD 仍为上述固定 commit；未运行或复制上游。
建议先理解一遍下节 Messages 调用链，再按如下顺序读 SDK 路径：

1. `shopping-agent/runtime-agent-sdk/shopping_agent_sdk/agent.py`：make_options 配置 runtime，run_turn 提交输入、收集结果。
2. `commerce-common/commerce_common/agent_sdk.py`：build_sdk_tools 将工具委托给执行器，collect_turn 收集 SDK 消息；这是应用接入层，不是 SDK 内部循环源码。
3. `shopping-agent/runtime-agent-sdk/shopping_agent_sdk/shopping_tools.py`：工具注册如何连接 core executor。
4. `commerce-common/commerce_common/execution.py`、`shopping-agent/core/shopping_agent/gates.py`：业务入口和代码守门仍然独立于 runtime。
5. 回到本项目 02 §1 / §6：解释旅行条件、Evidence、确认与事务恢复为什么需要自己写。

上游使用的 presentation 停止钩子、Skills 加载权限和 cost_usd 收集不是本项目的既定保证；需按 SDK 锁定版本核实。DeepSeek 不能按上游美元字段直接计费。不复制上游可执行代码或其宽泛 Any 接口。

## 一次 travel 工具往返（M0.1 历史阅读，不是本项目已经运行）

```text
travel/api/main.py：MockTravel + ShoppingAgent + itinerary 展示扩展
  → demo_common/host.py：把本轮会话交给 agent.stream_turn
  → ShoppingAgent.stream_turn：预取、组装上下文、构造模型请求
  → client.messages.stream：得到 assistant 的 tool_use
  → StreamedRound / EagerDispatcher：收集完整参数并调 executor.execute
  → BaseToolExecutor.execute / dispatch：选择 handler 或展示扩展
  → ShoppingToolExecutor._search_products → MockTravel.search_products
  → state.remember_products：把可引用的商品 ID 记入会话状态
  → ToolOutcome → tool_result_block：用同一个 tool_use_id 配对
  → 工具结果追加到 messages → 下一轮模型请求 → 文本或展示结果
  → host：SSE 事件输出；轮次结束后保存会话
```

状态位置：模型消息在 `messages` 列表；已查到的商品在 `ShoppingSessionState`；演示供应商状态在 MockTravel；宿主负责会话保存。
上游循环末轮设置不调用工具；异常或中断时 `close_open_tool_uses` 为未配对调用补结果。已完成写操作优先使用真实结果，避免被描述为需要重试。

## M0.1 当时的阅读与取舍（后续实现以新版 M0 规格为准）

以下路径相对 `vendor/commerce-agents/`；函数名均按本批读到的固定 commit 记录。

| 文件 / 入口 | 本批核实的事实 | 后续本项目如何使用 |
| --- | --- | --- |
| examples/travel/api/main.py | 构造 MockTravel 与 ShoppingAgent，注册 itinerary 扩展 | 参考入口组合方式，不使用上游运行时 |
| shopping-agent/runtime-messages-api/shopping_agent_runtime/orchestrator.py / stream_turn | 有界循环、末轮 tool_choice none、配对结果回填 | 旧计划曾拟自行实现；现用于学习，实际 M0.4 调 SDK |
| commerce-common/turn.py / EagerDispatcher.collect | 收集工具结果，支持流中启动的调用 | 第一版按本项目设计默认串行，不能直接照搬并发 |
| commerce-common/turn.py / close_open_tool_uses | 中断后补齐结果并保留已完成操作结论 | 后续消息配对测试的参考思路 |
| commerce-common/execution.py / execute、dispatch | 统一路由、参数失败与后端失败区分 | 自行实现 ToolExecutor 与既定错误码 |
| shopping-agent/core/shopping_agent/executor.py / _search_products | 搜索后把结果写进本会话 seen 状态 | 本项目用 Evidence 与引用检查代替隐含信任 |
| examples/travel/api/itinerary.py / _enrich | 用已见 ID 补卡片，忽略未知 ID；还会调用 note_trip_plan 写后端 | 不沿用展示时写业务状态的做法；保存由独立确认入口负责 |
| examples/demo_common/host.py / write_back | 会话冲突后读取新版本再保存旧 turn | 不沿用；本项目要求条件更新，不能覆盖较新请求 |
| commerce-common/testing.py / FakeClient | 脚本化响应、记录调用；响应耗尽即失败 | 参考离线脚本化测试策略；SDK 路线用 FakeRuntime，不复制 |

## M3.3 SDK公共能力核查

2026-10-03：[官方MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)与安装2.3一致；使用Server的on_list_tools/on_call_tool及StreamableHTTPSessionManager，不使用已变更的旧v1装饰器。schema复用本项目定义，协议交SDK；Client和streamable_http_client用于实际HTTP回归。来源阅读用于选接口，不复制上游应用代码。

## M3.1 上下文能力核查

2026-10-03：锁定SDK公开SystemMessage支持compact_boundary；当前Python接口没有compact()，不套用新版CLI独有PostCompact能力。[官方环境变量](https://code.claude.com/docs/en/settings#environment-variables)中的CLAUDE_AUTOCOMPACT_PCT_OVERRIDE只用于本地机制测试。实际CLI完成自动压缩并续接规划，应用仅观察事件、读取PG快照，不实现摘要器或改写消息。真实模型摘要效果另验。

2026-10-09 P05追加核验（历史记录不改写）：实际SDK0.2.163/CLI2.1.294的reactive压缩保护当前用户工具组；仅人工抬高当前组usage会遇固定前缀优化、无可总结助手。测试通过SDK公共query/receive_response生成两轮已完成助手历史，随后原生产worker/Runtime执行单业务prompt；相同20%/100k窗口、人工8k/11k/22k输入，full实际boundary、关闭模式零boundary。精确版本pair追加，不支持未知pair，若意外压缩仍中止；不添加摘要器、改写transcript或count_tokens端点。实际PG18项通过含压缩后当前快照/配对/SDK续接，以及工具后summary503无checkpoint。数据为合成机制验证，不代表真实模型摘要质量；原七基线失败与完整回归结果见[本批P05](../plans/2026-10-08-product-v2.md)。

## M0.1 当时边界（历史）

- 没有调用 DeepSeek、Claude 或其他 LLM API；没有做协议实测。
- 没有执行上游测试，因此不能声称上游运行通过。
- M0.1 的工具往返是源码分析；本项目 CLI、Provider 与业务工具尚未实现。
- DataMind 的业务材料与 21 条用例留到 M0.6 按既定规则处理；本批没有从内部仓库发布文件或内容。
