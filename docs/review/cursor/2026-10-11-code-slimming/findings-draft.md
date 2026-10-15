# 审查发现草稿 — Code Slimming (2026-10-11)

> 主会话直接审查的原始发现（Task 派发通道故障后改为人工审查）。
> 此文件为工作草稿，最终整理进 proposals.md 后交 Codex 审批。

## S 区（backend services + api + 根杂项）

### S-1 limits.py 三常量零引用
- 位置: backend/limits.py:10-12（BASE_URL/MAX_TOKENS/MAX_REQUEST_BYTES）
- 现象: 定义后全项目无引用
- 证据: Grep `BASE_URL|MAX_TOKENS|MAX_REQUEST_BYTES` 全仓库 *.py，仅定义处命中；
  其余命中为 LANGFUSE_BASE_URL/DATABASE_URL/ANTHROPIC_BASE_URL 等无关环境变量名
- 初步建议: 删除三常量
- 置信度: 高