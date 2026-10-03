# 进程内工具桥接

`build_server` 从 `tools.contracts` 的同一份定义注册 SDK MCP 工具。
身份从服务端 `RunContext` 注入，不从模型参数读取。
执行调用注入的 `ToolExecutor`，结果用 SDK 的 `is_error` 标记。
工具事件只包含名称/错误码，不记录完整参数或结果。
M3.3 才提供对外只读 MCP；这里不启动外部服务。
