# SDK 应用边界

`ClaudeRuntime.execute` 接收应用上下文、用户文本、已核对的 SDK 会话 ID。
`options` 只组合 SDK 配置和进程内 MCP 工具；不实现模型/工具消息循环。
SDK 原始消息在这里转换为 `RuntimeEvent` / `RuntimeOutcome`。
`Agent.run` 负责业务会话归属、版本/模型切换和唯一终态。
当前仅定义进程内续接边界；跨进程业务恢复属于 M2.4。
运行时必须置于隔离工作进程，共用 M0.2 的环境、费用和进程保护。
旧 CLI 缺少 verbatim_prompts 时，拒绝含 @ 或行首斜杠的输入。
测试使用脚本化 SDK 消息；不把替身结果当模型效果。
