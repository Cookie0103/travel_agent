# SDK 适配与兼容线路

目标：在 M0.2 验证 Claude Agent SDK，M0.3 封装配置、会话、取消与事件。
当前仅 probe/ 已实现：旧 Messages API 的有限实验，不是 Agent SDK runtime。
入口：probe/flow.py 的 run_probe，仅由显式 live 测试调用，已完成一次受限实测。
后续流程：应用上下文 → SDK → MCP 工具 → SDK 结果 → 应用事件。
不变量：SDK 类型不越过适配边界；两币种独立；导入不联网；不自写通用消息循环。
设计见 docs/adr/003-claude-agent-sdk-runtime.md、plan/实操计划/02-Agent架构与实现设计.md。
