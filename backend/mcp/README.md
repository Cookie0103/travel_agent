# 旅行工具的 SDK 桥接与对外服务

职责：M0.3/0.4 用进程内 MCP 将自写工具接到 Claude Agent SDK。
M3.3 再提供独立的对外只读 MCP 服务，两者共享业务 handlers。
入口：尚未实现，当前为目录占位。
关键流程：SDK 工具参数 → ToolExecutor → services/domain → 结构化结果。
不变量：内部条件修改/草稿/hold 也必须过业务校验；确认保存和下单不暴露给模型。
对外 MCP 只读；不预设 2.x，按 SDK 依赖组合锁定版本。
