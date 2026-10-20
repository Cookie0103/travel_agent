# 操作与运行记录

放**原始过程和操作手册**：执行过的命令与真实输出摘要、失败尝试细节、部署/回退操作。任务状态不写这里，只链接回[批次计划](../plans/README.md)（规则见 plans/README §1、§4）。2026-10-02/03 的旧日志已迁入 [archive/operations/](../archive/operations/)。

| 我想知道… | 文件 | 说明 |
| --- | --- | --- |
| Product V2 批次怎么调查、修复、真实验收的 | [product-v2.md](product-v2.md) | 约 190 KB，按 P-编号分节（如 P73 前端 standalone 构建与重启）；先用批次计划找到 P-编号再来搜 |
| 本地验证、Railway 私有对话只读导出、Langfuse 联验、V2 评测命令（eval-v2 / eval-memory / eval-simulator / eval-v3 / eval-calibration）、盲标、TeamoRouter、部署中断残留锁 | [interaction-memory-eval.md](interaction-memory-eval.md) | 2026-10-13 起的操作手册，含 live 授权与预算注意事项 |
| 测试怎么跑、环境问题 | [../testing/README.md](../testing/README.md) | 测试总览 |
| 2026-10-02/03 的 M0 命令与日志 | [../archive/operations/](../archive/operations/) | 历史，只读 |

## 记录要求

- 新增操作记录：长命令输出放这里，批次计划里只留摘要和链接。按批次主题新建 `YYYY-MM-DD-主题.md` 或追加到上表对应文件，并在上表加一行。
- 有 `--live`/`--trace-cloud` 的命令，必须写明授权来源、预算和实际次数；密钥、私人对话原文不入库。
- 命令的原始 JSONL 只在确有复盘价值时保存（旧批次的 `.commands.jsonl` 已归档）。
