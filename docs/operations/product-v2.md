# V2 本地验收记录（2026-10-04）

本页只汇总实际证据；当前恢复点在[执行计划](../execution/travel-agent.md)，实现范围在[产品V2](../proposals/PRODUCT-V2-PLAN.md)。没有恢复旧 evaluation。

## 真实核心流程

大阪前端请求：2026-10-13—15、2成人、1间房、60000JPY、步行。真实 DeepSeek 经 Claude Agent SDK 调用 Google Geocoding/Places/Routes、乐天及 Open-Meteo，使用真实 PostgreSQL。

- run：`729bf445-e612-4c93-a71c-8b638c36601a`，completed、无error_code，15个成功工具步骤。
- 真实两家酒店、四个景点、一路线、天气；未知门票/餐饮/酒店选择不冒填，行程校验无冲突。
- 前端展示、确认正式V1 `2c37582b-e650-4c52-92be-b6224e3bf9d4`，后端/前端重启后同身份读回四景点。
- 日历接口HTTP200；没有真实订房或付款，PG booking为0。
- 10模型HTTP，预算账本新增 `0.395230 CNY` 保守上界。

实现已保存并push `66649fa`、`eb6ff4d`、`744f410`。本轮追加补齐缓存、调用上限、手动入口、三城验证和文档。

## 四城与常见失败

2026-10-04 UTC 12时前后执行，每城单独显式运行，不循环、不放CI。

| 城市 | 命令 / run | 真实结果 | 模型HTTP / CNY上界 |
|---|---|---|---|
| 大阪 | 上述前端流程 | 酒店比较、真实景点/路线/天气、确认、重启恢复 | 10 / 0.395230 |
| 札幌 | `python -m scripts.smoke_live --execute --city 札幌 --base-url http://127.0.0.1:8000`；`29a860b2-7557-4832-8bb4-0bd8d5a185fa` | completed，真实酒店搜索、景点/路线/天气和草稿 `684b19a3-fc7d-4b73-9338-4dd22cc92153`；天气复用PG缓存 | 9 / 0.358114 |
| 那霸 | 同命令 `--city 那霸`；`43ebc296-5909-403a-ad87-e29ec5a1a79c` | completed，酒店工具unavailable后继续真实景点/路线/天气，草稿 `9e2e5fe0-e301-4d99-8a65-72031d9df776`；缺酒店保持未知 | 7 / 0.223128 |
| 箱根 | 同命令 `--city 箱根`；`d9de77b6-9574-4d50-9593-e2fb3458dfbd` | completed，真实酒店搜索、景点/路线/天气，草稿 `e93e520d-233c-4da2-814a-0edb00995ad2`；无效刷新/额度拒绝没有崩溃 | 8 / 0.333728 |

三城的酒店展示/刷新有模型参数错误或供应商失败，工具明确blocked/unavailable；不能称每个工具全成功。所有三城均完成规划和返回草稿，大阪已有完整前端操作证据。

札幌首轮 `373788af-e9da-473b-8261-84146ba8cdea` 未生成草稿，3模型HTTP / 0.057788 CNY上界。只读计数确认：界面恢复消耗详情后 Places 已25次，工具正确拒绝；本地乐天 Referer 缺失。补齐注册应用的 Referer/Origin配置，用户明确批准仅今日增加3次 Places 后，只复核该失败一次，原失败保留。

那霸主流程酒店不可用原因没有被元数据精确保留，不冒称已证明根因。随后使用已缓存城市坐标，独立做一次单晚和一次两晚乐天查询：分别消耗1次、2次HTTP，两次均返回2家真实酒店，0模型/Places请求。不复跑已经成功的规划，不把独立查询当同轮全部成功。

## 计数与预算

累计UTC当日实测计数（含失败和原阶段定位）：Geocode **5**、Places **28**、Routes **5**、乐天 **23**、天气 **4**。模型本轮V2共37HTTP，账本共新增 **1.367988 CNY保守上界**，不是供应商账单。历史3287请求/75.597392 CNY保持不动。

补三城前快照：geocode3/places25/routes1/rakuten12/weather2；三城及必要酒店定位合计增量：geocode2/places3/routes4/rakuten11/weather2。每run模型数来自原私有SDK报告；没有完整的原per-run数据HTTP快照时只报告合计，不编造逐城精确拆分。

临时28只通过后端进程环境设置，三城结束后已停止该进程并以 `.env` 的25重新启动。PG历史次数没有重置；当天余额为0，下一UTC日可继续。最终本地后端端口8000、前端3000，现有公网Railway仍是旧离线版。

## 缓存、接口入口和离线验证

- 新迁移0012已应用真实开发PG：天气按城市/起止日期共享缓存3小时，跨run命中不发HTTP；过期重新请求。空响应或日期范围不匹配拒绝缓存。
- 乐天单run上限为 `min(住宿晚数+1,8)`，失败也扣计数；多晚匹配保留现有规则。
- `tests/fixtures/`四份人工合成接口结构，不持久录制Google详情/真实公开报价。
- `tests/live/test_real_apis.py`仅显式选一个接口；默认测试排除，不自动循环，不输出响应。
- `scripts/smoke_live.py`仅显式单城一轮；输出工具状态、引用、数据次数增量与DeepSeek上界，不保存模型回答或供应商地点详情。
- 最终默认全量离线回归 **798 passed、3 live deselected、215.45s**；239文件三平台strict、ruff/格式、3分层契约与10份文档地图通过。独立只读审查三项P2（统计供应商选择、探针额外前置查询、天气空/错日期缓存）均已局部修复并复核无P1/P2。不引入新依赖。

## 个人 Google Calendar 真实导入

2026-10-04，在个人账号创建专用日历 **Travel Agent V2 验收（合成样本）**。真实本地API/PG创建离线京都行程，日历接口导出6个VEVENT；上传该ICS后Google页面确认 **“已导入6个活动，共6个”**。每个景点一个事件；这是文件格式兼容验收，不冒充大阪真实景点文件导入。

证据位于ignored私有缓存 `.cache/v2-verification/calendar-import.jpg` 和 `calendar-compatibility.ics`。没有邀请参会者、创建付款或操作公司日历。扩展文件权限先由用户明确允许临时开启，导入完成后用户已确认关闭；工具因浏览器安全策略未自行改扩展设置。

## 剩余范围

截至2026-10-04，Railway V2发布、Claude真实API、V2同轮Cloud trace实测未进行。2026-10-05代码发布和DeepSeek启用见下文；云端Google/乐天凭据已配置，实际景点/酒店/有效日期天气查询通过，整轮规划仍受DeepSeek上游超时影响，见末节。核心流程没有已知P0/P1；额度耗尽是实际运行限制，不能通过清账隐藏。旧Cloud证据和已接线代码不能替代本轮实测。

## Railway代码更新（2026-10-05）

用户授权操作其已登录Chrome，将当前本地最新代码发布到既有项目 `449ee30a-0ff4-437a-a35a-53ddc5c4ef93` 的production。三个代码服务原绑定旧前端分支，API上一轮因SupplierClient拒绝固定模拟供应商私网地址而健康失败。按ADR-008只补精确 `supplier.railway.internal`，不放开任意私网/公共域名；无新依赖或runtime。27专项通过、236文件三平台strict及格式/lint/分层/文档检查通过，独立只读窄审查无P0/P1/P2。功能提交 `75318535b5494bd247d862d37eeaeb4146f26080` 的正常check和完整test钩子Passed，普通push成功，ls-remote完整SHA一致。

已将api/web/supplier切到 `batch/2026-10-04-product-v2`，Details核对仅三项Branch变化后Deploy Changes。三个代码服务与Postgres均Online，api/web部署详情链接精确功能提交。该轮部署ID：api `d42e637d-9695-4b20-9035-5dd5431743e0`、web `faf35171-0145-46fe-9f1f-4573a44ea30b`、supplier `18e3a7ed-feb1-4150-af4b-937f947c0279`。保持既有自动部署、Dockerfile、私网代理、迁移/快照导入启动及Postgres卷；以后push同一分支自动更新，新分支须更新三个服务绑定。

公网 [web](https://web-production-0aaac.up.railway.app)：同源health HTTP200/status=ok，models HTTP200且仅offline可用，articles HTTP200/20条。复用 `scripts.smoke_demo`、只在运行时改BASE和STATE，完整core_flows退出0：比较酒店、生成/确认行程、修改第二天下午、模拟供应商确认幂等、非法版本/其他用户拒绝、live拒绝、SSE末次游标读取与恢复均通过。合成身份/模拟订单的私有恢复状态在ignored `.cache/railway-v2-smoke/state.json`，不写入提交或日志。Chrome实际进入最新版工作台，分景点/酒店/天气的数据说明及官方链接均可见。此次0真实模型或旅行数据API调用，不操作真实订单/付款；模型/供应商密钥和.env未上传，云端未以--live启动。

环境恢复：首次正常提交的610项非PG测试通过，187项PG用例因Docker未运行而setup失败；未跳过测试。启动Desktop后发现两处残留AF_UNIX套接字导致后台崩溃。仅元数据检查确认 `C:/Users/user/AppData/Local/Docker/run` 及 `C:/Users/user/AppData/Local/docker-secrets-engine` 含0字节运行时套接字、无凭据/配置/数据后，核对精确绝对路径，原目录重命名备份并重建。保留 `Docker/run.travel-agent-20261005-0310`、`Docker/run.travel-agent-20261005-0311` 和 `docker-secrets-engine.travel-agent-20261005-0311`；未删除任何文件、修改安全设置或触碰数据库卷。Docker28.5.1恢复，dev db-up退出0/既有项目PG Healthy，重新正常提交钩子全部Passed。自动审批拒绝展开云端变量值（可能暴露DATABASE_URL）后保持遮罩，通过日志/健康/既有API脚本完成部署验收，未读取数据库凭据。

## Railway DeepSeek live启用（2026-10-05）

用户随后要求启用live，并明确允许将本地已有DeepSeek密钥写入该项目api服务。已在用户Chrome发布变量：DEEPSEEK_API_KEY（遮罩）、LLM_PROVIDER=deepseek、DEEPSEEK_MODEL=deepseek-flash、DAILY_BUDGET_CNY=15.00、DAILY_BUDGET_USD=0。没有输出或提交密钥，没有上传整个.env；Anthropic及Google/乐天凭据未配置。健康接口200，模型选择器DeepSeek available=true/无拒绝原因，Claude仍因缺凭据禁用。

独立只读审查识别两项部署问题：现有CLI查找器只查显式路径/PATH，镜像内SDK bundled CLI需要显式指定；原/app/.cache是容器临时目录，会因重部署丢失预算。已配置TRAVEL_CLAUDE_CLI=/app/.venv/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude，新建api-volume（ea80d5f1-0425-44b9-82d1-7c87cf2a7f7b）挂载/app/.cache，保留单副本。依据[Railway卷权限说明](https://docs.railway.com/volumes)，仅启动初始化使用RAILWAY_RUN_UID=0；下面命令立即清补充组并降到既有10001用户，模型、迁移和API均保持非root。无新依赖或业务源码变化。

当前Start Command（非密钥）：

```sh
python -c 'import os; os.chown("/app/.cache",10001,10001); os.setgroups([]); os.setgid(10001); os.setuid(10001); os.umask(0o077); os.execvp("sh",["sh","-c","test \"$RAILWAY_VOLUME_MOUNT_PATH\" = /app/.cache && test -w /app/.cache && \"$TRAVEL_CLAUDE_CLI\" --version && python -m scripts.bootstrap_demo && exec python -m backend.server --host 0.0.0.0 --live"])'
```

部署55f9a0ad-7b2d-48ea-954d-8c50e4abc786 Active；启动日志确认CLI2.1.286、bootstrap166项成功、API启动完成及health200，证明挂载/可写/CLI前置检查通过。独立复核该补齐无新增P1/P2；不清空任何旧账本或锁。生产后续push仍沿用该挂载和启动命令。

Chrome实际选中DeepSeek，发送“你好，请只用一句话介绍你能帮我做什么，不调用任何工具。”，页面显示“完成”及真实模型介绍回复。一次云端模型流程，未重放；没有工具步骤、真实旅行数据查询、订单或付款。逐HTTP云端账本本轮未读取，请求次数/金额不冒报；15CNY配置与既有守卫不等同实付账单。私有截图railway-deepseek-live.jpg保存于本次Codex可视化目录；不进入仓库。简单回复仅证明模型可执行，不代替Google/乐天真实规划或Cloud trace验收。

## Railway旅行数据接线（2026-10-05）

用户实际在公网输入京都2026-11-06至07两天一夜；模型能回复，但景点、天气、酒店工具报配置缺失。云端变量检查确认缺Google/乐天；本地已有。用户明确允许把四个现有Google/乐天凭据保存到既有api服务后，Chrome发布GOOGLE_MAPS_API_KEY、RAKUTEN_APP_ID、RAKUTEN_ACCESS_KEY、RAKUTEN_AFFILIATE_ID（全部遮罩），以及RAKUTEN_REFERER=https://web-production-0aaac.up.railway.app/。明确五个原daily caps：geocode50/places25/routes150/rakuten150/weather200；没有提高原额度，未更改供应商账号权限、凭据或来源注册。没有上传整个.env或输出任何凭据。

独立接线审查确认API与SDK工作进程均接收变量，无遗漏/新增P1/P2。天气使用Open-Meteo，不需key；当前工具先用Google定位城市，原缺Google也连带阻断天气。11/06–07超出10/05起16天窗口，合法结果应为unknown；最早10/23可覆盖两日。模型参数/日期不被偷偷改变，不补造远期天气。

发布后一次原条件重试run c1a0a2a3-bc94-4c54-b2da-fe20684de3ef：天气日期判断、search_places三次、search_hotel_offers一次、estimate_routes一次，共6成功工具步骤。Google/乐天真实响应证明凭据与来源有效；最后模型HTTP超过现有50秒上游总期限，guard记录timeout/client_disconnected，最终provider_error，无草稿，不冒称整轮完成。6模型HTTP，新增2.259656CNY保守占用（包括超时未结预占，非账单）。下一次仅要求复用证据恢复；实际查询次数以下文记录为准，不清账、不重复原消息。

另经用户Chrome的Railway Console，用已部署项目LiveData、ApiUsage和forecast验证10/12–13天气：verified/2日/Open-Meteo，weather1请求计入同一真实PG；Google坐标命中此前缓存，无额外geocode。探针进程写缓存前降UID/GID10001并umask077，用户会话日期未修改，无额外模型或酒店查询。该时点云端PG当日计数geocode1/places3/rakuten1/routes5/weather1；模型累计11HTTP/2.383102CNY保守占用（含先前模型验收和用户原失败流程），旧账本/预占保持不动。后续根据确定的故障修代码，部署后仅做一次有依据的恢复验收，不循环付费。

证据复用恢复run9259c1f2-24bd-4fb2-b5ea-5c184b620377再次在上游50秒总期限失败，5HTTP/新增2.265514CNY保守占用。3个get_place_facts及1个search_hotel_offers成功，模型实际主动刷新数据，不能将提示“不重新搜索”当作实际零查询证据。云端累计16模型HTTP/4.648616CNY保守占用，PG当天geocode1/places6/rakuten2/routes5/weather1；两条失败原样保留，未生成/确认/预订。两次相同失败后只先修代码期限，不再盲目重试。

根据[DeepSeek请求保活说明](https://api-docs.deepseek.com/quick_start/rate_limit/)，流式响应可能等待并持续发保活注释；本项目此前即使仍有保活也会被整个上游进程50秒硬期限终止。现复用profile统一有界期限：DEFAULT上游90、socket85、SDK客户端100、worker210、父进程220、API240秒；RELAXED上游120、socket115、客户端130，外层保持280/290/300。只新增档位字段，不加第二套运行时、传输重试或依赖；原模型次数/输出/数据次数和15CNY/USD0保持不变。guard上游socket/进程timeout成为API timeout，但不覆盖显式cancelled，避免通用解析错误掩盖根因。83离线专项通过，覆盖两档传输、秘密不继承、超时预占不退/只尝试一次、终态分类与内外期限一致；独立审查识别socket误分类和取消被覆盖两项P2，均已修复并补回归，复核无剩余P1/P2，正常完整提交钩子已通过，发布及真实剩余问题见下文。外层运行期限不含有界guard清理，不能宣称为整轮硬墙钟上限。


源码修复提交9326a53ea3a7df1c737d2bbee0e3ef655a91b47b已普通push，远端完整SHA一致；正常project-check和project-test钩子均Passed。完整离线807 passed/1 live deselected（211.18s），237文件三平台strict、ruff/格式、3分层契约与10文档入口通过。首次钩子识别测试通过http.sys访问未显式导出，改为标准库sys导入后正常重跑钩子通过，没有跳过PG或断言。api/web/supplier均Active且Details精确关联功能提交；部署分别833aa872-df95-487f-a1cb-708579b23a49、bc43f226-cd0e-4b72-aa5d-698455153c8f、dc7156e9-d88d-4ad1-911e-e325d046f37c。api启动CLI2.1.286、bootstrap166项与health200，持久卷和非root启动命令不变。重新部署后、付费验收前只读核对模型账本仍16HTTP/4.648616CNY与PG原计数一致，证明没有清账。

修复后仅一次原条件验收run abcf3785-0572-4789-acd2-d37b99f4a6e1仍failed，但已正确显示timeout/upstream_timeout。3模型HTTP/新增2.177554CNY保守占用；search_places两次、search_hotel_offers及get_weather_forecast共4成功工具，Google/酒店可用、远期天气unknown判断正常。最终上游仍超过新90秒总期限；不将期限延长当作完成规划证据。云端当日累计19HTTP/6.826170CNY保守占用（含三轮未结预占，非实付账单），PG geocode1/places8/rakuten3/routes5/weather1。没有行程草稿、确认或真实预订。三类数据接线及实际接口验证完成，整轮生成仍有DeepSeek上游等待问题；停止付费重复，不清账或进一步放宽限额。恢复只读核对当前部署/记录；无新的故障证据不重跑同一请求。仅文档交付提交复用上述同源码完整回归，保留project-check、跳过重复project-test；push后核对最终部署，不再付费测试。

## 京都10月7–8日超时定位（2026-10-05，当前恢复入口）

用户再次反馈近日期两天一夜规划失败，cloud run bda36dd5-c24c-47a5-87d7-5d57106772ce从04:22:06.647至04:23:49.635UTC（约103秒），update_travel_request和search_places两次成功；第一模型HTTP9180input/1709output/tool_use，第二模型HTTP超过90秒上游总期限，guard仅timeout，没有预算拒绝。新增2HTTP/2.145568CNY保守占用，云端累计21HTTP/8.971738CNY，PG当天geocode1/places10/rakuten3/routes5/weather1。不是密钥缺失，也不能把页面通用提示当额度不足证据。当前近日期在天气窗口内，原远期天气限制不解释这次失败。

在用户Chrome Railway Console用真实SDK和bundled CLI2.1.286、本地合成Messages及独立temp预算做离线协议核对并复核thinking字段确实省略：runtime.options已经thinking disabled，但实际forward body省略thinking，output_config.effort=high，2048max_tokens/1899bytes/1工具；0真实上游HTTP/数据API，进程先降10001/umask077，不读取或输出密钥/提示/思考正文。依据[DeepSeek思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)，省略时默认开启且high。已证明CLI选项未落实到DeepSeek出站协议；不能仅再加期限。独立审查另用纯内存HTTPResponse证明完整SSE message_stop后没有HTTP结束chunk时，旧read(1MiB+1)仍等待并timeout；尚无旧真实失败收到终态的证据，不能断言每次均由EOF缺陷导致。

最小源码修复：DeepSeek请求在已有校验边界显式thinking disabled并移除effort，保留其他output_config字段；显式启用思考拒绝，Anthropic原文不变。HTTP read1增量读完整SSE帧后终止，保留原响应交给既有usage/工具/终态校验、1MiB上限、原90秒期限与所有费用/次数不变量。前端timeout提示改为真实等待超时，已完成步骤保留，不再暗示Key/额度错误。133离线专项通过；238文件三平台strict/ruff/分层/docs检查及前端25测试/type/lint/format/build通过，独立复核修复非空失败answer仍显示timeout的P2后无剩余P1/P2。正常完整commit钩子、push/deploy及一次原条件真实验收待完成。原21HTTP账本和四轮未结预占保持，不清账或反复付费试错。没有新增依赖或runtime。

功能提交c9e1d7d126b2b13d0a5afa46055ce7aec5602e12的正常project-check与完整project-test钩子均Passed，普通push后远端完整SHA一致。api/web/supplier均Active/Online且Details关联精确SHA，部署分别085eab95-2029-448b-bfde-f5141da75dd6、f325cb24-70af-4d10-8b67-d4afc61a3122、0393b92c-7edc-4d3d-9a02-d7cf50735690；api日志CLI2.1.286/bootstrap166/health200，原持久卷及非root启动不变。公网health200、DeepSeek available。刷新旧非空失败answer后，新timeout说明实际可见，原条件保留。

付费前云端同一个真实SDK离线探针证实forward thinking_present=true/type disabled、output_config省略、2048max_tokens/2013bytes/1工具、guard无错误；0真实上游HTTP/数据API。云端原账本21HTTP/8.971738CNY及原PG计数保持，未清预算。随后只重跑一次用户原10月7–8日请求，run20804855-a69b-4f94-89ef-ef75eee052f7从04:41:50.885至04:43:33.238UTC（约102秒）仍failed/timeout/upstream_timeout。天气、景点4次、酒店共6成功工具；前3HTTP输出130/160/171tokens，最后第4HTTP超过90秒。明确配置修复已落实，但未证明彻底解决云端等待；尚无该HTTP收到的字节/帧进度记录，不能断言供应商排队、网络慢流或终态缺失中的某一项。没有草稿、正式确认或预订。

本次模型新增4HTTP/2.187588CNY保守占用，云端累计25HTTP/11.159326CNY（含五轮未结预占，非实付账单）；PG geocode1/places13/rakuten4/routes5/weather2。官方[限速与连接保持说明](https://api-docs.deepseek.com/quick_start/rate_limit/)允许推理前发送keep-alive等待，但这不是此run排队的实测证据；[官方状态页](https://status.deepseek.com/)当时显示正常，不能称全站故障。不清账、不新增重复付费探针或再放宽期限。剩余问题是单次上游响应的等待定位与整轮草稿生成，三类数据接线没有缺key证据。恢复先读当前失败报告；若继续修复，应先补最小脱敏传输阶段/字节/终态进度证据，再决定一次有依据的验收，不能盲目重发。此次仅文档续记复用同源码正常完整回归，保留project-check、跳过重复project-test；push后仅核对部署，不再次付费。

## TRAVEL_PROFILE=human（人工手测档）

`TRAVEL_PROFILE=human` 供人工手动测试：工具80次/模型60轮/整轮900秒（worker840<process850<run900，upstream120<API_TIMEOUT），外部API次数大于relaxed；default/relaxed/human三档，CI与评测保持default。每日15 CNY授权、预占/结算与Claude USD(0,0)不变。景点/文章证据只按城市适用，不随请求版本失效；酒店与路线证据仍绑定版本。
