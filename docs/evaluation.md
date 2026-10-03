# 评测与可恢复报告

默认历史30例：`uv run python -m eval.run --database`；不调用模型。
冻结集：`uv run python -m eval.run --suite frozen --database --split test --repeat 3`。
授权真实调用需额外 `--live` 与明确供应商/原币种/每日额度；最新DeepSeek许可每日15CNY、无累计金额/次数上限，旧账/未结占用继续计入，USD仍0。完整40×3最低120次HTTP且通常更多，每日额度不足停止，不承诺整批一定完成。
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

语气/内容评审：`python -m eval.judge <私有JSONL>`默认只准备；显式--live复用同SDK/费用守卫、固定模型/temperature0/零工具。完整回答与评分私有，解析错误单列judge_error；运行异常停止余下样本，真人分不生成。校准/调用说明见[calibration](../eval/calibration/README.md)。
## 工具参数与首次进度指标

逐调用报告保留correct/incorrect/unknown；成功返回不能证明参数符合用户目标。缺少整个指标的旧报告全量计数为null，已测小计单列。首次进度自动只计实际工具事件和展示卡片，排除started/心跳及未分类文本ACK；纯文本回答未人工分类时该测量为unknown。

独立参数评审复用同一指标函数，可运行 `uv run python -m eval.assess --events <私有events.jsonl> --actual <actual.json> --expected <expected.json> --case-id <原case_id>`。actual/expected是ArgumentFact JSON数组，包含context（user_id/session_id/run_id）、tool_call_id、arguments，事件为RuntimeEvent JSONL。实际参数从对应私有轨迹核对，答案依据用户输入/已知业务状态独立填写；不能抄实际参数、用模型自述或为失败改答案。允许多条合法路径，每条已审查调用给自己的完整答案；没有证据的调用继续unknown。附件留.cache，不加入提交/公共Trace。该命令只输出脱敏计数，不改既有规则结果或冻结集；自动事件报告本身没有完整参数语义答案。

## 同一SDK对照

实际模型评测可加 `--variant full|no_tools|baseline_b2|no_skills|no_preferences|no_repairs|no_compaction`（需--database --live与既有授权）。full为B3；no_tools为B0，不给数据库事实或工具；固定--workflow为B1；baseline_b2为B2，保留工具/Skill/校验，同时关闭自动压缩和当前持久偏好注入。这是两项组合基线，不是单因素对照。其余分别只关闭按需Skill、当前持久偏好注入、校验后的修复轮次或自动压缩。非full单轮/fresh SDK，不与--workflow或辅助评审混用；每例仍独立业务身份和原结果评分。反思关闭不跳过首次/最终校验，冲突草稿可展示但用户确认必须拒绝。manifest绑定实际variant/组别/schema/Skills。FixtureRuntime不模拟这些效果，非full离线CLI拒绝；实际SDK+本机脚本/PG测试只证明配置机制。

关闭自动压缩使用SDK公共options.env与官方DISABLE_AUTO_COMPACT=1，限已验证SDK0.2.163/CLI2.1.114；未知版本在初始化/模型请求前拒绝，意外压缩事件中断而非计成功。实际原生SDK在相同人工usage/阈值下默认发生压缩、no_compaction/B2不压缩；这不代表真实模型摘要质量或效果已测。带工具的get_context_usage会触发辅助请求，因此不逐轮查询、不放宽费用守卫、不改写transcript。长期偏好关闭只隔离保存的偏好值，保留用户当前条件与合法近期对话/删除墓碑，不声称删除所有历史线索。详见[ADR012](adr/012-evaluation-variants.md)。

## 事实与内容的私有评审

数据库评测在本次临时PG销毁前，将原回答、context、当前条件/时间、本人Evidence（含invalidated）写入results.content_record，不筛掉旧引用来美化成绩。正式入口：`uv run python -m eval.content --results <原results.jsonl> --case-id <原case_id> --repeat 1 --review <独立review.json>`；核对原text、唯一attempt/context、manifest选定Case与suite版本，原文/hash不匹配或缺捕获拒绝。旧运行没有捕获时不能补造；`--answer <AnswerRecord.json>`仅独立快照，输出standalone_snapshot而非原模型实验。所有附件留.cache，入口0模型请求、不改原结果/冻结集。

ContentReview按原case/context/answer_sha256绑定；reviewer记录实际独立评审人，不能抄模型自述。claims每项包含claim_id、原文start/end/excerpt、entity_id、field_path、规范JSON value、certainty（asserted/unknown/estimate）与evidence_id。field_path是既有对象的相对字段：目录name/opening_hours、酒店total或stay.start_date、路段minutes/fare；复用Place/Article/HotelOffer.card/RouteEstimate，不用整对象自证单项。金额遵循原card的Decimal字符串，不另写税费算法。路线费用/分钟和边界框坐标须明确estimate；对象内null是unknown，缺字段/坏领域对象/外国或缺失附件保持unknown，错值/失效/缺来源不能通过。

required_facts是依据原需求/既定状态独立列出的必需事实清单（entity_id/field_path/value/certainty），不从被测回答反推。claims_complete与requirements_complete只有经核验才填true；漏事实降低覆盖率，不完整或仍有未解决Evidence则总比率null；零断言分母不是100%。unknown陈述不充当确定事实，明确估算的正确陈述仍计入事实分母。输出仅hash/计数/固定理由标签，无陈述/来源/评审人；绑定不证明标注独立性，Evidence一致性也不代表现实数据独立核验。

human_quality只接收真人提供的relevance/explanation/tradeoffs各0–5、reason与rater；未提供不生成分数。0=该项缺失/明显错误，3=基本可用但有关键遗漏，5=完整满足：相关性对应当前需求与硬条件，解释说明来源/unknown及选择原因，取舍说明冲突/可选调整且不偷偷放宽条件。内容辅助评审使用 `uv run python -m eval.judge <私有Sample.jsonl> --kind content`，默认只准备；显式--live仍受原累计/每日额度约束，同一固定温度零工具SDK入口，只将三维rubric与严格输出模型换为QualityScore。模型分和human_quality分别保存，不能用模型分代替真人或事实证据。已有评分补入实际真人human_quality后，运行 `uv run python -m eval.persona <samples.jsonl> --kind content` 离线分别计算三维校准，不再次调用模型。实际内容单样本已验证入口，完整模型统计、人工抽查和校准仍待验证，不能将本机SDK工程测试当整体模型质量验收。

评测CLI复用scripts.dev编码初始化，Windows无需手动设置PYTHONUTF8；输出和私有文件保持UTF-8。初始化不读取密钥、不修改评分输入，不产生请求。

## 本轮受控测量约定（2026-10-03）

首个真实完整批次在HEAD9eb653a、干净工作区启动：travel-eval-v1原40test×3、full/B3、每例最多12HTTP；被测源码/数据/prompt/schema保持不变。期间保存执行文档及push不会改变这些文件，原manifest的HEAD与启动状态保留，结束时逐文件核对。该批次是测量，不能补造优化前缺失的成功率/费用验收阈值。

后续B0对照在运行前明确：仍用同40test、同顺序、3个独立重复、原期望与初始状态、同模型/SDK/CLI/数据/源码和12HTTP上限，唯一运行配置变为no_tools。先完成当前批次并核对日余额，再决定是否启动；日硬限不足停止并公开not_run，不自动回放失败。B0不注入数据库事实/工具，其缺工具导致的结构规则失败是预期对照边界，不能据此宣称事实准确率提升。对照不用于调提示或挑选有利案例。

B2/B1及单因素后续测量各自记录实际样本/重复/适用范围，不能把未运行的组别填为成功或将B2两开关组合当单因素。比较入口只读取原manifest/results，核对完整配对/执行版本并重用report统计，缺语义或真人答案继续unknown。新增eval比较源码会改变未来manifest哈希集合，因此本轮同版本受控调用先完成，随后实现比较；不临时忽略源码差异来接纳不同实验。
