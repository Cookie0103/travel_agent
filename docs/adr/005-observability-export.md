# ADR-005：本地 OTel 记录与可选 Langfuse 导出

状态：accepted（2026-10-03，落实 ADR-000 的可观测选择；云端 UI 验收待凭据）。

当前 Langfuse 自托管 Compose 依赖 Redis、ClickHouse、对象存储与 PostgreSQL。
本项目禁止引入 Redis/消息队列，ADR-000 已允许开发期使用 Langfuse Cloud；因此不安装整套额外服务。
本地 `.env` 尚未配置 Langfuse 项目凭据。完成本地 Trace 和 OTLP 导出能力后继续其他开发，UI 链接/截图不能记为已验收。

采用官方 `opentelemetry-sdk` 与 `opentelemetry-exporter-otlp-proto-http`，由 uv 锁定版本。
现有依赖没有标准 OTel Span/OTLP 导出能力，不自行实现协议，也不增加自动模型 instrumentation。
使用 SDK 的 InMemorySpanExporter 收集后，ConsoleSpanExporter 保存私有 JSONL；只有显式选择云导出且配置完整才批量调用 OTLP HTTP exporter。
显式检查导出结果，避免 SimpleSpanProcessor 吞掉写入异常后误报成功。导出失败记录安全状态，不改变业务结果。
已有直接 OTel 的应用事件契约即可满足当前需求，暂不额外引入 Langfuse 专用 SDK。

记录真实应用事件的时间和工具调用 ID，在父进程按这些时间建立 TaskRun → SDK/离线执行 → 工具 span。
这是对已发生事件的映射，不是模拟执行；缺事件/模型 usage 时明确标记缺口，不编造模型子调用。
SDK 原始会话和全文不导出；属性只含运行ID、工具名、参数键名、状态、实际模型与守卫用量摘要。
完整响应用量与本轮账本金额分开；超时保留的预占属于后者，不拿成功响应的小计冒充整轮费用上界。

备选：只用日志缺少标准 Trace；自写网络 exporter 增加重复代码；无凭据时伪造 Langfuse UI 证据不可接受。

来源：[Langfuse Compose](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml)、
[Langfuse OTel 接入](https://langfuse.com/integrations/native/opentelemetry)、
[OTel Python exporters](https://opentelemetry.io/docs/languages/python/exporters/)。
