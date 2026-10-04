# Claude Agent SDK 接入记录

2026-10-03。这里只记录可复核的观察，不用旧 Messages 探针代替 SDK 验收。

## 版本与环境

- Python 3.12.12 / Windows 原生；claude-agent-sdk 0.2.163、MCP 2.3.0（uv.lock）。
- SDK 的 Windows 源码发行包没有附带 CLI；当前使用已有原生 Claude CLI 2.1.114，可通过 TRAVEL_CLAUDE_CLI 指定路径。不修改用户全局安装/配置。
- API 来源固定 DeepSeek，模型从 DEEPSEEK_MODEL 读取。SDK subprocess 不继承真实 key、Claude OAuth、其他供应商开关、代理、Node 注入或 OTel 凭据。

## 已完成的离线观察

- 真正 SDK + 本机 CLI + 进程内 MCP + 本地脚本化 SSE 完成工具往返；CLI 请求只含指定合成工具，SDK 执行结果包含工具生成的随机挑战值。
- tools=[]、strict_mcp_config、setting_sources=[]、skills=[]、隔离目录生效于上述实验；没有把 allowed_tools 单独当成安全隔离。
- 未知模型/协议功能/工具集合、过大输入/输出拒绝转发。缺最终 usage、输出计数倒退、重复终止、未闭合内容块拒绝结算。
- 受控慢流在总期限内结束；Windows Job + 启动握手在超时后关闭后代，故意推迟 Job 分配也不会抢先启动任务。
- 费用：每次实际 HTTP 尝试先 fsync 预占整模型上下文与输出上界；成功完整 usage 按高峰单价结算，失败/中断保留全部占用。次数不退款；累计 5 CNY/100 次和每日额度同时检查，旧探针同日占用纳入每日。
- SDK 与 HTTP 子进程分别设总期限；所有转发仅到固定官方 HTTPS 地址，不跟随重定向、不自动重试。

## 真实验证

已通过一次真实 SDK → DeepSeek → 合成工具 → 最终回答。命令：`uv run --env-file .env python -m pytest -m live tests/live/test_agent_sdk_integration.py -v`，1 passed（4.16 秒）；旧 pytest 缓存目录权限产生一个非功能警告，未因此重跑付费测试。

| HTTP 请求 | 输入 token | 缓存输入 token | 输出 token | 高峰价保守 CNY 估计 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 439 | 0 | 56 | 0.001326 |
| 2 | 150 | 384 | 70 | 0.001628 |

共 2 次，保守累计 0.002954 CNY；缓存输入也按未命中高峰价估算，不冒充供应商实际账单。guard_failures 为空，SDK terminal_reason=completed。每次 2.113536 CNY 预占均在完整 usage 后结算，无未结预占。

脱敏事件证据：[JSON 摘要](evidence/sdk-roundtrip-2026-10-03.json)。真实账本在 `.cache/model-budget/deepseek.jsonl`，SDK session 文件不提交。
后续 live 使用 `python -X utf8 -m pytest ... -p no:cacheprovider`，避免控制台编码和缓存警告。

## 已知限制

- 仅合成只读工具、新会话、小输入；还不能证明多用户隔离、恢复、压缩、并行工具或业务正确性。
- CLI 2.1.114 不保证新版本的 verbatim_prompts；当前探针提示词固定，没有用户文件引用。正式接受用户文本前必须处理 @path / slash 命令解释风险，不能照搬此探针宣称隔离完成。
- 启动守卫是应用边界，不是恶意本机进程的 OS 沙箱。原始 SDK 会话仅留在被忽略的私有 .cache 目录。
- Flash 每次要先有约 2.11 CNY 可用余额才能按最大上下文预占；真实用量很小也可能因保守预占提前停止。这是费用保护的取舍，不自动扩大额度。

依据：[SDK Python](https://code.claude.com/docs/en/agent-sdk/python)、[DeepSeek Claude Code 接入](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/claude_code/)、[人民币价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[本项目 ADR-004](adr/004-sdk-request-budget-boundary.md)。
