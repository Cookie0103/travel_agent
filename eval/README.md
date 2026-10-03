# 评测与可恢复报告

默认历史30例：`uv run python -m eval.run --database`；不调用模型。
冻结集：`uv run python -m eval.run --suite frozen --database --split test --repeat 3`。
授权真实调用需额外 `--live` 与既有供应商/请求/原币种/每日额度；完整40×3最低120次请求超过本轮授权，不会自动放开。
历史21+9文件和期望不改。冻结版本、hash、20dev/40test、历史来源及正常对照由suites校验；未冻结/内容漂移拒绝运行。test不用于模型调优。

调用链：load_suite → temporary_database → database_evaluation → prepare/observe/checks → grade → report。
DB模式只创建本次随机本地 `travel_agent_eval_<uuid>`，迁移/导入既定快照；正常退出仅清理该库，保留父库及输出。不读取已有用户数据。硬断电可能留下本次孤立库，恢复不自动删除其他库。
InitialState使用现有服务构造正式行程/锁、报价过期/条件失效、held/unknown、偏好/墓碑与历史。setup与实际运行分开run_id，setup事件不计成绩；业务历史种子不等于原生SDK长会话。
供应商故障只注入本次本机HTTP `/holds`；unknown订单setup在用户确认后丢响应。模型没有确认/对账工具，必须保留unknown并说明用户/API查询，不能据此声称模型对账成功。
事后比较正式版本、完整模拟订单集合、偏好/条件；本轮酒店展示、暂留和故障绑定实际事件/报价/HTTP请求，历史结果不冒充当前成果。
局部改程专门核对第二天下午稳定ID、start/end延后一小时及其他项/酒店保留；泛化单项修改与精确任务分开评分。

固定编排加 `--workflow search|hotel|itinerary`，默认自主工具选择，参数仍由同一SDK模型决定。请求上限 `--max-attempts 1..12`（默认4）不是SDK轮数。
每轮每例独立身份/session/run；预先指定重复不是失败自动重试。运行错误/禁止副作用后停止余下所有轮次，规则失败继续；未执行/错误分别记录，不进入规则分母。
`.cache/eval/<新运行ID>/` 的manifest绑定HEAD、dirty、实际源码/schema/快照/用例/价格与冻结依据；联网前attempts及逐结果flush/fsync。断电恢复先核对这些文件与持久费用账本，不能仅凭缺结果推断未花费。
报告分别记录重复n/波动、工具数/HTTP、token、时延P50/P95及CNY/USD；未知测量为null，不填零、不换汇。未经语义/人工校准，规则分不代表事实准确率。
离线DB仍用FixtureRuntime搜索/固定演示，只证明设施/真实服务协作，不能代表自主模型规划。规格期待从不送入模型，完整回答/SDK会话留私有缓存。
规则失败仍输出报告并退出0；执行/规格/输出异常退出1，不能仅看退出码当业务通过。

语气评审：`python -m eval.judge <私有JSONL>`默认只准备；显式--live复用同SDK/费用守卫、固定模型/temperature0/零工具。完整回答与评分私有，解析错误单列judge_error；运行异常停止余下样本，真人分不生成。校准/调用说明见[calibration](calibration/README.md)。
## 工具参数与首次进度指标

逐调用报告保留correct/incorrect/unknown；成功返回不能证明参数符合用户目标。缺少整个指标的旧报告全量计数为null，已测小计单列。首次进度自动只计实际工具事件和展示卡片，排除started/心跳及未分类文本ACK；纯文本回答未人工分类时该测量为unknown。

独立参数评审复用同一指标函数，可运行 `uv run python -m eval.assess --events <私有events.jsonl> --actual <actual.json> --expected <expected.json> --case-id <原case_id>`。actual/expected是ArgumentFact JSON数组，包含context（user_id/session_id/run_id）、tool_call_id、arguments，事件为RuntimeEvent JSONL。实际参数从对应私有轨迹核对，答案依据用户输入/已知业务状态独立填写；不能抄实际参数、用模型自述或为失败改答案。允许多条合法路径，每条已审查调用给自己的完整答案；没有证据的调用继续unknown。附件留.cache，不加入提交/公共Trace。该命令只输出脱敏计数，不改既有规则结果或冻结集；自动事件报告本身没有完整参数语义答案。

## 同一SDK对照

实际模型评测可加 `--variant full|no_tools|baseline_b2|no_skills|no_preferences|no_repairs|no_compaction`（需--database --live与既有授权）。full为B3；no_tools为B0，不给数据库事实或工具；固定--workflow为B1；baseline_b2为B2，保留工具/Skill/校验，同时关闭自动压缩和当前持久偏好注入。这是两项组合基线，不是单因素对照。其余分别只关闭按需Skill、当前持久偏好注入、校验后的修复轮次或自动压缩。非full单轮/fresh SDK，不与--workflow或语气评审混用；每例仍独立业务身份和原结果评分。反思关闭不跳过首次/最终校验，冲突草稿可展示但用户确认必须拒绝。manifest绑定实际variant/组别/schema/Skills。FixtureRuntime不模拟这些效果，非full离线CLI拒绝；实际SDK+本机脚本/PG测试只证明配置机制。

关闭自动压缩使用SDK公共options.env与官方DISABLE_AUTO_COMPACT=1，限已验证SDK0.2.163/CLI2.1.114；未知版本在初始化/模型请求前拒绝，意外压缩事件中断而非计成功。实际原生SDK在相同人工usage/阈值下默认发生压缩、no_compaction/B2不压缩；这不代表真实模型摘要质量或效果已测。带工具的get_context_usage会触发辅助请求，因此不逐轮查询、不放宽费用守卫、不改写transcript。长期偏好关闭只隔离保存的偏好值，保留用户当前条件与合法近期对话/删除墓碑，不声称删除所有历史线索。详见[ADR012](../docs/adr/012-evaluation-variants.md)。
