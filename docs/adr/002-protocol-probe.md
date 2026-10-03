# ADR-002：M0.2 小范围协议实测

状态：accepted（2026-10-03，落实 ADR-000 及用户调用限制）

- 按 ADR-000 使用 anthropic SDK，只放在 providers 边界内；复用它的 SSE 拼接与类型。标准库虽可发 HTTP，但自写流式解析会混入协议实测，不选。SDK max_retries=0，固定 DeepSeek 官方 HTTPS 地址和明确模型名。
- 实测模块独立于尚未开始的 M0.3，不在此固定 Message/ModelProvider 公共接口；使用两个无业务数据的模拟查询工具。
- 先做离线 FakeClient 流程和 HTTP 模拟失败验证；live 默认排除，显式 pytest -m live 才启动，.env 由 uv 的 --env-file 加载。
- 本批最多 2 次流程、4 次 HTTP 尝试，跨进程与跨天保留本批次数。一次成功的最小往返后停止，不自动继续全套协议实验。
- 人民币/美元账本按计费来源分开。本探针只调用 DeepSeek；不实现其他模型调用，SDK 类型名不代表计费供应商。
- 最小本地保护：在发请求前持久记录一次尝试及保守费用占用；不知道 usage 时不退回占用。实际 usage 费用另记，不把保守估算冒充供应商账单。不是 C 档多 worker 预算预留/结算系统。
- 使用 Decimal；按官方最高时段单价、缓存未命中价估计，限制请求字节数和 max_tokens。每日使用 UTC 日期作为确定的重置边界；重启不清账，文件损坏/并发占用则拒绝调用。
- 密钥只在内存进入 SDK；不保存原始流、推理文本或 SDK 异常正文，只保存合成请求规格、响应结构、工具配对、事件类型、模型名、usage 与错误码。
- 未测试字段保持“无法判断”；收到 200 只证明本次请求被接受，不能证明字段被忽略或思考块必需。
- 用户补充模型必须可配置：DEEPSEEK_MODEL 支持已核对单价的 deepseek-flash / deepseek-v4-pro，缺失或未知模型拒绝调用。选定 Flash 做本批最小实测，SDK 不使用 claude-* 别名。模型价格变化时必须复核本探针中的价表，不能当作长期价格数据库。
- 离线边界测试使用 anthropic 已安装的 httpx2.MockTransport；这是测试替身，不发网络请求，也不另引入网络库依赖。

来源：[DeepSeek 兼容接口](https://api-docs.deepseek.com/zh-cn/guides/anthropic_api/)、[人民币价目](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[SDK](https://github.com/anthropics/anthropic-sdk-python)。
