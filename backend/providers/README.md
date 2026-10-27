# SDK 适配与兼容线路

入口：claude_agent/application.GuardedRuntime → live/worker → ClaudeRuntime。
Claude Agent SDK驱动工具往返，隔离worker与父进程费用守卫控制实际HTTP请求。
价表、预算配置在 backend/limits.py，限额档位在 backend/profile.py；费用账本在claude_agent/ledger.py。
hotel_fixture/routes_fixture读取自编模拟报价与路线；不获取外部实时数据。
不变量：SDK 类型不越过适配边界；两币种独立；导入不联网；不自写通用消息循环。
设计见 docs/adr/003-claude-agent-sdk-runtime.md、docs/design/02-architecture.md。
