# v3 测评基础设施：实现方案（2026-10-19）

本文来源：architect agent 只读设计，Codex 不可用时的后备方案。实现状态见 [README.md](README.md) 的版本表。

标记说明：R = 读代码得出的结论；A = 假设，未核实。实现时以代码为准。

## 0. 影响设计的代码事实

1. **真实 API 和故障注入不能同时开**：`real_data` 与 `evaluation_fault` 同时设置时，`GuardedRuntime` 会直接报错（`application.py:47-50`、`live.py:81-89`、`worker.py:111-116`，R）。因此：
   - `fault: null` 的题使用 `real_data=True`，调用真实 DeepSeek、乐天、Google、Open-Meteo。
   - 故障题使用合成数据。这些题的断言只能写成性质判断，不能断言具体酒店名或价格。
2. **system prompt 在 worker 子进程里拼装**（`worker.py:147`），工作目录为 `.cache/sessions/<uid>/<sid>/`。worker 的环境变量是白名单，所以开关要放进 payload 传递。另外 import-linter 禁止 `backend` 导入 `eval`。
3. **profile**：`TRAVEL_PROFILE` 默认是 DEFAULT（每天 15 CNY、16 次工具调用、240 s）；HUMAN 为 900 s，且不限工具次数和费用。线上 Railway 实际用哪个还不知道（A）。runner 默认 `--profile human`，并把 profile 写进 manifest 和 trace 标签。
4. **API 配额**：配额计数存在临时数据库里，每次 run 新建一个临时库就会重置。用 `--max-cny` 做硬止损。
5. **trace**：一个 trial 对应一个 Langfuse trace，里面包含多个 `travel.run`。内层 span 已经带有伪名化的 session_id 和 user_id。`evaluation.trial` 只接受 1..3（`tracing.py:483-497`），所以 `--repeat` 最多是 3。
6. **草稿校验结果会落库**：`PlanDraft.validation` 记录每项检查的 `subject / status / code / message`。
7. **卡片选项**：记忆卡的选项为 `remember | trip | reject`；询问卡是 `ChoiceForm(purpose="trip_ask")`，`groups[].key` 里包含 `pace`；酒店卡带 `evidence_id`、`total`、`budget_excess`。
8. **命令**：
   - 测试：`uv run python scripts/dev.py test`，即 `pytest -m "not live" -q`。
   - 门禁：`uv run python scripts/dev.py check`，依次执行 ruff、format、`mypy --strict`、lint-imports、check_docs。
   - 集成测试需要先执行 `uv run python scripts/dev.py db-up`。

## 1. 模拟用户：按脚本说话，LLM 只做兜底
用户的每一步都按脚本执行。只有当 agent 问到脚本没覆盖的问题，并且该题设置了 `fallback.policy="facts"` 时，才调用 LLM，从 `user_facts` 里取答案作答，最多追加 `max_extra_turns` 轮。

这样做的理由：用 LLM 改写用户话语会引入方差，干扰 pass^3 的统计；同时还会把"过度配合"的问题带回来（见 README §2.2 引用的 Sim2Real Gap 论文）。

## 2. v3 题目格式
以 `eval/v3_cases.py` 里的 pydantic 模型为准。字段说明对外发布在 [question-generation-spec.md](question-generation-spec.md)。

## 3. 文件改动
新增：
- `eval/v3_cases.py`：题目模型和加载时校验。
- `eval/v3_user.py`：按脚本逐步执行，包括卡片、酒店选择、新会话、换用户、确认行程，以及耐心超时取消和 LLM 兜底。
- `eval/v3_run.py`：命令行入口、trial 循环、根 span、推送分数、输出 manifest。
- `eval/v3_score.py`：时延、校验和修复轮次、工具检查、硬/软约束分级（`VALIDATOR_TIER`）、记忆 L1–L4、声明一致性、success 判定。
- `eval/v3_report.py`：pass^1/pass^3、Success@T、失败原因表、`scatter.csv`、`report.md`。
- `eval/cases/v3.jsonl`：示例题。
- 对应的测试文件。

小改：
- `worker.py`：增加 prompt 快照钩子。
- `live.py`、`application.py`：透传开关；开关由三道门共同控制，见下。
- `evaluation_faults.py`：抽出 `is_eval_database`。
- `tracing.py`：metadata 和标签里加入 `category`。
- `claims.py`：增加声明对账，"在预算内"、"已选酒店"、"已记住"，以及 2026-10-20 补的"已订好"（`claims-v7`，按该用户 status=booked 的真实预订对账）；不传 facts 时输出与旧版完全一致。
- `scripts/dev.py`：增加 `eval-v3` 子命令。

prompt 快照只写入 `.cache/sessions/<uid>/<sid>/system-prompt-<run_id>.txt`，不进 trace、报告或 stdout。要写入必须同时满足三个条件：payload 标志为 true、环境变量 `TRAVEL_EVAL_PROMPT_SNAPSHOT=1`、DSN 是评测临时库。

## 4. Langfuse 埋点
所有分数都在 `finish_trial` 里通过 `push_scores(batch=True)` 推送，只推数值。不适用的指标不推，不要当作 0 推上去。

| 名称 | 含义 |
|---|---|
| tags：`v3`、category、`deepseek`、profile | 用于筛选 |
| metadata：`suite`、`eval_case_id`、`eval_trial`、`category`、`git_sha`、`run_name`、`trial_group`、`fault` | 用于回溯 |
| `success`、`hard_pass`、`false_claim`、`within_time`、`tool_ok`、`memory_ok`、`abandoned` | 0/1 |
| `soft_score` | 0..1 |
| `ttfua_s`、`turn_latency_max_s`、`turn_latency_total_s` | 秒 |
| `validation_rounds`、`repair_rounds`、`validation_time_s` | 拖慢响应的定位依据 |
| `required_tools_ok`、`forbidden_tools_ok`、`hallucinated_tool`、`blocked_run` | 0/1 |
| `mem_l1_exact`、`mem_l2_persisted`、`mem_l3_in_prompt`、`mem_l4_behavior` | 只在该题声明了对应层时推送 |
| `claim_budget`、`claim_hotel_selected`、`claim_remembered` | 1 表示违规；只在回复中出现了该类声明时推送 |
| `tool_calls`、`cost_cny` | 成本 |

## 5. 指标定义
- **TTFUA**：从 run 创建到第一个 `presentation` 事件的时间；如果没有 presentation，则取到 run 结束。按轮计算，trial 取各轮最大值。
- **每轮耗时**：`finished_at − created_at`。
- **validation_rounds**：`validate_itinerary` 的调用次数。`repair_rounds = max(0, n−1)`。
- **工具检查**：
  - required ⊆ 实际调用过的工具；
  - forbidden ∩ 实际调用过的工具 = ∅；
  - 出现不在注册表里的工具名，或 guard 报告未知工具，记为 hallucinated；
  - 任一轮的结束 code 为 `blocked`，记为 blocked run。
- **abandoned**：任一轮超过 `patience_s`，取消该 run，并记为放弃。
- **success** = `hard_pass ∧ ¬false_claim ∧ tool_ok ∧ memory_ok ∧ ¬abandoned`（另需无 step_unavailable、无 infra_error；时延只记录，不参与）。judge 打分**不参与** success。
- **声明判定为 unknown**：只计数，不判失败，在报告里单独显示 unknown 率。
- **失败原因**：每个失败的 trial 只取一个原因，按以下优先级取第一个命中的：`infra_error` > `abandoned` > `blocked_or_hallucinated_tool` > `false_claim:<kind>` > `hard:<id>` > `step_unavailable:<n>` > `tool:<name>` > `memory:L<n>` > `over_time`。
- **记忆 L1–L4 的数据来源**：
  - L1 复用 `memory_scores`。**不要调用 `inspect_memory`**，它会删除偏好。
  - L2 查 `user_memory_facts` 表。
  - L3 看新会话第一个 run 的 prompt 快照文件。
  - L4 走普通检查项。

## 6. 风险
- 线上 profile 不明，可能导致测出来的结果和线上不一致。
- 真实 API 的结果不确定，pass^3 会有噪声。
- run 被放弃时是中途取消的，数据库状态不完整属于正常现象。
- 题目日期必须晚于运行日；天气只能预报 16 天以内，超出范围时结果为 unknown，不算失败。

## 6.1 实现后补充的限制（2026-10-20 QA 后）
- 时延只记录、不进 success（负责人决定）；`patience_s`/`ttfua_s` 默认 null。`--max-cny` 可选，软上限，只在 trial 之间检查；每个 trial 前复核授权。
- rubric 评审（`eval/v3_judge.py`）已实现，不参与 success；见 eval/README.md。
- 声明一致性的服务端事实逐轮计算（该轮结束时的状态）；“在预算内”按到该轮为止展示过的所有酒店卡判断，不区分声明指哪一张卡，粗检可能漏报或误报。
- 声明检测器只认断言句：搜不到、提供选项、提问（可以选择/可选/要不要/是否/吗/？）会被跳过。
- live 下新会话首轮的 prompt 快照缺失按 `infra_error`（`prompt_snapshot_missing`）处理，不算 `memory:L3`。
- 运行可中断后用 `--resume <run_dir>` 续跑（跳过已完成 trial，重跑 infra_error trial，报告取每个 (case, trial) 的最新一行）；连续 2 个限额类 infra_error 会停下并打印续跑命令。
- `fallback.policy=facts` 的 LLM 调用走同一预算账本，包含在 trial 成本里。

## 7. 暂缓
- judge 和人工评分表（`--judge`）；
- "软约束没满足、也没告诉用户"的检测器；
- Langfuse datasets；
- 真人与模拟用户的拟真度对比；
- 旧套件归档（README §7）。
