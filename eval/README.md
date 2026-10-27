# 评测入口与不变量

默认离线：`uv run python -m eval.run --database`。
冻结40例三轮：`uv run python -m eval.run --suite frozen --database --split test --repeat 3`。
真实调用须显式--live；DeepSeek最新授权每日≤15CNY（含旧费/未结预占），无累计次数上限，USD仍0。

V2 套件：`--suite v2`（交互/故障恢复）、`--suite v2-memory`（确认记忆），封装为 `dev.py eval-v2` / `eval-memory`；模拟用户评测 `dev.py eval-simulator`；报告含 pass@1 / pass@k / pass^k。用法与授权见 [V2 评测指南](../docs/guides/evaluation.md#v2-评测套件模拟用户与-passk入口)和 [操作手册](../docs/operations/interaction-memory-eval.md#v2评测与恢复)。

v3（脚本化用户、硬/软分级、pass^k与Success@T）：`uv run python scripts/dev.py eval-v3`（离线冒烟）/ `--live`（真实调用），题库 `cases/v3.jsonl`，设计见 [docs/proposals/eval-redesign](../docs/proposals/eval-redesign/infra-plan.md)。
v3 注意：
- 时间策略：`patience_s` / `ttfua_s` 默认 null，只记录延迟（TTFUA、每轮耗时、校验/修复轮次），不取消、不进 success；profile 自带的 run 超时仍生效（命中记 `infra_error:timeout`）。题目显式设 `patience_s` 才会超时取消并记 abandoned；设了 `ttfua_s`/`patience_s` 才会推 `within_time`。报告里的 Success@T 仅供参考（“若设上限 T 会怎样”）。
- `--max-cny` 可选，默认不设上限；设了则是软上限，只在 trial 之间检查，最多超出一个 trial。每个 trial 前复核预算授权。成本取 trial 前后账本差，含 LLM 兜底和 rubric 评审调用（同一账本）。
- Rubric 评审：`--live` 默认开启，`--no-judge` 关闭，`--judge-check` 用另一套措辞重评通用项并报告翻转率（成本约翻倍）。每个 trial 一次结构化调用（DeepSeek 温度 0），题目 rubric + 4 个通用项（g-disclose / g-no-reask / g-next-step / g-tone），逐项 yes/no/unknown；证据含完整对话、每轮工具摘要、发出的卡片、DB 摘要。评审失败只记 `judge_error`，不改 success。推 Langfuse：`judge_yes_rate`、`judge_unknown_n`、`judge_<item>`（yes=1/no=0，unknown 不推）。
- 中断后怎么接着跑：被 Ctrl-C/SIGTERM 打断、`--max-cny` 到顶、授权失败，或连续 2 个 trial 以限额类 infra_error（`rate_limited`、`service:429`）结束（停止原因 `quota_suspected:<code>`）时，已完成的 trial 已写入 `trials.jsonl`，报告也会照常生成，结尾打印“接着跑：…”命令。用 `dev.py eval-v3 --resume <run_dir> [原来的参数]` 续跑：跳过已完成（成功或真实失败）的 trial，重跑缺失或带 infra_error 的 trial（旧行保留，报告以最新一行为准）；题库文件内容/所选 case-id/live 模式与原运行不一致会拒绝（退出码 2），确认无误加 `--resume-force`。`--max-cny` 的累计花费在每次续跑时重新计数。退出码：0 正常/到费用上限，1 疑似额度耗尽或授权失败，130 被中断。
- 人工校准：每个 trial 的可读对话写到 `.cache/eval-v3/<run>/transcripts/`（私有）。`python -m eval.v3_judge sheet <run_dir>` 导出两位评审的打分表（不含评审结论）；填完后 `python -m eval.v3_judge agree <run_dir> <sheet.csv>` 输出逐项一致率与 Cohen kappa（忽略 unknown），并列出评审与两位人工都 ≥80%（且每对≥5条）的项。
- 声明一致性事实按“该轮结束时”的服务端状态逐轮计算（累计展示过的酒店卡、当前会话已选酒店、当前用户已生效记忆）；“在预算内”只看到该轮为止展示过的全部卡片，不区分声明具体指哪一张。live 下 L3 快照缺失记为 `infra_error:prompt_snapshot_missing`（`l3_source=missing`），不算记忆失败。

`eval.compare` / `eval.assess` / 分诊、重算分、重发分数入口已于2026-10-20移除（见git历史）。

调用链：load_suite → temporary_database → database_evaluation → prepare/observe/assess → grade → report。
数据库、工具、规则与SDK复用业务入口；每轮身份独立，setup不计成绩。
冻结test不用于调优；原始回答/附件/会话只留私有.cache，公共报告脱敏。
规则失败、运行错误、未执行和unknown分别统计；费用保持原币种。
业务分项复用当前PG校验；partial不当完整约束通过，未观测恢复不算成功，旧记录不补造。
FixtureRuntime仅证明设施，不代表模型效果；规则通过不等于事实正确。

- [运行、对照配置、参数与事实评审详解](../docs/guides/evaluation.md)。
- [固定温度语气/内容辅助评分与真人校准](calibration/README.md)。
- [测试总览](../docs/testing/README.md)。
- [验收测试矩阵](../docs/execution/verification.md)。
- [当前进度与恢复点：批次索引](../docs/plans/README.md#批次索引)（旧执行计划已归档）。
