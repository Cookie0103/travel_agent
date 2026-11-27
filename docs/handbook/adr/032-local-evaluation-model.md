# ADR-032 本地评测模型经既有 Claude Agent SDK 接入

日期：2026-11-28
状态：隔离线路已准备，等待固定权重和 A7 实机十题验收

## 背景

第二阶段的大规模评测使用本机通义千问。DeepSeek Flash 保留给已授权的小样本验收。Mac 为 Apple Silicon、64 GB 统一内存，运行仍使用仓库固定版本的 Claude Agent SDK 和 Claude CLI。

## 决定

- A7 候选为 Ollama 官方库的 `qwen3.8:27b-q4_K_M`。约 18 GB。首次下载须待自动审批放行，验收时记录实际权重摘要、Ollama 版本、上下文窗口和运行资源。模型来源见 [Ollama 模型卡](https://ollama.com/library/qwen3.8:27b-q4_K_M)。
- Ollama 兼容 Anthropic Messages，负责本机模型推理。应用仍使用原有工具定义、校验、专用数据库与 SDK 进程。证据由工具返回，费用与方法见阶段计划。[接口与工具调用文档](https://docs.ollama.com/api/anthropic-compatibility)
- 本地评测显式启用，限定专用本地评测库，连接固定的回环地址 `127.0.0.1:11528`。Ollama 以 `OLLAMA_NO_CLOUD=1` 运行。验收设 `OLLAMA_CONTEXT_LENGTH=32768`，与本机线路的请求上限一致。使用固定本机模型名，不把真实供应商凭据传给本地服务，网络故障时结束该次试验。
- 本机计价为 0，既有模型请求次数、输出 token 上限和持久化运行证据仍适用。本机账本独立于 DeepSeek 的阶段账本。无模型权重时只做夹具测试，A7 的实机结论保持待验证。

## 验证和回退

在 64 GB Mac 上执行 10 个多轮案例，记录逐题是否遵守工具契约、是否出草稿及耗时。至少 8 题满足通过条件后才采用本机模型做大样本。实测未达标时执行开发计划 D9 已定的小样本路径。

- [第二阶段开发计划](../../phase2/plans/2026-11-27-judge-evolution.md)
- [既有 SDK 接入](003-claude-agent-sdk-runtime.md)
- [请求与费用边界](004-sdk-request-budget-boundary.md)

本机模型验收题由 `python -m eval.v3.local_probe` 列出，来自反思划分。使用 `dev eval-v3 --local-model --split reflection` 和列出的题目，给汇总入口传入本次的 `trials.jsonl`。当前线路只用于 A7 工具调用与草稿可行性验证。本机记忆抽取和 D5 基线需要单独补齐实际证据。
