# 2026-10-03：切换 Claude Agent SDK 的文档调整

## 授权与范围

- 用户明确选择 Claude Agent SDK 承担 Agent runtime，自行实现旅行业务与工具；commerce-agents 用于理解底层机制。
- 本轮只更新开发设计、任务规格、执行规则与导航；不安装依赖、不改业务代码、不调用真实模型、不修改上游仓库。
- 起点：`batch/2026-10-03-m0-repair`，HEAD `3819723`，工作区干净。沿当前未合并增量修订文档，不把已有工作切走；本次不是继续实施 M0.3。

## 操作过程

1. 读取 AGENTS.md、plan/README、04、M0 规格、ADR-000、项目和 docs 首页，定位旧的手写循环及模型适配要求。
2. 只读检查用户提供的 commerce-agents 与 Claude Agent SDK / DeepSeek 官方资料。初次上游 `git rev-parse` 被 ownership 检查拒绝；未修改全局 Git 配置，后续用仅本命令生效的 safe.directory 检查固定版本。
3. 上游单次 safe.directory 检查成功，HEAD 为 fd4d59224ab96b43c6dc6888207c67b3bd5a24cf。读取 shopping-agent/runtime-agent-sdk 的 agent.py、commerce_common/agent_sdk.py 和依赖说明，没有运行上游。
4. 核对 SDK 概览、Python 参考、工具、权限、会话、费用和网关文档；DeepSeek 两个无尾斜杠 URL 初次读取失败，改用官方中文带尾斜杠链接读取成功。来源保存在 06 与 ADR-003。
5. 以起点干净版本为基线，用 .cache/update_sdk_docs*.py 本地辅助程序修改 Markdown/HTML。第一次文本替换因章节符号和代码标记冲突中止，已修复转换、以起点重新生成相关文档；未涉及业务代码。辅助程序只用于本次编辑，不作为项目功能提交。
6. 更新 01/02/04/05/06、M0 规格、ADR-000/002/003、AGENTS：取消自写通用循环和原始消息转换任务；保留旅行领域、工具、校验、幂等及评测；明确内部 MCP 与对外只读 MCP 的差别。
7. 同步 README、包职责、上游阅读线、学习 HTML 与简历目标稿。旧探针和其审阅页只增加历史提示，原实验结果保留。新增 docs/review/M0-sdk-route.md 作为通俗阅读入口。
8. 范围检查：M0–M4 仍 33 项；M0.2/0.3 仍是关卡，M2.4 增加 M2.3 依赖以覆盖预订对账恢复。OpenAI/Gemini 保留为后续扩展而非 SDK 原生保证；未标记新实现完成。
9. 文档一致性扫描发现学习 HTML 中两条旧路线描述及 03 中 MCP 内外边界不清，已修正；旧实验文件保留历史标记。首次文档格式检查发现 03 的 CRLF，已转 LF；随后 26 个文档、107 个相对链接、33 个任务及行数/代码块检查通过，git diff --check 通过。
10. 并行运行 dev check / dev test，均退出 0：ruff 31 文件、mypy 31 文件、3 条架构约束；pytest 70 passed、1 deselected in 2.70s。原输出保存在同名前缀 commands.jsonl；未运行 live。
11. 补充审阅材料、批次总结及两个可回退选择（其他模型暂列扩展、Skills 用受控工具）；更新完成状态的措辞，准备按正常钩子提交文档，不跳过验证。

## 恢复点

文档调整和验证已完成；提交主题为 `M0: 更新 Claude Agent SDK 开发路线与验收边界`，实际提交成败以 git log 和 .cache/agent-sdk-docs-commit-result.txt 为准。恢复时先看 Git 状态和新版 M0.2；已有两次 Messages 请求不算 SDK 兼容证据。没有改业务代码、依赖/.env 或上游，没有产生新的模型费用。
