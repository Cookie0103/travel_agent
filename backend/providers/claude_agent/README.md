# SDK 应用边界

`ClaudeRuntime.execute` 接收应用上下文、用户文本、已核对的 SDK 会话 ID。
`options` 只组合 SDK 配置和进程内 MCP 工具；不实现模型/工具消息循环。
SDK 原始消息在这里转换为 `RuntimeEvent` / `RuntimeOutcome`。
`Agent.run` 负责业务会话归属、版本/模型切换和唯一终态。
完整成功轮次通过checkpoints绑定用户/会话/版本/revision与私有SDK文件指纹，复用SDK resume。
中断、文件丢失/损坏、条件变化时按当前业务快照新建；不透明重放未完成工具。
运行时必须置于隔离工作进程，共用 M0.2 的环境、费用和进程保护。
旧 CLI 缺少 verbatim_prompts 时，拒绝含 @ 或行首斜杠的输入。
测试使用脚本化 SDK 消息；不把替身结果当模型效果。

`live.run_live` → 费用守卫 → `worker` → `Agent` → SDK/MCP → 旅行工具。
`settings`按LLM_PROVIDER显式选DeepSeek/CNY或Anthropic/USD，模型/价表共用。
`budget/request/response/guard/http`共用预占/结算；DeepSeek请求上限512 KiB，其他模型128 KiB；TRACE记录model_req_received原始大小、model_req_start转发大小/上限、model_req_rejected拒绝大小/阶段/原因（不记正文/密钥）；USD累计授权为0，密钥和日预算不放行。
`environment/process/bootstrap/windows_job` 共用环境隔离与子进程清理。
`backend/limits.py` 读取环境变量并给出价表/预算校验（档位在 `backend/profile.py`），`ledger`在网络调用前落盘计次与保守费用（写入失败就不发送）；不同币种分开记账。
父进程的私有报告在 .cache/sessions；前端/CLI 不展示 SDK session_id 或原始 stderr。
GuardedRuntime将API事件/取消接到同一live入口；父进程验证后才报告终态；用量/实际CLI版本只从本轮核验报告取，API Trace仍用已提交PG事件。
DatabaseTools用Selector线程运行数据库工具，SDK进程保留Windows Proactor。
私有事件文件只用于跨进程传递；UI读取PostgreSQL中的已提交应用事件。
业务快照与revision同次读取；轮次中条件变化不保存续接指针。指针只由worker管理。
原生Stop hook仅一次纠正条件齐全但未完成的业务待办；合法追问/硬失败可停，不新增模型循环或扩大预算。
每个追加用户轮次刷新快照并重建工具作用域；版本变化时新建SDK会话。
compact_boundary只转为context_compacted事件，不复制摘要或改写SDK历史。
评测可注入固定阶段守门；两组SDK和schema相同，真实HTTP上限仍由父进程Guard独立限制。
Claude固定Haiku4.5经实际CLI本地脚本往返；真实Anthropic服务与新模型协议尚未验证。

SDK普通搜索6轮，DB完整规划12轮；HTTP/工具/费用独立限制。已知取消/轮数终止优先于最后stop_reason，不完整结果无成功checkpoint。
