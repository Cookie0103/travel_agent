# HTTP 与 SSE 接口边界

只通过 services 或 agent 调用项目其他层；M1.1 起实现。

入口：尚无可执行入口；M0.1 只创建包边界。
关键流程：只通过 services 或 agent 调用项目其他层；M1.1 起实现。
不变量：遵守 AGENTS.md 的分层规则，不在导入包时执行网络或业务写操作。
