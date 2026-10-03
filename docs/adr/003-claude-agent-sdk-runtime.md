# ADR-003：用 Claude Agent SDK 承担运行时

状态：accepted（2026-10-03，用户明确选择）；**设计已确认，SDK 实现与兼容性未验收**。
取代 ADR-000 中的手写循环 / 通用 ModelProvider 方向；ADR-002 仅保留旧探针的实验边界。
设计正文以 [02 架构](../../plan/实操计划/02-Agent架构与实现设计.md) 为准，任务映射见 [04](../../plan/实操计划/04-开发任务计划.md)。

## 为什么调整

用户希望通过 commerce-agents 理解底层执行机制，项目实现使用 SDK，把开发重点放在旅行业务、工具、校验、状态和评测。无需为了理解循环再维护一份生产循环。

## 决策

- 使用 Python `claude-agent-sdk` 驱动模型/工具往返和会话；现有 `anthropic` 包只是 Messages 客户端，原探针不改写为应用运行时。
- commerce-agents 固定在 `fd4d59224ab96b43c6dc6888207c67b3bd5a24cf`；Messages 版本用于学习，Agent SDK 版本用于接入参考，领域和工具独立编写。未复制上游代码。
- SDK 类型封装在 providers / mcp；domain、services、工具业务实现与 API 不依赖它。应用只定义所需的执行、取消、会话引用与事件边界，不造全厂商消息转换体系。
- 工具由 SDK 进程内 MCP 桥接调用，统一经过 ToolExecutor；内部可提供条件修改、草稿和模拟 hold。对外 MCP 仍只读，确认保存与下单不注册为模型工具。
- 禁用与旅行任务无关的内置工具和隐式配置来源；先验证工具隔离、生命周期、费用和失败路径，再做少量授权 live。
- Claude 为原生线路，DeepSeek 为待验证兼容线路。OpenAI / Gemini 后续单独设计；不在本轮引入网关或第二套 runtime，也不保证更换 key 即可使用。

## 依赖与实施顺序

本 ADR 允许后续 M0.2 引入 `claude-agent-sdk` 及其所需传递依赖；直接使用 MCP API 时声明与 SDK 兼容的 `mcp` 版本，不再预设 2.x。Python 3.12、uv、现有质量检查保留。安装时由 uv 更新锁文件，记录 SDK / 实际 CLI / MCP 版本和 Windows 进程依赖，原文档调整轮未安装；长程实施中可按本 ADR 安装。

M0.2 做 SDK 接入验证 → 自动验证/独立审查 → M0.3 固定适配边界 → 自动验证/独立审查 → M0.4 做旅行 CLI。2026-10-03 用户已取消人工阶段确认，不需合并 main。M0.3 同步 import-linter 禁止其他层直接 import claude_agent_sdk；这是原文档轮的状态；实施后必须补上检查，不声称尚未运行的规则已生效。

## 代价与边界

- SDK 会调用 Claude Code 进程，需要核实运行环境与版本；不是把现有 anthropic import 改名即可。
- SDK session 与业务数据库不共享事务。幂等、版本冲突、确认、预订对账和恢复由我们实现，不能把 SDK 的 resume 或文件回滚当作数据库保证。
- SDK 美元估算不代表 DeepSeek 人民币账单；max_turns 不保证 HTTP 请求次数。SDK 内部辅助调用/重试须纳入调用授权和预算，无法限制时拒绝 live。
- 过去的两请求许可已使用完；后续长程开发获用户整体授权，具体供应商/次数/金额以 docs/execution/travel-agent.md 为准。保留 CNY / USD 独立账本，不借用余额。

## 备选与取舍

手写 Messages 循环便于完全控制请求，但需维护消息配对、流式和恢复等通用代码；LangChain / LangGraph 更适合广泛的模型适配，但用户当前希望沿 commerce-agents 的 SDK 路径实现。此时选择 SDK，接受其运行环境和兼容性边界；兼容失败时记录证据再讨论，不静默更换路线。

## 依据与验收

- [SDK 概览](https://code.claude.com/docs/en/agent-sdk/overview)、[自定义工具](https://code.claude.com/docs/en/agent-sdk/custom-tools)。
- DeepSeek 提供 [Claude Code 接入说明](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/claude_code/)；Anthropic [网关说明](https://code.claude.com/docs/en/llm-gateway) 不保证非 Claude 模型支持；二者不等于本项目端到端已通过。
- 运行实验按 [M0 规格](../tasks/M0.md)；旧证据见 [Messages 探针](../protocol-deepseek.md)，不能替代 SDK 验收。若 SDK 无法在既定权限/费用/Windows 条件下工作，M0.2 保持未通过并记录失败。
