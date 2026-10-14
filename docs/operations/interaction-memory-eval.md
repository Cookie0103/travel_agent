# 交互、记忆与评测批次操作

状态只维护在[当前批次](../plans/2026-10-13-interaction-memory-eval.md)。本文件记录可重跑命令及导出步骤，不包含凭据或私人对话。

## 本地验证

```text
uv run python scripts/dev.py db-up
uv run python scripts/dev.py format
uv run python scripts/dev.py check
uv run python scripts/dev.py test
uv run python scripts/dev.py test --path tests/integration/test_answer_history.py
uv run python scripts/dev.py web-generate
uv run python scripts/dev.py web-check
uv run python scripts/dev.py api --live
```

本机Turbopack的CSS子进程在绑定内部端口时出现 `Operation not permitted`，停止本任务前端服务后仍复现；这不是业务类型或单元测试失败。可执行 `uv run python scripts/dev.py web-check --webpack`，保留全部类型、lint、Node测试和生产构建检查，仅显式选择Next自带Webpack。默认CI/部署构建不变，不新增依赖。[官方CLI选项](https://nextjs.org/docs/app/api-reference/cli/next#next-build-options)。

当前本机默认 CLI 2.1.296，压缩关闭实验的已核验名单止于 2.1.295。测试前在当前进程设置 `TRAVEL_CLAUDE_CLI` 指向本机已有的 2.1.295 文件，不改 `.env`、全局 CLI 或未知版本门禁。其他平台选择当地已有的已核验版本，不硬编码到产品代码。

模型日预算 60 CNY、累计 150 CNY 从 2026-10-13 UTC 日期起生效，HUMAN 同样受限。旧日期和旧账本格式保留，未结算预占按全额计费，不清零。供应商配额独立记账。

## Railway 对话导出到本地（方式 A）

新代码部署后，最终回答随原 `task_runs` 事务存入配置的 PostgreSQL；本批不改 Railway 部署。旧占位回答无法恢复原文。导出只读，不触发模型、供应商或订单。

1. 从 Railway 的 Postgres 服务变量取得 `DATABASE_PUBLIC_URL`，放入本机临时环境，不写入仓库。
2. 选择新的本地 JSON 路径。`--user`、`--session` 同时给出时取交集；不筛选则导出全部会话，适用于拥有数据库凭据的操作者。
3. 执行以下命令。macOS/zsh 示例中的变量，在 PowerShell 中用 `$env:DATABASE_PUBLIC_URL`；脚本默认也可读取 `DATABASE_URL`。

```text
uv run python scripts/export_history.py --database-url "$DATABASE_PUBLIC_URL" --session <会话UUID> --out <本地新文件.json>
```

输出含会话、各轮 prompt/answer、状态、时间戳和 presentation 引用，不含令牌、SDK 文件或供应商原始响应。文件含私有对话，保留在本地；脚本拒绝覆盖已有文件。

## 备选：整库备份与直接查询

生产 PG18 的备份需本机 `pg_dump` 18 或更新版本。整库备份包含更多私有业务数据，不提交到 Git。

```text
pg_dump "$DATABASE_PUBLIC_URL" -Fc -f travel.dump
railway connect Postgres
```

进入 psql 后可先 `BEGIN READ ONLY`，按用户/会话查 `task_runs`，最后 `ROLLBACK`。这些步骤供用户需要导出时执行；开发期间不连接生产数据库。

## 验证日志

本机原始日志保留在 ignored 的 `.cache/batch-2026-10-13/`，正式结果写在当前批次计划。完整测试输出与私有运行报告不提交到公共仓库。

## 乐天价格排序口径验证

授权后执行 `uv run python scripts/dev.py probe-hotel-sort --live`；不带 `--live` 返回2且不发请求。包括失败重试总共最多2次HTTP，保留每日计数与既有节流，不重设生产额度。探针只保存脱敏数值与计数到[证据](../evidence/t4-rakuten-sort-2026-10-13.json)，不会保存原始响应或酒店标识。

2026-10-13 UTC实测：京都11/14–15、2成人1间、禁烟独立房。standard与+roomCharge各1次成功。上游recordCount均392；前者返回30家，标准化最低每间31600；后者返回23个不同酒店/30房型，最低16124。排序样本每间标准化金额升序，原rakutenCharge因混合chargeFlag不是升序。不要直接按原金额筛预算。

[官方空室API](https://webservice.rakuten.co.jp/documentation/vacant-hotel-search)说明：sort=+roomCharge价格升序，chargeFlag=0每人、1每间；dailyCharge只对应一晚。接口返回页有限且有房型/套餐重复；recordCount按酒店的解释仍标ASSUMED，过滤数按返回房型计数。一次样本不证明所有日期或房型覆盖，也不能把首晚价乘晚数当已核实全价。

测试使用既有已核验CLI；PG集成与纯规则专项分组运行，避免跨目录文件交错时pytest未加载子目录conftest。完整suite保持原入口。不要在SDK测试运行中修改其子进程将导入的源码，最终全量须在稳定代码上重跑。

## Langfuse同轮联验

本地API通过项目入口`api --live --trace-cloud`启动后，执行`uv run python scripts/dev.py smoke-langfuse-linkage --live --trace-cloud`。任一授权标志缺失都会在创建用户或联网前拒绝。凭据从本地配置读取，不输出、不提交。新合成用户只要求节奏卡；失败不自动重新付费。

脚本从PG读取run.trace_id；按该ID及有界时间读取v2 observations，选择core/basic/trace_context/metadata，不读io。比较全span的session HMAC、tags、PG工具事件数量、实际模型HTTP数量；用固定幂等ID推送数值分数并从v3 scores读回。[官方API与字段](https://langfuse.com/docs/api-and-data-platform/features/public-api)、[v4上下文要求](https://langfuse.com/integrations/native/opentelemetry/migration-to-v4)。证据保存在[JSON](../evidence/t6-langfuse-linkage-2026-10-13.json)，不包含私有会话正文或凭据。

## V2评测与恢复

```text
uv run python scripts/dev.py eval-v2
uv run python scripts/dev.py eval-v2 --live --trace-cloud --repeat 3
uv run python scripts/dev.py eval-memory
uv run python scripts/dev.py eval-memory --live --trace-cloud
uv run python scripts/dev.py eval-simulator
uv run python scripts/dev.py eval-simulator --live --trace-cloud --repeat 3
uv run python scripts/dev.py eval-triage <结果目录/results.jsonl>
uv run python scripts/dev.py eval-triage <结果目录/results.jsonl> --live
uv run python scripts/dev.py eval-calibration <实际结果1.jsonl> <实际结果2.jsonl> --live
```

默认只准备/离线；显式live才用DeepSeek。评测用随机本地`travel_agent_eval_<UUID>`数据库，旅行外部数据全用MockTransport，未知路径不回退真实网络；运行完清理仅本次随机数据库。生产用户、订单、Railway都不参与。模拟用户也走同SDK固定温度/零工具，隐藏目标表外回答不知道，最多8用户动作；每trial含用户模拟调用的真实成本。完成不代表成功，规则与保存后独立约束另算。

结果与原始合成回答保存在ignored `.cache/eval/`、`.cache/simulator/`，manifest绑定实际源码hash和预声明case。模型调用期间不改运行源码；改变评分探针时保留原结果，并对同批所有原始事件统一重算，不能只替换失败样本。分诊每条失败最多一次、输出用x模式防覆盖，标签是未人工核实参考，未知保持unknown。

本批CLI固定2.1.295；在命令前设置对应`TRAVEL_CLAUDE_CLI`。账本全程保留；中断后先读results/attempts/账本核对已发生调用，不直接从头重复收费。运行中的SDK评测和全量测试均须保持源码稳定。本次部分无工具评审与离线全量同时运行，各自使用不同会话/测试库/账本；需要改运行源码时先等二者结束。E6服务器探针检查的是记忆事实/快照/旧回顾，用户要求保留的原始历史不算遗忘残留。

## 30条盲标与AI预标注

`eval-calibration`只从实际非空回答选15条规则通过与15条规则失败，先保证任务多样性，再取后续trial，固定种子洗牌；这不是质量好坏均衡，也不是总体成功率抽样。多轮样本附实际用户动作，评价末回复时使用这些上下文。模型格式无效会保留unknown，不伪造参考分。

CSV的`human_pass`、`human_rater`与`notes`由用户填写：`human_pass`填0或1，判断回复的相关性、解释与取舍是否都达到「基本可用」，诚实说明资料不足可以通过；填写自己的评审者名称，疑问写notes。先做盲标，再看hidden-reference或agent-provisional；后者是AI预标注，不是真人真值。本批交付表、隐藏模型参考、AI预标注分别保存在本地ignored `.cache/batch-2026-10-13/calibration/`；原始运行结果保留在 `.cache/calibration/`，不会上传正文到Langfuse。

填写后执行 `uv run python -m eval.calibrate_v2 <human-labels.csv> <hidden-reference.json>`，脚本只对实际真人标注且有有效模型参考的行计算一致率、κ、混淆矩阵；不足30对标为pending。不代填人名、不用AI预标注冒充人工。两对A/B交换只是很小的偏差探针，不证明评审器无位置偏差。


## 重发已有评测的数值分数

```text
uv run python scripts/dev.py eval-publish-v2 <结果1.jsonl> <结果2.jsonl> --triage <model-triage.jsonl>
uv run python scripts/dev.py eval-publish-v2 <结果1.jsonl> <结果2.jsonl> --triage <model-triage.jsonl> --trace-cloud
```

默认仅统计待发布数量，零网络、零模型调用；显式trace-cloud才把已有trace的封闭数值指标上传到已配置项目。缺失/非有限值不补零，旧E6弱隐私探针不发布，分诊标签名称带unverified。manifest绑定全部结果与来源文件hash；每条上传回执在ignored `.cache/published-v2/`。回执表示接收，不能冒充读回。

每个trace使用一次 `/api/public/ingestion` 的 `score-create` 批次，分数ID按trace和指标幂等，事件ID每次新建，必须所有事件均获successes确认且errors为空才算成功。[官方限流说明](https://langfuse.com/faq/all/api-limits)、[v4评分事件支持](https://langfuse.com/faq/all/deprecated-api-migration)。先前逐条scores接口实际只有2/81组完整接收，其余429；原回执保留。自动审批要求本次批量重发另获具体授权，在用户回答前不执行上传。

本机前端最终验收使用 `web-check --webpack`，包括类型、lint、141项测试及生产构建。默认Turbopack在此本机CSS构建子进程绑定端口失败；[Next.js官方build选项](https://nextjs.org/docs/app/api-reference/cli/next#next-build-options)支持显式Webpack。默认部署配置保持。


## F9中文盲标（2026-10-14，替代本批旧30条表）

本次表为 `.cache/batch-2026-10-14/labeling/标注表.csv`，24个不同用例。AI原文不改，名词解释帮助理解，三个人工问题只填是/否，拿不准就在不确定填是或留题目空白；人工五栏均未预填。先看同目录怎么标.md，先不要看对照表.json。题目评价已有回答，不随后续代码修复变更。

```text
uv run python scripts/dev.py eval-human-sheet
uv run python scripts/dev.py eval-human-score .cache/batch-2026-10-14/labeling/标注表.csv .cache/batch-2026-10-14/labeling/对照表.json
```

生成只读旧CSV/manifest/AI预标注/隐藏参考，绑定hash，输出目录必须不存在，不覆盖。统计零模型调用，三题全是为通过，任一否为失败；不确定/漏填不计，有效至少20条才报告一致率与κ。旧30条格式兼容保留，不把AI参考当真人。生成命令不要对已开始填写的表重复执行。

### F7 内容参考分与封闭事件摘要

内容模型分仅展示为「未校准参考分」，不作为任务通过门槛。`eval-calibration --threshold 3` 保持默认；可选1–5，实际值与task_pass_gate=false写入新manifest。摘要仅有注册工具名、结果码、choice_card、实际attempts、data_mode及预算/记忆卡存在性；旧来源缺失保持未知，不混入正文或第三方资料。旧30份评分文件保持只读；本F批不运行该命令的`--live`，人工至少20有效行前不生成κ结论。

### F8 未核实分诊线索

离线粗检：`uv run python scripts/dev.py eval-triage <results.jsonl> --check-references <model-triage.jsonl> --out <新目录>`。输出用x模式，来源前后hash核对；不允许结合`--live`。当前10条结果在`.cache/batch-2026-10-14/f8-triage/consistency.json`，5不一致/5无法判断；原标签不改、根因准确率不计算。新参数元数据仅闭合类型/操作/范围/组件/日期及服务端选项ID，不含原文值和引用。

### F12/F13 最终验证与保存证据（2026-10-14）

F12共22个真实SDK试验（15计划、7诊断/修复回归），账本新增252HTTP/8.444428CNY。仅各命令进程设置`DAILY_BUDGET_CNY=10`，.env与Railway不动。UTC2026-10-14从08时到09时执行，未跨日；每次HTTP先预占，失败也计入。原始七目录、22条结果的路径/哈希/费用见`docs/evidence/f12-deepseek-acceptance-2026-10-14.json`，同文件记各版本及不同目录trial_key，不混淆同名trial1。

新结果读取时冻结索引`.cache/batch-2026-10-14/f12-frozen-input-hashes-final.json`保留原55项并追加14项结果/manifest；新69项不是全都F0冻结。原22条全部用`eval-simulator-rescore --hashes <此索引> --out <新目录>`离线重算，新输出在`f12-v5/`，原4/9与真实误导不覆盖。错误场景九条v5为8/9；未重跑400/429模型，只有新增无候选3条和拒绝3条用于指引修复回归。三城市3条中1条规则通过、2保存partial，未知10/12不算通过，无保存的约束不填0。

旧51条的最终统一输出在`.cache/batch-2026-10-14/f13-v5/{e7,pace,e5}/`，交互版本`interaction-v5-local-denial`、说法版本`claims-v5-local-denial`；manifest记录实际源4270583及逐文件hash，摘要逐trial列改变检查。旧F5与首次v4、原始19/24和24/24均保留。F6两个记忆集合仍分别20/20和15/15，不混成35/35成功率，不把旧三隔离探针说成实际测过第四项。

最终命令日志：`f13-regression-final-check.log`、`f13-final-full-test.log`（1907 passed/1skip/4deselect，347.53s）、`f13-final-web-generate.log`与`f13-final-web-check.log`（143passed/构建通过）。首轮全量的5失败和基线d237隔离复现保存在`f13-full-test.log`、`f13-baseline-rakuten.log`、`f13-baseline-clock-red.log`；保留验证过程，不以调整安全/金标断言过关。任务状态和最后提交只见批次计划。
