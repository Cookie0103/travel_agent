# M0.2：DeepSeek 协议验证记录

> 历史 Messages 探针证据。2026-10-03 用户选择 Claude Agent SDK，现行关卡见 [新版 M0.2](../tasks/M0.md)。以下实测不证明 SDK 兼容；未测字段继续保留，不自动追加付费请求。

当前：代码与离线检查通过；用户明确授权后的最小真实往返通过（2 次请求）。完整协议矩阵仍有未验证项，M0.2 关卡未完成，不开始 M0.3。

## 请求规格与限制

- 本地 DEEPSEEK_MODEL=deepseek-flash；请求目标为 DeepSeek 的 Anthropic 兼容接口。密钥不写文档，读取 .env 不等于请求已经发送。
- max_tokens=1024，thinking=enabled，budget_tokens=512，tool_choice=auto，disable_parallel_tool_use=true；请求内容上限 8192 字节。
- 合成 lookup_fixture 工具仅接受 Kyoto/Osaka；京都固定返回合成样本，大阪固定返回 unavailable 且 is_error=true；工具定义带 cache_control=ephemeral。
- 第一轮流式请求获取完整 tool_use 参数；随后按 tool_use_id 反向排列结果，连同完整 assistant 块在内存中续接。第二轮要求最终回答，不自动进入第三轮。
- 最多两次流程/四次 HTTP 尝试；本次单独确认的一次流程最多两次请求，Flash 每次先占用 0.05 元保守费用。人民币预算与美元预算独立。
- 模型单价按 2026-10-03 官方高峰、缓存未命中价格估算；usage_cost_upper_cny 是费用上界估算，不是平台账单。未知 usage 不退回保守占用。

## 差异表与证据

| 项目 | 本次实际响应 | 结论 |
| --- | --- | --- |
| 思考模式 + 强制 tool_choice | 尚未发送；最小流程使用 auto，不覆盖强制工具 | 无法判断 |
| 思考块回传格式、是否必须回传 | 首轮含 thinking，完整 assistant 块原样续接成功；没有省略块的对照请求 | 格式符合文档；是否必须回传无法判断 |
| 多个工具调用的结果配对顺序 | 首轮 2 个 tool_use；结果按 ID 配对并反向提交，第二轮 end_turn | 本次顺序交换被接受，符合文档；不证明任意排序均可 |
| 流式工具 JSON 完整性 | 两个参数对象经 SDK 拼接并通过本地参数校验；两轮均有 message_stop | 本样本符合文档；中断分片仅有离线证据 |
| 返回的实际模型名 / 别名映射 | 两轮 model 均为 deepseek-flash；没有尝试 claude-* 别名 | 明确模型名符合文档；别名映射无法判断 |
| tool_result.is_error 是否被忽略 | 大阪合成失败结果携带 is_error=true 与正文 status=unavailable，请求被接受 | 是否被忽略无法判断；未做控制变量对照 |
| cache_control 是否报错 / 是否被忽略 | 两次 tools 都带 cache_control=ephemeral，均未报错 | 接受字段符合文档；忽略行为/缓存收益无法判断 |
| disable_parallel_tool_use 是否被忽略 | 设为 true，首轮仍返回 2 个工具调用 | 本次明确未限制多个调用，符合文档 |
| budget_tokens / mcp_servers / document 等不支持项 | 未做独立试验；本轮不追加大量请求 | 无法判断 |
| 流中断后的真实续接 | 离线验证中断时不使用半消息；未进行真实中断/恢复实验 | 无法判断 |

## 当前验证

- dev check：31 个源文件类型检查通过，3 条分层契约保持。
- dev test：70 passed、1 deselected；新增测试均为离线，不产生 API 费用。
- live 命令第一次被自动审批拒绝，未启动进程；用户随后明确允许本次实测，再执行同一命令，1 passed in 2.73s。
- 2026-10-03 12:06（Asia/Tokyo）：第一轮 input=355、output=81；第二轮 input=499、output=18；按最高时段/不享受缓存折扣估算费用上界共 0.002500 元人民币，非平台实际账单。
- 本地账本：1 次流程、2 次请求、success；保守费用占用共 0.10 元，没有返还占用。成功标记阻止再次付费运行；没有调用美元线路。
- [脱敏实测摘要](../operations/2026-10-03-m02-protocol.result.json) 为本次 .cache 摘要的公开副本，不包含完整回答或思考块。
- 原始模型推理不落盘；.cache/m02-protocol/ 保存仅含结构、用量与状态的摘要以及次数/费用账本。

官方来源：[兼容接口](https://api-docs.deepseek.com/zh-cn/guides/anthropic_api/)、[人民币价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。文档说明与本表的真实实测结果分开，不能互相代替。
