# 后端代码

这里放整个后端，不只放 HTTP 路由。当前主要是目录占位；providers/probe 有独立协议探针，没有可运行旅行服务。

| 子目录 | 以后负责什么 |
| --- | --- |
| api | 收到网页的 HTTP 请求，发送响应和 SSE 事件 |
| services | 组织一次业务操作，协调规则检查和数据库读写 |
| agent | 旅行上下文、Skills 与执行策略，经适配调用 SDK |
| providers | Claude Agent SDK 配置、会话与应用事件转换；旧 probe 保留 |
| tools | 提供景点查询等工具，检查参数和调用权限 |
| domain | 定义旅行条件、事实、行程、预订等业务对象和规则 |
| persistence | 数据库表映射、迁移、查询和事务 |
| adapters | 对接外部数据或服务 |
| mcp | 内部 SDK 工具桥接；后续对外只读 MCP 服务 |

未来主流程：网页 → api → services/agent → 需要的工具、模型和业务规则 → 返回结果。
入口：尚未实现；M0.1 只划定目录。
不变量：domain 不依赖其他业务层，api 不直接读写数据库。
