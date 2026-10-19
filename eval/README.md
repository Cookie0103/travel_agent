# 评测入口与不变量

默认离线：`uv run python -m eval.run --database`。
冻结40例三轮：`uv run python -m eval.run --suite frozen --database --split test --repeat 3`。
真实调用须显式--live；DeepSeek最新授权每日≤15CNY（含旧费/未结预占），无累计次数上限，USD仍0。

V2 套件：`--suite v2`（交互/故障恢复）、`--suite v2-memory`（确认记忆），封装为 `dev.py eval-v2` / `eval-memory`；模拟用户评测 `dev.py eval-simulator`；报告含 pass@1 / pass@k / pass^k。用法与授权见 [V2 评测指南](../docs/guides/evaluation.md#v2-评测套件模拟用户与-passk入口)和 [操作手册](../docs/operations/interaction-memory-eval.md#v2评测与恢复)。

离线比较：`uv run python -m eval.compare --runs <run_a> <run_b>`；完整配对/源码/数据/schema/真实身份校核，规则差不当事实质量。

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
