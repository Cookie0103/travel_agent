# 评测入口与不变量

## 目录

```text
eval/
  cases/       题库数据（jsonl）与冻结清单，见 cases/README.md
  core/        各套评测共用的底座：题目结构与加载（cases、suites）、每题独立的临时库（database）、
               初始状态与事后断言（state）、live 防护（guard）、重复与测量摘要（report）
  grading/     确定性打分与指标：规则评分（graders）、调用证据（metrics）、业务分项（business_metrics）、
               记忆指标（memory_metrics）、声明一致性（claims）、失败归因（diagnostics）、内容评审（content）
  judging/     模型辅助评审与人工校准（v2 时期）：judge、persona、calibration、human_sheet、event_summary
  simulator/   多轮合成用户（v2 时期）：run、metrics、failures
  v1v2/        旧套件入口 run.py：legacy / frozen / v2 / v2-memory
  v3/          现行的脚本化用户多轮评测：cases、tiers、user、run、score、judge、report
```

第二阶段新增的代码各自建子包（规则题、商业期望分、自进化），不放回根目录；位置见[开发计划](../docs/phase2/plans/2026-11-27-judge-evolution.md)。

## 命令

默认离线：`uv run python -m eval.v1v2.run --database`。
冻结40例三轮：`uv run python -m eval.v1v2.run --suite frozen --database --split test --repeat 3`。
真实调用须显式--live；DeepSeek最新授权每日≤15CNY（含旧费/未结预占），无累计次数上限，USD仍0。

V2 套件：`--suite v2`（交互/故障恢复）、`--suite v2-memory`（确认记忆），封装为 `dev.py eval-v2` / `eval-memory`；模拟用户评测 `dev.py eval-simulator`；报告含 pass@1 / pass@k / pass^k。用法与授权见 [V2 评测指南](../docs/handbook/guides/evaluation.md#v2-评测套件模拟用户与-passk入口)和 [操作手册](../archive/phase1/docs/operations/interaction-memory-eval.md#v2评测与恢复)。

v3（脚本化用户、硬/软分级、pass^k与Success@T）：`uv run python scripts/dev.py eval-v3`（离线冒烟）/ `--live`（真实调用），题库 `eval/cases/v3.jsonl`，设计见 [archive/phase1/docs/proposals/eval-redesign](../archive/phase1/docs/proposals/eval-redesign/infra-plan.md)。
v3 注意：
- 时间策略：`patience_s` / `ttfua_s` 默认 null，只记录延迟（TTFUA、每轮耗时、校验/修复轮次），不取消、不进 success；profile 自带的 run 超时仍生效（命中记 `infra_error:timeout`）。题目显式设 `patience_s` 才会超时取消并记 abandoned；设了 `ttfua_s`/`patience_s` 才会推 `within_time`。报告里的 Success@T 仅供参考（“若设上限 T 会怎样”）。
- `--max-cny` 可选，默认不设上限；设了则是软上限，只在 trial 之间检查，最多超出一个 trial。每个 trial 前复核预算授权。成本取 trial 前后账本差，含 LLM 兜底和 rubric 评审调用（同一账本）。
- Rubric 评审：`--live` 默认开启，`--no-judge` 关闭，`--judge-check` 用另一套措辞重评通用项并报告翻转率（成本约翻倍）。每个 trial 一次结构化调用（DeepSeek 温度 0），题目 rubric + 4 个通用项（g-disclose / g-no-reask / g-next-step / g-tone），逐项 yes/no/unknown；证据含完整对话、每轮工具摘要、发出的卡片、DB 摘要。评审失败只记 `judge_error`，不改 success。推 Langfuse：`judge_yes_rate`、`judge_unknown_n`、`judge_<item>`（yes=1/no=0，unknown 不推）。
- 中断后怎么接着跑：被 Ctrl-C/SIGTERM 打断、`--max-cny` 到顶、授权失败，或连续 2 个 trial 以限额类 infra_error（`rate_limited`、`service:429`）结束（停止原因 `quota_suspected:<code>`）时，已完成的 trial 已写入 `trials.jsonl`，报告也会照常生成，结尾打印“接着跑：…”命令。用 `dev.py eval-v3 --resume <run_dir> [原来的参数]` 续跑：跳过已完成（成功或真实失败）的 trial，重跑缺失或带 infra_error 的 trial（旧行保留，报告以最新一行为准）；题库文件内容/所选 case-id/live 模式与原运行不一致会拒绝（退出码 2），确认无误加 `--resume-force`。`--max-cny` 的累计花费在每次续跑时重新计数。退出码：0 正常/到费用上限，1 疑似额度耗尽或授权失败，130 被中断。
- 人工校准：每个 trial 的可读对话写到 `.cache/eval-v3/<run>/transcripts/`（私有）。`python -m eval.v3.judge sheet <run_dir>` 导出两位评审的打分表（不含评审结论）；填完后 `python -m eval.v3.judge agree <run_dir> <sheet.csv>` 输出逐项一致率与 Cohen kappa（忽略 unknown），并列出评审与两位人工都 ≥80%（且每对≥5条）的项。
- 声明一致性事实按“该轮结束时”的服务端状态逐轮计算（累计展示过的酒店卡、当前会话已选酒店、当前用户已生效记忆）；“在预算内”只看到该轮为止展示过的全部卡片，不区分声明具体指哪一张。live 下 L3 快照缺失记为 `infra_error:prompt_snapshot_missing`（`l3_source=missing`），不算记忆失败。

`eval.compare` / `eval.assess` / 分诊、重算分、重发分数入口已于2026-10-20移除（见git历史）。

## 自进化候选

- 第一版用 `dev eval-evolve first --baseline RUN --proposal PROPOSAL.json --output .cache/phase2/evolution-round-1`。提案包含 `skill`、`markdown`、`trigger`、`self_assessment`。获授权的反思可显式用 `--use-codex`，它从反思组读取投影后的对话和 Skill。
- 第二版用 `dev eval-evolve guarded --reflection-run REFLECTION --baseline VALIDATION --edit EDIT.json --output .cache/phase2/evolution-guarded-1`。编辑包含 `skill`、`old`、`new`。新增 Skill 的触发条件、三个触发用例与无法复用现有 Skill 的原因见 `GuardedEdit`。
- 两个命令沿用基线的题目、种子、重复次数和本机运行方式。需要复用已有成对数据时传 `--candidate-run RUN`，命令校验评测清单与实际候选内容。原始数据、候选和审核页留在指定的本机输出目录。提请用户审核的页面见[自进化候选审核](../docs/phase2/evolution/README.md)。

## 评测边界

调用链：load_suite → temporary_database → database_evaluation → prepare/observe/assess → grade → report。
数据库、工具、规则与SDK复用业务入口；每轮身份独立，setup不计成绩。
冻结test不用于调优；原始回答/附件/会话只留私有.cache，公共报告脱敏。
规则失败、运行错误、未执行和unknown分别统计；费用保持原币种。
业务分项复用当前PG校验；partial不当完整约束通过，未观测恢复不算成功，旧记录不补造。
FixtureRuntime仅证明设施，不代表模型效果；规则通过不等于事实正确。

- [运行、对照配置、参数与事实评审详解](../docs/handbook/guides/evaluation.md)。
- [固定温度语气/内容辅助评分与真人校准](judging/README.md)。
- [测试总览](../docs/handbook/testing/README.md)。
- [验收测试矩阵](../docs/handbook/execution/verification.md)。
- [当前进度与恢复点：批次索引](../docs/handbook/recording.md#批次索引)（旧执行计划已归档）。
