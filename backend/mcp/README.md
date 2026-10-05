# SDK工具桥接与对外只读查询

`build_server` 从 `tools.contracts` 的同一份定义注册 SDK MCP 工具。
身份从服务端 `RunContext` 注入，不从模型参数读取。
执行调用注入的 `ToolExecutor`，结果用 SDK 的 `is_error` 标记。
工具事件只包含名称/错误码，不记录完整参数或结果。
`uv run python -m backend.mcp.server`在127.0.0.1:8002启动独立Streamable HTTP。
地址`http://127.0.0.1:8002/mcp/{session_id}`；使用本人API已创建会话及Bearer令牌。
仅开放search_content/get_article/search_places/get_place_facts，契约/handlers同业务工具。
协议/请求大小由MCP2.3官方Server与StreamableHTTPSessionManager处理，不手写JSON-RPC。
每个HTTP重新认证并检查会话归属；stateless避免跨连接共享身份。Host/Origin限本机。
不提供状态/酒店/预订工具；查询只附带生成可追溯Evidence，不修改旅行条件。
