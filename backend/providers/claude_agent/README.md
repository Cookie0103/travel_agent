# SDK 应用边界

`ClaudeRuntime.execute` 接收应用上下文、用户文本、已核对的 SDK 会话 ID。
`options` 只组合 SDK 配置和进程内 MCP 工具；不实现模型/工具消息循环。
SDK 原始消息在这里转换为 `RuntimeEvent` / `RuntimeOutcome`。
`Agent.run` 负责业务会话归属、版本/模型切换和唯一终态。
当前仅定义进程内续接边界；跨进程业务恢复属于 M2.4。
运行时必须置于隔离工作进程，共用 M0.2 的环境、费用和进程保护。
旧 CLI 缺少 verbatim_prompts 时，拒绝含 @ 或行首斜杠的输入。
测试使用脚本化 SDK 消息；不把替身结果当模型效果。

`live.run_live` → 费用守卫 → `worker` → `Agent` → SDK/MCP → 旅行工具。
`budget/request/response/guard/http` 共用 M0.2 验证过的人民币与请求限制。
`environment/process/bootstrap/windows_job` 共用环境隔离与子进程清理。
上述模块由探针移动到这里；探针仍复用同一实现，不维护副本。
父进程的私有报告在 .cache/sessions；前端/CLI 不展示 SDK session_id 或原始 stderr。
