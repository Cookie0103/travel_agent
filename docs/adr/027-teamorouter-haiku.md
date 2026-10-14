# ADR-027：TeamoRouter Haiku 5.5 接入

状态：accepted（2026-10-14，用户明确要求配置并推送上线，真实Claude由用户手测）。

复用Claude Agent SDK、回环费用守卫和Anthropic Messages线路。`ANTHROPIC_BASE_URL`只允许官方根地址和用户指定的`https://api.teamorouter.com`，默认官方；保留HTTPS、固定`/v1/messages`、`x-api-key`认证、不跟随重定向，不支持任意URL、端口或URL凭据。真实key继续只经stdin传给受控传输进程，SDK只得到本地令牌。

新增固定模型`claude-haiku-5-5`，沿用非思考设置。旧CLI可能省略thinking，守卫明确补`disabled`；只接受low/medium/high effort。删除CLI默认采样参数1/0.99，拒绝其他自定义采样及top_k，不变更旅行工具/校验协议。沿用128KiB请求上限和HUMAN 24模型HTTP/4次校验。

Haiku 5.5按最高长上下文档保守核算：输入0.50、输出2.50美元/百万token，1小时缓存写乘2、1M上下文上限；不依赖网关动态折扣，不声称等于实际网关账单。完整usage才结算，失败保持预占。

用户本次授权线上Claude每日10美元，不限制累计次数。`ANTHROPIC_LIVE_ENABLED=1`显式开启美元线路；默认0保持此前零美元授权，key和日预算不会自行授予调用权限。日预算仍拒绝缺失/0/非法/不足，HUMAN不免除美元日限，账本跨部署保留。DeepSeek和人民币规则不变。

备选：改用OpenAI兼容接口会绕开现有Messages传输与SDK；任意网关URL扩大凭据转发范围。均不采用。不上新依赖、不升级SDK、不实现第二套runtime、不做真实Claude验收。

来源：[TeamoRouter原生接口](https://api.teamorouter.com/docs/api-integration)、[Haiku 5.5价格](https://platform.claude.com/docs/en/models/haiku-5-5/overview)、[迁移参数](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide)、[非思考支持](https://platform.claude.com/docs/en/build-with-claude/thinking)。网关可用性和旅行效果由用户上线手测，离线测试不替代真实验收。
