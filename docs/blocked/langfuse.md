# Langfuse Cloud接入与页面验收

当前状态（2026-10-04）：用户配置本地`.env`并授权验证，Japan项目认证200、一次离线查询OTLP上传成功；v2 observations读回200，4个span与本地ID/项目/Trace完全一致。[脱敏证据](../evidence/m05-langfuse-cloud-2026-10-04.json)。0模型请求，无正文/参数值外发，密钥与项目ID仅私有缓存。API/server显式开关的23相关真实PG/本机HTTP回归已通过。

此前“缺配置”记录为历史。当前只剩页面显示未验：新建in-app浏览器tab出现“没有访问此Trace权限”和Sign In，原因是该浏览器会话未登录；API密钥不是网页登录凭据。没有代注册/修改账户或要求用户中断开发，其他工作继续。私有receipt保存实际Trace链接，用户自行登录所属项目后可查看。

2026-10-03，M0.5：`.env` 中 Langfuse public key、secret key、base URL 均未配置（只核对是否为空，没有记录值）。
自托管官方栈需要本项目已排除的 Redis 等组件，按 ADR-000/005 使用 Cloud 导出选项。
本地 OTel Trace、导出接口及其离线测试继续实施；Langfuse 中查看真实 Trace 的链接/截图保持待验收。
这不阻塞评测、数据库业务或前端开发，也不要求用户现在中断工作去注册。

2026-10-04再次仅核对是否为空：三个字段仍未配置。OpenTelemetry是记录/传输标准和库，本身不需要账号或API key；Langfuse Cloud需要项目的public key、secret key和该区域base URL，和DeepSeek/Claude的模型密钥无关。只能在本地`.env`填写，不在对话或Git中提交。

配置来自Langfuse项目Settings的API Keys。`LANGFUSE_BASE_URL`填所在区域的服务首页URL（例如EU的`https://cloud.langfuse.com`、Japan的`https://jp.cloud.langfuse.com`），不重复添加API路径。CLI查询使用`--trace-cloud`；网页后台使用`uv run --env-file .env python -m backend.server --trace-cloud`，若需要已授权真实模型再显式加`--live`。仅填key不会自动上传，也不会改变模型预算。

API与CLI复用同一个OTel/OTLP HTTP导出器，不增加第二套观测框架。API先保存本地记录，再建立本轮独立云导出器；配置缺失/网络失败只记录脱敏告警，不撤销已提交的业务。Trace上传范围沿用ADR005：工具名称、参数键名、运行状态和版本等摘要，不上传聊天正文或参数值。离线API Trace没有真实模型usage，不据此宣称完整模型费用时间线。

页面验收仍需用户拥有的Langfuse项目凭据，agent不代注册账号。凭据到位后可用一次免费本地业务运行验证上传及页面显示；不需要调用Claude或重新支付模型费用。

当前官方依据：[Langfuse OTel配置与区域端点](https://langfuse.com/integrations/native/opentelemetry)、[OpenTelemetry Collector配置](https://opentelemetry.io/docs/collector/configuration/)。当前导出器已经发送v4 ingestion header，无需为追新增加Langfuse SDK。
