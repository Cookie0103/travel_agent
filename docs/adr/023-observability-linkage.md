# ADR-023 同轮PG锚点、HTTP观测与Langfuse分数

日期：2026-10-14；状态：实施并真实联验。依据：[本批T6](../plans/2026-10-13-interaction-memory-eval.md)，补充ADR-005。

逐HTTP输入token遵循[官方OTel说明](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/registry/attributes/gen-ai.md)：input_tokens包含实际观察到的普通、缓存读取和缓存写入输入。guard保留三种数值，span求和，不对缺失usage捏造零用量；合成10+40+5的RED→GREEN验证总55，旧无缓存观测不变。

消息事务为新run分配32位trace_id（迁移0017）；历史行保持nullable，不回造旧追踪。复用OTel RandomIdGenerator，仅替换trace ID生成；事件的真实时间、tool_call_id和守卫每次HTTP的纳秒时间映射为span，不接管SDK执行循环。

每个span都携带HMAC session/user假名、mode/provider/profile、run_id/git_sha/revision。HMAC密钥优先TRAVEL_TRACE_HMAC_KEY，兼容已有LANGFUSE_SECRET_KEY；缺密钥时不发送原身份。云出口仍须显式trace-cloud、完整HTTPS配置；不透出prompt/answer/quote、模型私有文件或供应商正文。完整响应用量与未知费用保留预占分开记录，不按美元解释CNY费用。200但没有完整校验usage的响应标为失败，不把HTTP成功当模型完成。

保留既有OTLP导出及v4请求头，不引入Langfuse SDK或第二套runtime。数值分数使用已有httpx调用/api/public/scores，以trace+名称确定幂等ID；失败只记录固定状态，不覆盖业务结果。联验只在项目入口显式--live --trace-cloud时运行，用本地合成会话，不调用旅行供应商。

读回使用[官方Public API](https://langfuse.com/docs/api-and-data-platform/features/public-api)的v2 observations与v3 scores，限定trace ID和时间，observations只读core/basic/trace_context/metadata，排除io。v4要求每个span均携带上下文，见[迁移说明](https://langfuse.com/integrations/native/opentelemetry/migration-to-v4)。只保存白名单证据，不存云响应正文。

实测：PG与云工具数量2=2，模型HTTP3=3，HMAC/tags一致，数值score读回；0供应商调用，0.078608CNY。见[脱敏证据](../evidence/t6-langfuse-linkage-2026-10-13.json)。这些数字只证明一次链路验收，不证明模型任务质量。

2026-10-14 F3：受保护本地eval构造方显式指定synthetic来源，生产默认live且不读取评测来源开关。适配器、证据、工具、页面和参考评审使用同一来源标识，合成报价不可从服务层进入模拟暂留；source_label为合成评测数据，不以测试数字冒充供应商实时结果。
