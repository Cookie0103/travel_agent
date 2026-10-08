# M0 文档调整：使用 Claude Agent SDK

当前决定：SDK 承担通用 runtime；通过 commerce-agents 理解机制；旅行业务、工具和评测由我们编写。**这次只改文档，还没有接入 SDK。**

## 阅读顺序
1. [02 架构 §1–4](../../plan/实操计划/02-Agent架构与实现设计.md)：看主调用链和职责。
2. [ADR-003](../adr/003-claude-agent-sdk-runtime.md)：看为什么换、代价和兼容性边界。
3. [M0 规格](../tasks/M0.md)：看下一步的实际产出和验收。
4. [上游阅读线](../guides/reuse.md)：先读 orchestrator/turn 理解机制，再读 SDK 的 make_options/run_turn/build_sdk_tools。

## 主调用链
API/CLI → 旅行上下文 → SDK 适配 → SDK 循环 → 进程内 MCP → 自写 ToolExecutor → 业务服务。
SDK 保存模型会话；数据库保存条件、证据、行程、预订与业务进度；应用事件供 UI/Trace 使用。

## 不变量
- 不重写第二套通用循环；SDK 类型不进入 domain/services。
- 全部旅行工具经过业务校验；模型不能绕过确认保存或直接下单。
- 两币种独立，SDK 轮次和美元估算不能代替请求次数与人民币预算。
- SDK 会话与数据库不是原子保存；稳定业务幂等键保护恢复后的写操作。
以上是新版验收要求，保护测试将在 M0.2/M0.3、M1/M2 分步实现，不能声称已有覆盖。

## 失败处理
DeepSeek 接 SDK 尚未验证；不通过时保留关卡，不静默切换模型或框架。
新实验不能复用已使用的两请求授权，无法限制真实费用/次数时停在离线验证。
SDK 会话不可恢复时核对业务快照，展示已确认状态；具体恢复实验留到 M2.4。

## 取舍
选 SDK，减少运行时维护，把精力放在业务与评测。代价是 CLI 环境、版本和兼容性需要验证。
备选为手写 Messages 循环或 LangGraph；用户此次明确选 SDK，不同时维护其他路线。
OpenAI/Gemini 保留为扩展需求，不把它们写成当前 SDK 原生能力。

## 验证
- dev check：ruff 通过、31 文件 mypy strict 通过、3 条分层契约通过。
- dev test：70 passed、1 deselected in 2.70s；未运行 live。
- 文档检查：33 个任务编号保留；当次扫描 107 个相对链接均存在，换行/代码块/行数限制通过；git diff --check 通过。
- 原始检查输出见 [命令记录](../operations/2026-10-03-agent-sdk-docs.commands.jsonl)；这些检查不证明尚未接入的 SDK 可运行。

## 理解问题
1. Claude Agent SDK 和 anthropic Messages SDK 的职责有什么不同？
2. 用 SDK 后，为什么 ToolExecutor、Evidence 和 validator 仍由我们实现？
3. SDK 已保存会话，为什么还需要业务幂等键和预订对账？
4. 两次 Messages 请求成功，为什么还不能说 SDK + DeepSeek 已跑通？
