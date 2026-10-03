# Travel Agent 长程执行计划

计划版本：2026-10-03 / v4。此文件是唯一实时执行进度与恢复入口，随每个增量更新。
设计以 plan/01–06 为准；任务 ID 与依赖见 [04](../../plan/实操计划/04-开发任务计划.md)，执行方式见 [workflow](workflow.md)，强制标准见 [standards](standards.md)。

## 用户目标与完成定义

**Goal（用户2026-10-03补充）**：依据当前项目设计、功能和架构说明，完整实现既定范围内的Travel Agent，使系统按设计运行；保留已经正确实现的工作，不重新开始。
需求入口为plan/01–06、docs/tasks与已接受ADR，目前不存在docs/spec目录。遵守plan/04已明确的A/B功能范围与C档仅写ADR边界；不把未来可选功能当本轮实现，不削减现有功能。Claude Agent SDK承担runtime，旅行业务独立实现。

**Acceptance Criteria**：

1. 既定功能全部实现，包含主要条件分支与失败路径，不能只交付happy path。
2. 所有主要功能映射测试：正常、分支、边界、预期失败、非法输入及合理外部工具/API故障，见[测试矩阵](verification.md)。
3. 重要跨模块链路有integration tests；核心用户流程尽可能真实端到端验证。事务/恢复使用真实PostgreSQL。
4. 现有tests、类型、lint、build及相关validation/CI检查通过。区分本地检查与未运行的远端CI，不编造结果。
5. 失败执行diagnose→fix→rerun，持续处理；不要求用户review来结束修复。
6. 不删除失败测试、不降要求、不跳过应该支持的功能、不绕过检查。测试假设调整须与原始设计相符并记录理由。
7. 本计划持续记录完成/剩余、问题、决定、验证、提交和恢复点，操作日志保存过程；不只依赖对话。
8. 验证/审查通过自动进入下一任务，不在milestone后等确认。只有真实产品需求冲突、缺credential/外部权限、高风险不可逆外部操作或无法合理决定的产品方向才升级；隔离后继续独立工作。
9. 最终提供功能范围、主要命令/测试结果、证据、限制/风险与未满足项。有未满足项不得标记整项完成。

模型额度、缺失Claude凭据、Langfuse页面、角色人工校准与完整多次评测如实保持开放；代码存在、脚本替身或小样本不能代替这些证据。

## 执行授权

- 用户授权连续推进，不因阶段完成、尚未合并 main 或学习材料未读而停下。允许独立审查 agent。
- DeepSeek：本轮累计上限 **5.00 CNY / 100 次真实请求**；同时检查 .env 每日 CNY 上限，优先离线。不默认用尽额度。
- 2026-10-03 用户明确回答上述额度；它是新授权，不复用旧两请求许可。其他计费供应商未获准，美元调用额度为 0。
- 新授权累计与每日消费同时核对；已发生的旧探针当日费用/保守占用也应计入每日限制。重启、跨日不重置本轮累计上限。
- 每个实际 HTTP 尝试（失败、重试、压缩/辅助调用）计入 100 次；SDK max_turns 不等于次数。先实现持久计数与保守费用拦截，再 live。
- SDK 自带美元 cost 字段不能当 DeepSeek 账单。金额用 Decimal，按明确模型价表，usage 不明保守记账；预算不足只停付费部分并继续离线。
- 不 push、合并 main、改历史、操作真实订单或发布；保留 workspace-write + auto-review。

## 当前恢复点

- 分支：batch/2026-10-03-travel-autonomous，起点 1d75f79，承接已有工程和 SDK 设计。
- 当前：保留M0/M1/M2原提交，M3.2已保存3590b2c、M3.3已保存f9eb345、M3.1已保存0861da7、M3.4已保存da68f86、M3.5已保存f792c85（正常静态/完整钩子通过）。M3.5工程线路已验、真实Claude未授权/未测。M3.6真实完整规划原4HTTP基线失败并保存Trace；上限截断不计模型选工具根因，保留原失败、不自动付费重试。
- 当前恢复：M4.1独立离线Compose代码/HTTP烟测/重建只读恢复/浏览器确认刷新已通过，独立P2嵌套dotenv已修并实际合成构建验证。正常钩子通过，e427808已保存，继续M4.2冻结60条与业务初始状态/副作用评分；不等待用户review。M3.6原规划修复后9HTTP仍incomplete_output（4次max_tokens），原失败保留，不自动付费重试；三独立真实坏例、完整行程对照/重复统计、Claude/Cloud/人工验收仍开放。
- 本轮新授权消耗：**80 次 / 2.076890 CNY 保守估计**，无未结预占；以 `.cache/model-budget/deepseek.jsonl` 为准。剩余 20 次，费用仍需同时满足每日与全程限制；暂无后续付费重试。
- 最新完整复跑511项通过（145.96秒），2项live默认排除；后续自动评审新增专项56通过，check204文件/3契约/10地图通过。最新web-check type/lint/10测试/build通过。正常提交钩子须包含新评审/诊断再全量执行；先前一次偶发持久化失败保留且根因未确认。远端CI未运行。PG0010。


## 进度

| 阶段 | 当前状态 | 要交付的可观察结果 | 主要验收 |
| --- | --- | --- | --- |
| 工作流切换 | verified | 连续推进与可恢复记录，不再要求逐项人工审阅 | 602669b；70 离线测试、独立审查修复 |
| M0.1 | verified（历史本地增量） | 工程骨架、开发命令、上游固定版本 | fce98f9；原审阅材料保留 |
| 旧 M0.2 探针 | partial（历史实验） | Messages 最小工具往返，不是 SDK runtime | 3819723；2 次真实请求 |
| 新 M0.2 | verified | SDK 接入与费用/工具/进程边界 | d2a1b13；SDK 0.2.163、MCP 2.3.0、CLI 2.1.114；123 离线测试，2 次 live 请求；见 [证据](../protocol-agent-sdk.md) |
| M0.3 | verified | 应用边界、会话引用、MCP 桥接 | e2d848d；149 离线测试/独立审查通过；两项审查问题有回归保护 |
| M0.4 | verified | 旅行搜索与 CLI | 727778b；20 景点/12 攻略 fixture；166 离线测试；SDK 本地续接及 3 次请求真实查询通过；[证据](../evidence/travel-query-2026-10-03.json) |
| M0.5 | partial | 本地 Trace 和可选云导出 | 837b8f0；176离线测试，真实本机OTLP传输；[Langfuse UI 待配置](../blocked/langfuse.md)，不阻塞其他开发 |
| M0.6 | partial | 21条初始用例、规则评分、版本与恢复记录 | 离线全表已运行；首次live 1通过/1规则失败/1限次错误/18未跑，见[真实证据](../evidence/m06-baseline-2026-10-03.json) |
| M0.7 | partial | 中性角色草案和语气评测设施 | [范围坏例回归](../evidence/m07-scope-regression-2026-10-03.json)；[LLM/人工校准待办](../blocked/persona-calibration.md) |
| M1.1 | verified | API、身份/会话、真实数据库与迁移、CI配置 | d2cfb12；205测试/独立复核；[HTTP实测](../evidence/m11-api-smoke-2026-10-03.json)；CI未远端运行 |
| M1.2 | verified | 真实京都快照、许可/来源、营业时间子集与导入 | 6443071；146 OSM对象+20段攻略；221完整测试/独立审查通过 |
| M1.3 | verified | TravelRequest与Evidence版本/归属/失效规则 | 723575a；238完整测试/check102文件通过，独立关卡关闭 |
| M1.4 | verified | 数据库工具、消息去重/单执行/取消、有序事件与SSE | baa7cf9；263完整测试/check116文件/独立复核通过；真实SDK与DB离线往返、HTTP/SSE通过 |
| M1.5 | verified | 6虚构酒店/12报价组合、刷新与同口径比较卡片 | 5415e60；282完整测试/check125文件与文档地图通过，6.1-sol high复核无P1/P2 |
| M1.6 | verified | 纯行程校验/估算路线/SDK修复反馈 | 3dd92c0；302完整测试/check132文件；实际SDK离线修复/上限、真实PG；独立审查两项P2已关闭 |
| M1.7 | verified | 稳定item_id局部修改、草稿/差异、确认幂等 | e40c259；320完整测试/check139文件，真实PG竞争/回滚、实际SDK离线stage/present，独立P2已关闭 |
| M1.8 | verified（d239cc7） | 网页完成规划→修改→确认保存 | 前端类型/构建、R01–R08、端到端流程 |
| M1.9 | verified（0b6fd8c） | 完整演示和30条回归 | R01–R08与页面证据 |
| M2.1–M2.6 | verified（4a12656） | 模拟预订、对账、重启与断线恢复 | R09–R12，真实PG/HTTP/浏览器；真实失败小样本前后证据 |
| M3.1–M3.6 | M3.1/M3.2/M3.3 verified / M3.4 partial（da68f86）/ M3.5 partial（f792c85）/ M3.6 in_progress | 上下文/偏好、对外 MCP、编排对照、坏例修复 | R13–R17/R19；授权范围内模型实验；真实压缩质量未计入机制验收 |
| M4.1–M4.5 | M4.1 partial（离线应用容器已验，Cloud UI待凭据）；M4.2 partial（冻结/离线重复已验，真实120运行未授权） | 可启动交付、回归报告、演示与学习索引 | 构建、冻结集、最终独立审查；未测项明示 |

执行时把当前阶段展开为任务级进度，附 commit 和证据链接；不为用户制造逐项批准待办。

## 质量与审查关卡

每个可验证功能增量 check/test、自审与独立审查通过后保存；M0.2/M0.3/M1.3/M1.6/M1.7/M2.2/M2.4 进一步核查跨模块不变量。审查通过直接进入依赖任务，无需合并。
领域规则用失败路径测试保护；事务/恢复用真实 PostgreSQL，不能用内存替身冒充。前端需构建与真实页面检查；费用与外部条件不满足的验收保持待办。

## 决定记录

- 2026-10-03 M3.5：默认DeepSeek/CNY，LLM_PROVIDER显式anthropic才选择Claude/USD；不按存在的key自动切换/回退。复用SDK与原预算/传输/Trace，不引入新runtime或依赖。USD累计0元/0次，预算配置不是授权。旧CNY仅读取时归一化并保持原写入格式，32次/0.301908及SHA256核对不变。
- 2026-10-03：核对Anthropic官方当前模型/价表；锁定Haiku4.5快照支持现有disabled thinking与工具模式，缓存创建按最高1h写价2x保守结算/预占，读缓存按普通输入上界。最新Sonnet5.5的thinking等协议改变，现有锁定SDK配置未验证，明确拒绝，不填假兼容。

- 2026-10-03：用户补充明确Goal与9项Acceptance Criteria，纳入v4及测试矩阵；不重启、不丢已有正确实现。M1.8/M1.9新增改动使用各自实际验证，不能套用e40c259的320测试证据。

- 2026-10-03：用户改用gpt-6.1-sol high继续开发；复杂故障先定位并留下证据，不自行升级档位。独立审查默认少量文件/必要上下文，减少重复阅读和全量重跑。
- 2026-10-03：核对Harness engineering后新增ARCHITECTURE和docs设计/前端/可靠性/安全/质量地图，链接既有设计/规则；dev check检查入口和仓库链接。plan仍设计唯一来源，不维护两份进度。

- 2026-10-03：用户强调 SDK 优先和简洁复用，已写入 AGENTS/工程标准 §3.4；参考 commerce-agents 的薄入口、共享工具契约与统一执行器。当前接入代码先做简洁性审查；后续不复制探针保护代码或另建运行时。

- 2026-10-03：按用户要求采用连续工作流；旧关卡保留技术验收作用，取消人工批准/合并要求。用户最终集中学习。
- 继续现有 SDK 设计，不新建第二套 runtime。OpenAI/Gemini 仍为扩展；Claude 对比代码可写，真实调用未授权。
- 为避免两份状态，04 留任务定义/依赖，本文件维护实施状态；历史审阅记录不删除。
- 角色暂用中性可配置草案；最终人格与人工校准不伪装成已完成，不阻塞其他业务实现。
- 独立审查建议已采纳：真实 SDK 验收与离线业务实现分开，未知 runtime 语义不能污染下游接口；本轮已有 DeepSeek 整体授权。

## 发现与风险

- M2.1：独立供应商/0006迁移与四种故障已实现；4专项PG/真实HTTP通过（1.15秒）。独立规格审查P3指出暂时查无可能迟到创建，已采用锁内过期缺席证明并加入实际超时/迟到对照。不标整项完成，Booking/恢复仍未实施。


- M1.9：HTTP全链/重启只读新增回归，完整329测试/check通过；30条规格仍保留1/30离线规则结果，DB业务评测适配待M3.4。独立无P1/P2，P3缺字段时允许记录已知条件已修。真实模型效果与进程故障仍开放。


- M1.8：Next工作台/生成契约/持久presentation/三个免费脚本已实现；初次3处类型错误与样例参数拼写已修。完整326测试、web-check与浏览器验证通过；独立3P2/1P3及截断歧义已修并复核关闭。真实浏览器丢包/进程故障仍在M2，不用函数测试替代。
- pnpm11忽略旧.npmrc store配置；首次安装写到D:默认store。已仅重装项目node_modules，workspace配置限定缓存到.cache；未删除外部store。工具依赖固定兼容的ESLint9/TS5，peer检查通过；拒绝非必要依赖安装脚本。

- Anthropic Messages SDK 与 Claude Agent SDK 是不同运行方式，旧探针不能证明新 runtime 兼容。
- SDK 内部请求、工具权限、Windows CLI 和 MCP 版本需实际核查。兼容失败保留证据，不静默更换来源。
- 100 次授权不保证足够完成 60 条 × 3 次及多模型评测；先完成关键小样本与离线回归，额度不足的完整统计保持待验收，不降低标准刷通过。
- 人工学习/校准与缺失 Claude 授权是后续外部条件，不要求用户现在反复审批普通编码任务。

## 验证与恢复记录

规则调整和后续操作见 [本轮操作日志](../operations/2026-10-03-autonomous.md)。
最新命令结果/独立审查/提交在执行后追加；没运行的不填“通过”。

## 最终交付清单

- [ ] 运行入口、环境配置、演示数据和启动/停止说明。
- [ ] 业务链路、模拟故障、版本/幂等/恢复的可重放证据。
- [ ] 测试、构建、评测、费用和独立审查报告。
- [ ] 一份按调用链组织的学习索引，关键取舍与实际失败故事；不要求用户先读完所有日志。
- [ ] 待验收项及其原因；最终由用户集中架构 review、运行与学习。

## M4.2 当前实施恢复点

初始正式行程/锁/报价时效/预订/偏好墓碑/历史通过现有服务构造，setup独立run_id不计模型轨迹；共用专用临时本地PG与本机HTTP设施。事后正式版本/完整订单集合/偏好比较，unknown保留用户/API对账边界；暂留与故障绑定本轮调用/实际Evidence/供应商请求。
60条20dev/40test已独立审查并冻结travel-eval-v1，旧30期待/hash保留，19旧dev原样沿用，不改名test。72专项通过21.50秒；check202文件/3契约/10地图通过。实际离线test三轮120案例，0执行错误/0未跑/0付费，每轮3/40规则通过；不当作真实模型成功率。临时专用库正常移除，父库/账本hash不变，证据见docs/evidence/m42-offline-repeat-2026-10-03.json。独立五P2/一P3关闭，完整Python506 passed/2 live deselected（140.03秒），独立复核无剩余P1/P2，正常钩子通过，e86ad6e已保存。后续真实SDK离线复现终止字段误分类/规划6轮不足，修复21专项通过；完整回归正在验证，等待通过后做有代码依据的一次原dev真实回归（最多12HTTP，既有额度内，不自动重试），再推进可重放演示与学习材料。
当前费用80/2.076890，剩余20HTTP；40×3最低120HTTP预检拒绝，完整真实模型重复统计保持开放。模型规划incomplete_output、三独立真实坏例、Claude授权、Cloud UI与人工校准未验，不能把整体标为完成。

## SDK链路修复恢复点

本机实际SDK两HTTP终止字段error_max_turns/tool_use被旧代码误归incomplete_output，新优先级修复仍失败无checkpoint。另一截断脚本四HTTP全计数/is_error=true。实际三日链路8工具+回答在DB6轮只到validate、blocked/max_turns；仅DB SDK12轮后9HTTP完成六项草稿/卡片，正式V0。普通搜索6、HTTP12/工具16/三修复/授权不变，check202/21专项通过，独立审查无P1/P2；完整回归运行中，代码未提交，无新付费。

## 原dev修复后一次真实回归

20261003T113648Z-a696428b：8HTTP/0.322942CNY、guard无失败；原规则error，SDK invalid_assistant_message。15工具中13次search_places、一次条件更新和一次酒店查询，没有facts/路线/校验/暂存/展示；最后四HTTP均max_tokens。DB12SDK轮不能单独解决模型的重复搜索/截断，不能宣称规划模型成功。原失败/Trace保留，不自动重试；累计59/1.257420，无未结预占。下一步先缩小规划提示的搜索路径歧义并离线核对，不调整HTTP/工具/费用保护或冻结test。

规划提示修正仅应用系统提示：服务端已有一致条件不重复更新，无兴趣时用京都宽查询；少量候选后从place_id读取当前Evidence，再推进住宿/路线/validate/stage/present，不复制资料。实际本机PG京都宽查询返回4条候选，未改检索函数/工具/冻结期待/预算，不新增runtime。check202通过；相关回归运行后再做一次原dev新提示回归，最多12HTTP，失败不自动重试。


## 原dev工具展示契约恢复点

20261003T114222Z-6424d8e2：新规划提示后10HTTP/0.452110CNY，SDK完成、guard无失败；原规则仍failed/tool_success。14工具已走到5次facts、路线、validate和stage，但present错误混入酒店专属expected_revision，原校验拒绝，无展示卡片。Trace 8d2539ef9c5fd57bfb77cbd1cf01208f。仅补两类参数互斥描述/错误反馈，不放宽validator、不修改冻结期待；26专项通过14.67秒，check202通过。累计69/1.709530，无未结预占。上一SDK增量完整511 passed/2 live deselected（145.88秒），当前最终钩子待运行。


20261003T114932Z-4e630873展示契约修复后原dev一次实测：10HTTP/0.365238CNY、guard无失败、SDKsuccess、原规则1/1通过；14工具/6事实/路线/validate/stage/present，实际持久事件展示6项草稿，正式确认未执行。validation partial：7 verified/13 unknown/0 conflict，部分营业/路线/预算未知、未选住宿；不当完整规划质量或统计提升。Trace 1474ad2c4069be5aa7a0732d54e5febf；证据docs/evidence/m36-planning-regression-2026-10-03.json保留同输入前三新代码实验和原失败。累计79/2.074768、0未结预占、剩余21HTTP，不再重复付费调此dev。下一步保存SDK/提示/契约与集中学习索引，随后补M0.7固定温度LLM评审的技术实现，人工校准/大样本/外部凭据仍开放。


## M0.7 自动评审补齐恢复点

ADR011先记录固定温度方案；复用唯一run_live/隔离worker/ClaudeRuntime，专用persona_judge只DeepSeek/零工具/无DB供应商workflow，不暴露给用户消息API。固定rubric移动到共享persona，eval沿用解析/校准；Guard评审分支明确temperature0与thinking disabled，正常旅行bytes不变。实际锁定CLI发送temp1且省略thinking，两次离线失败定位后修复；43专项4.01秒/check204通过，durable UUID序列化首测错误也已修，不改测试要求。eval.judge默认准备，显式live才收费，manifest/attempts/results/samples逐调用flush/fsync，JSON错误judge_error无分、运行错误停止余下样本；真人分保留。独立复核进行中，无新增真实费用。

先前完整提交钩子失败未提交；原workbench持久化失败专项/15组复跑过，随后完整511 passed/2 live deselected（145.96秒）通过。最近PG容器无ERROR，暂未确认偶发根因；新增脱敏类型/SQLSTATE诊断及实际PG写入故障注入，要求unavailable恢复核对且不泄漏SQL/参数，29相关通过4.07秒。保留原失败，不声称已定位根因。最终正常钩子须包含新评审/诊断测试再保存。


M0.7固定温度一次真实小样本：.cache/persona/557cb6fc-70c7-4748-9559-439065ede2d7，1HTTP/0.002122CNY，实际temperature0/零工具/合法JudgeScore，真人配对0，calibration pending（不公开原回答/评审理由）；证据docs/evidence/m07-persona-judge-2026-10-03.json，Trace a637bf02dc340727432cea0bc87c1eeb。独立无P1/P2；新增启动前拒绝DB/supplier/workflow/provider、多prompt和actualSDK非法JSON/未授权工具反例，56专项7.64秒/check204通过。累计80/2.076890，0未结预占；剩余20HTTP，不消耗余量凑20条假人工校准。前端最新web-check type/lint/10测试/build通过。M0.7代码/小样本可验，最终角色/20真人校准仍partial；正常提交钩子全量待运行。


M4.4–4.5集中材料：docs/review/learning.md/demos.md/resume-draft.md已形成调用链、三段重放入口和证据审计稿。项目表述用great-resume技能、只列实际工程/数据与费用/模型边界，个人贡献标待确认，无对外消息/发布；不写模型提升或真人校准。C档ADR按plan“A档完成前不开始C”继续延后，不因学习材料ready改产品范围。下一步正常钩子保存当前合并增量；如通过继续全仓剩余验收审计，不等待用户批准。


## Goal/AC 剩余离线缺口审计

独立autonomy_review对照plan/05发现可继续自主补齐的3项：逐次工具调用准确率（当前只有case级布尔/调用数，须保留语义参数unknown）；首次有意义进度延迟（当前仅总耗时，须排除启动/心跳、缺失null）；B0/B3与单因素控制（当前仅固定workflow/自主，须仍复用SDK与强制安全校验，SDK无可靠压缩关闭开关则明确限制）。不把这些伪装成外部阻塞；当前增量保存后继续。

第二次正常钩子失败：540 passed/3 failed/2 excluded/1 error（149.73秒）。三处原parent故障测试工厂不接受新增temperature关键字，已恢复普通Guard调用兼容，仅评审serve前设置temperature0，原测试未改；初始化数据库一次unavailable仍未定位，common事务边界补共享脱敏异常类型/标准SQLSTATE日志。44相关9.62秒/11故障工作台6.53秒通过。无自动重试/调超时/跳过；正常钩子须再次完整验证。
