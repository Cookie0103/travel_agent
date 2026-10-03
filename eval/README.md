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
