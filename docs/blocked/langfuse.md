# Langfuse Cloud接入与页面验收

当前状态（2026-10-04）：用户配置本地`.env`并授权验证，Japan项目认证200、一次离线查询OTLP上传成功；v2 observations读回200，4个span与本地ID/项目/Trace完全一致。[脱敏证据](../evidence/m05-langfuse-cloud-2026-10-04.json)。0模型请求，无正文/参数值外发，密钥与项目ID仅私有缓存。API/server显式开关的23相关真实PG/本机HTTP回归已通过。

此前“缺配置”记录为历史。页面验收现已通过：复用用户已登录的Chrome，原Trace和明确chain/agent/tool分类的后续Trace均显示四个节点及completed状态，读回类型也完全匹配。初次匿名in-app会话曾显示访问权限错误/Sign In，作为历史失败保留；API密钥不是网页登录凭据。无账户修改，实际项目/Trace链接仅私有receipt。

2026-10-03，M0.5：`.env` 中 Langfuse public key、secret key、base URL 均未配置（只核对是否为空，没有记录值）。
自托管官方栈需要本项目已排除的 Redis 等组件，按 ADR-000/005 使用 Cloud 导出选项。
本地 OTel Trace、导出接口及其离线测试继续实施；Langfuse 中查看真实 Trace 的链接/截图保持待验收。
这不阻塞评测、数据库业务或前端开发，也不要求用户现在中断工作去注册。

2026-10-04再次仅核对是否为空：三个字段仍未配置。OpenTelemetry是记录/传输标准和库，本身不需要账号或API key；Langfuse Cloud需要项目的public key、secret key和该区域base URL，和DeepSeek/Claude的模型密钥无关。只能在本地`.env`填写，不在对话或Git中提交。

配置来自Langfuse项目Settings的API Keys。`LANGFUSE_BASE_URL`填所在区域的服务首页URL（例如EU的`https://cloud.langfuse.com`、Japan的`https://jp.cloud.langfuse.com`），不重复添加API路径。CLI查询使用`--trace-cloud`；网页后台使用`uv run --env-file .env python -m backend.server --trace-cloud`，若需要已授权真实模型再显式加`--live`。仅填key不会自动上传，也不会改变模型预算。

API与CLI复用同一个OTel/OTLP HTTP导出器，不增加第二套观测框架。API先保存本地记录，再建立本轮独立云导出器；配置缺失/网络失败只记录脱敏告警，不撤销已提交的业务。Trace上传范围沿用ADR005：工具名称、参数键名、运行状态和版本等摘要，不上传聊天正文或参数值。离线API Trace没有真实模型usage，不据此宣称完整模型费用时间线。

当前无需补充凭据。真实认证、上传、读回与页面显示均已有证据；离线Trace没有模型子调用/token/实际模型账单，不扩张为这些验收。两个免费业务运行均未调用Claude或DeepSeek。

当前官方依据：[Langfuse OTel配置与区域端点](https://langfuse.com/integrations/native/opentelemetry)、[OpenTelemetry Collector配置](https://opentelemetry.io/docs/collector/configuration/)。当前导出器已经发送v4 ingestion header，无需为追新增加Langfuse SDK。

2026-10-04实际SDK Cloud补验：独立审查P2指出Fixture Trace不足覆盖M0.5 SDK信息。原成功SDK查询报告仅本地读取并保留SHA，明确移除正文/参数值/原身份及会话信息，以新随机ID代替；使用共享trace_report导出已核验白名单摘要。初次原报告+网络组合命令被自动审批拒绝，脱敏载荷及本地span字段证据完成后，仅读脱敏文件的上传获批；无旁路。真实认证/上传/四span精准读回/type匹配，已登录Chrome看到agent.sdk、两工具、deepseek-flash、19773tokens、原CLI/SDK版本及model_subcalls_observed=false；Input/Output为空。历史3HTTP/.042048CNY/token不改，0新模型请求/费用，实际项目链接仅私有receipt。不伪造模型子调用。
