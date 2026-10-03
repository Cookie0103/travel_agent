# 评测入口与不变量

默认离线：`uv run python -m eval.run --database`。
冻结40例三轮：`uv run python -m eval.run --suite frozen --database --split test --repeat 3`。
真实调用须显式--live；DeepSeek最新授权每日≤15CNY（含旧费/未结预占），无累计次数上限，USD仍0。

离线比较：`uv run python -m eval.compare --runs <run_a> <run_b>`；完整配对/源码/数据/schema/真实身份校核，规则差不当事实质量。

调用链：load_suite → temporary_database → database_evaluation → prepare/observe/checks → grade → report。
数据库、工具、规则与SDK复用业务入口；每轮身份独立，setup不计成绩。
冻结test不用于调优；原始回答/附件/会话只留私有.cache，公共报告脱敏。
规则失败、运行错误、未执行和unknown分别统计；费用保持原币种。
FixtureRuntime仅证明设施，不代表模型效果；规则通过不等于事实正确。

- [运行、对照配置、参数与事实评审详解](../docs/evaluation.md)。
- [固定温度语气/内容辅助评分与真人校准](calibration/README.md)。
- [验收测试矩阵](../docs/execution/verification.md)。
- [当前进度与恢复点](../docs/execution/travel-agent.md)。
