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

`TRAVEL_PROFILE=human` 供人工手动测试：工具80次/模型60轮/整轮900秒（worker840<process850<run900，upstream120<API_TIMEOUT），外部API次数大于relaxed；default/relaxed/human三档，CI与评测保持default。每日15 CNY授权、预占/结算与Claude USD(0,0)不变。景点/文章证据只按城市适用，不随请求版本失效；路线与酒店报价证据不再绑定请求版本（见下方 2026-10-05 续），仅看有效期、`invalidated` 与条件逐字段相等。

**上游首字节看门狗与有界重试（HUMAN，2026-10-05）**：run 1da5c298 的第5次模型请求在 `model_req_start` 后120秒内转发子进程无任何 TRACE（未到 `model_req_sent`），说明停滞发生在发送之前（spawn/导入、stdin、DNS/TCP/TLS 之一，未区分）。现转发子进程增加阶段 TRACE：`child_start`(pid、boot_ms)、`child_stdin_read`、`child_connecting`、`child_connected`(DNS+TCP)、`child_tls_done`，并保留 `model_req_sent/first_byte/first_chunk/body_done/child_error`；父进程记 `child_spawned`，并在等待期间读取同一 trace 文件，超时时输出 `child_last_phase`。
HUMAN 新增 Limits：`first_byte_timeout=25`、`upstream_retries=2`——仅当尚无任何响应头时，杀掉子进程并用同一请求体重试（每次重试各自 `reserve`，停滞的预占不退款，计入 `max_attempts`，TRACE 为 `upstream_retry`）；已收到响应头、HTTP 错误状态、未授权工具响应、部分正文都不重试。DEFAULT/RELAXED 均为0（行为不变）。单请求最坏约 2×25+120=170 秒，`API_TIMEOUT_MS` 改按 `upstream_timeout+重试×首字节期限+10` 推导（HUMAN 180秒，DEFAULT 100秒/RELAXED 130秒不变）。这是定位并缓解，不是已证明的根因修复。

**供应商HTTP错误直接显示（2026-10-05）**：guard 记录最近一次非200状态码（仅数字），live 报告携带 `upstream_http_status`，`RuntimeOutcome.reason=upstream_http_<码>`（也进入 `run_finished` TRACE）。RunService 对 live 失败按固定表生成说明并作为本轮回复显示：402「账户余额不足，请充值后重试」、401/403「密钥无效或无权限」、429「请求过于频繁或速率受限」、5xx「服务暂时不可用」、400「请求被拒绝」、其他「上游返回 HTTP n」。只用状态码，不含上游响应正文、头或密钥；error_code 仍为 provider_error，超时与其他失败文案不变；无迁移、无OpenAPI变更、未改 apps/web。

**stdin>64KiB 交接死锁（根因，2026-10-05）**：`run_process` 原先用 `communicate(input=…, timeout=0.2)` 循环，首次超时后改传 `input=None` 续调；在 Python 3.12 下这不会继续写 stdin，超过管道容量（64KiB）的 key+body 永远卡住，子进程停在 `child_start`（Python 3.14 行为正常，所以系统 python 复现不出）。现由独立线程写入并关闭 stdin，`communicate` 只读输出；转发子进程与 SDK worker 共用此路径。

**工具失败原因进入TRACE（2026-10-05）**：`tool_end` 增加 `detail`（仅标签，不含输入值/模型自造字段名/消息正文）：pydantic 失败为 `schema` + 至多6条 `路径:错误类型`（如 `items:too_long`、`items.3.note:string_too_long`）；ServiceError 为 `service:<HTTP码>` + 固定 reason 标签（`revision_stale`、`evidence_missing/stale`、`validator:<固定校验文案>`、`repair_limit`、`tool_call_cap` 等，未标注为 `untagged`）；校验报告为 `report:<状态>`、`counts:v/u/c` 与未通过检查的 `code:status`；校验/暂存调用另附 `repair_round:n`、`max_validations:m`。

**失效证据指引与报价精简（2026-10-05 续）**：`evidence_stale` 的模型可见提示按种类（route/hotel_offer/place/article）给固定补救文案，TRACE 为 `evidence_stale:<种类>`；`地点引用必须是place证据` 另附 `place_ref_kind=<种类>` 与静态提示；`applicable()` 不再要求 route/hotel_offer 的 `request_revision` 相等（预算/兴趣等无关修改不再使其过期，入住/路线条件变化、过期、`invalidated` 仍失效）。
`search_hotel_offers`/`refresh_hotel_offer` 结果先去掉每卡重复字段（stay/request_revision/image_url），仍超8000字按总价由低到高整卡保留并加警告，不截断JSON；`offer_ids` 也接受卡片的 `evidence_id`。
HUMAN 无每日CNY上限（README 已同步）；调用上限、编排与预算代码未改。

**证据有效期与修复轮次（HUMAN，2026-10-05）**：run b5d23210 中 `update_travel_request`（为 `estimate_routes` 设交通）在 `search_hotel_offers` 之后，使请求revision递增，`validator.hotel_cost` 因 `offer.request.revision != request.revision` 连续拒绝（第5轮撞 `repair_limit`）。现 `hotel_cost` 不再比较revision，仍要求 offer_id 一致、入住条件（城市/日期/人数/儿童年龄/房间/币种）逐字段相等、`quoted_at <= now < expires_at`；条件不符与过期为两条固定文案（都提示重新 `search_hotel_offers`），模型可见。新增 Limits：`evidence_ttl_minutes`（酒店报价与路线估算有效期；DEFAULT/RELAXED 15，HUMAN 30，地点24h/文章不变）与 `max_validations`（DEFAULT/RELAXED 4，HUMAN 50，仅 live 数据库工具路径使用；评测单因素变体仍为1）；二者进 boot 行。HUMAN 下 validate_itinerary 描述、系统提示词与 load_skill 文本中的静态修复轮数均随档位渲染为实际值（49；DEFAULT/RELAXED 仍为“3轮”，文本字节不变），不再追加“覆盖前文3轮”的补丁句；评测变体 no_repairs（1）文案不变。保留的revision比较：暂留/确认订单仍要求条件未变（bookings.py），该路径不在本次范围。50轮最坏墙钟：每轮约模型2–5秒+工具毫秒，约250秒，低于worker840/process850/run900秒。

**路段冲突提示与TRACE标签（2026-10-05）**：生产症状为一次 `estimate_routes` 把所有leg都用默认09:00出发，产生 `route_unexpected`×1 与 `route_departure`×3，修复轮次耗尽。规则不变（零容差，出发须在前一项结束与后一项开始之间，每天首项不接路段），只改文字：`estimate_routes` 描述与 `RouteLeg.departure` 说明要求先定各项时间、每段用前一项结束时间出发、调整顺序后重估；`route_departure`/`route_unexpected`/`route_scope` 的校验消息带京都时区的具体时刻和补救动作（check code/status不变）。
TRACE 的校验 `detail` 对 route 冲突附位置标签 `route_departure:conflict@d{天}i{当天第几项}`（从1起）及 `dep= pe= ns=`（出发/前项结束/后项开始，HH:MM），每条≤60字符，只含数字与时刻，不含名称、ID或消息正文；标签存于 `ValidationCheck` 私有属性，不进API，无OpenAPI变更。

## 回复不暴露内部编号（2026-10-05）

提示词新增规则：回复文字不得出现offer_id/evidence_id/draft_id/plan_id或UUID；另在 `services/runs.py` 对最终回答文本（`domain.execution.scrub_internal_ids`）兜底删除带标签编号与36位UUID，不改工具结果和展示卡片。

## 2026-10-08 调查与修复准备

用户本轮要求先理解与规划，不修业务代码；授权创建`batch-2026-10-08-product-V2`并切Railway api/web/supplier分支，要求后续一功能一commit、记录根因/过程/取舍/边界以备面试。完整设计与实时状态见[批次计划](../plans/2026-10-08-product-v2.md)（原 07 规划已迁入）。

| 操作/证据 | 实际结果与限制 |
| --- | --- |
| git fetch/status/remote compare | 原checkout干净，旧分支`batch/2026-10-05-product-v2`与origin为0/0；基线`b1e84bf0fac90b0325e51f67ae3d1d35427a9a96`。 |
| git switch -c / push -u | 创建并推送用户指定的新分支，未改业务文件。 |
| Chrome配置核对 | 首次在另一个Chrome配置中Railway未登录；切到用户指定的个人黄色Chrome后已有项目权限。没有操作账号权限或请求密码。 |
| Railway三项变更预览 | production的api/web/supplier各只有一项Branch，从旧分支切到新分支；Deploy Changes已应用，选择值新分支且待应用列表消失。 |
| 既有部署与健康配置 | 三服务既有基线部署成功；api健康检查/health，supplier为/openapi.json。分支变更没有业务差异，不能把配置切换当Bug修复上线。 |
| 发布门禁调查 | 三服务auto deploy开启、Wait for CI为false；本轮只切分支，未改其他开关。后续业务push前须完成相关本地Chrome与自动验证；仅开启Wait for CI不能替代体验验收。 |
| 普通uv check | 全局exclude-newer为2026-10-01，与锁定要求python-dotenv>=1.2.4发布时间冲突，依赖解析失败。未改全局配置、依赖或锁文件。 |
| uv run --no-sync python scripts/dev.py check | 使用已装虚拟环境：Ruff检查/248文件格式、win32/linux/darwin strict mypy、3项分层契约、10份文档地图均通过。静态通过不等同离线/PG/真实修复验收。 |
| 独立只读规划审查 | 核对关键源码和19项覆盖，修正R4依赖R3、CI与浏览器验收分离、酒店位置字段尚缺、用户URL/无报价选择保留、worktree同分支不能重复检出。未改业务实现。 |

源码已确认的类别原因：单run/组件内sent导致前端旧回复与用户消息无法完整恢复；酒店以报价套餐截取，未按不同酒店去重；reserveUrl优先使浏览入口直达预订；Markdown缺table分支。`plan_exists`只证明该服务会拒绝同会话已有正式版本后的initial草稿，原第23步仍缺绑定错误证据；B13隐藏默认值候选原因仍需回归。

后续每项在本节下记录：Bug ID/输入前提/实际与期望、版本与run证据、根因假设和排除、首次失败测试、选定与拒绝方案、实现文件、回归命令/结果、commit与部署、回退/剩余限制。原失败保留；不上传token、密钥、原始私人对话或无关账号截图。

## 2026-10-08 D6–D8 决定落盘

当前恢复入口为[批次计划](../plans/2026-10-08-product-v2.md)，任务状态仅在那里维护。

- 开始前 `git status --short --branch`：指定分支、工作区干净；本地 HEAD 与本地 origin 跟踪引用均 `8d99da0`（VERIFIED，不代表新查询远端）。
- 用户明确 D6：两个预算原值均保存，validator 计算 conflict/warning/无法判断，不另存冲突标志；D7：B08 本批部分修复；D8：当前 checkout 开发、每项开工前检查干净。同步计划 §2/§3.5/§4/§6，并更正 §7、P-01 假设 4。
- `python3 scripts/check_docs.py`：退出 0，10 份入口及仓库链接通过。`git diff --check`：退出 0。文档自审核对用户决定逐项一致；本步未改业务代码、未操作 Railway、未调用模型或旅行数据 API。

## 2026-10-08 T0.1 uv 配置复现与修复

- 普通 `uv run python scripts/dev.py check`：先输出全局日期新增导致重新解析，随后 PyPI DNS 失败，退出 2；`uv lock --check --offline` 同样重新解析，因缓存缺失返回 1。全局配置实际为相对 `7 days`，不是计划中固定日期字面量。
- 先红 `uv run --no-sync python -m pytest tests/test_dependency_resolution.py -q`：1 failed；临时用户策略 2000-01-01 使锁定 alembic 不可用。
- 失败尝试：项目 `exclude-newer=false` 被 uv 0.11.7 拒绝（TOML Helper parse error）；改固定 `2026-10-08T00:00:00Z`。`uv lock --offline` 因 registry 缓存不足失败；获准联网 `uv lock` 退出 0、88 packages，diff 仅新增 options 日期，版本与制品均保持不变。
- 绿色 `uv run python -m pytest tests/test_dependency_resolution.py -q`：1 passed / 0.08s。普通 `uv run python scripts/dev.py check`：退出 0，249 文件格式与三平台 strict，3 契约、10 文档地图通过。
- 完整 `uv run python scripts/dev.py test`：沙箱 18 failed、788 passed、1 skipped、1 live deselected、195 errors / 15.65s。失败涉及 live_application（6）、persona_judge（6）、sdk_cli_offline（2）、sdk_lifecycle（1）、tracing（1）、travel_sdk_offline（2）；代表根因为本地 HTTPServer.bind PermissionError，非付费上游调用。获准启动本地替身后同一完整命令：806 passed、1 skipped、1 live deselected、195 PG setup errors / 45.41s。原 18 项全部转绿，PG 错误仍未解决。私有原输出在 ignored `.cache/t01-check.log`、`.cache/t01-test.log`、`.cache/t01-test-unrestricted.log`，不提交长日志。
- 环境：Docker CLI 在 Docker.app 内，PATH 未包含；daemon 连接失败（/var/run/docker.sock 缺失），context 只有 default；本地 .env 存在、数据库配置有效且仅指向 localhost，连接不可用。未输出配置值或凭据；已异步告知用户启动现有 Docker Desktop。
- 自审：固定策略覆盖用户配置；锁文件无升级；测试真实 CLI、不改 lock。独立只读审查：Windows 注入 APPDATA（原 P2）已修复并复核通过，macOS 专项 1 passed；Windows 行为依据官方配置目录文档为 REASONED，非在 Windows 实机运行。

## 2026-10-08 T0.2 完整基线

- `3771886` 已普通 push；`git ls-remote origin refs/heads/batch-2026-10-08-product-V2` SHA 为 `37718867526cebbcfe4514f3650db2225d9ac7ee`，工作区干净后开始 T0.2。
- 用户启动 Docker 后，临时 PATH 指向已安装 Docker.app CLI，运行原 `uv run python scripts/dev.py db-up`：Docker 29.7.2，postgres:17 拉取完成，项目本地容器 Healthy，退出 0；原数据卷不清理。
- 普通 `uv run python scripts/dev.py check`：退出 0，249 文件格式/三平台 strict、3 分层契约、10 文档地图。
- `uv run python scripts/dev.py web-check`：typecheck/lint 退出 0；test 25 passed / 0 failed / 0 skipped；build 因沙箱无法下载 Noto Sans SC/Geist 失败。获准联网单独 `pnpm --dir apps/web run build` 退出 0，5 条路由构建完成，未发布。
- PG Healthy 后完整 `uv run python scripts/dev.py test`：994 passed、7 failed、1 skipped、1 live deselected / 237.45s。`uv run python -m pytest -m integration -q -ra`：180 passed、2 failed、821 deselected / 170.96s。两套结果重叠；未标 integration 的 evaluation_variants 五项不在 marker 专项内。两套均只用本机模拟模型/HTTP 与随机隔离 PG 库，无真实上游 HTTP/金额。私有日志 ignored `.cache/t02-check.log`、`t02-web.log`、`t02-build.log`、`t02-test.log`、`t02-pg.log`。
- 7 项失败名完整列在计划 P-05；4 项有 `blocked/auto_compaction_capability, 0 attempts`，3 项缺压缩事件/summary请求。当前 `claude --version`=2.1.294；importlib metadata SDK=0.2.163；SDK bundled `--version`=2.1.286。旧 2.1.114 本机不存在；未更新/回退用户 CLI、未放宽门禁/断言。
- 独立只读审查：T0.2 是基线采集，可按明文退出条件记录完成，但全量并未通过；环境问题关闭为 P-04，SDK 能力缺口记 P-05，R6 必须解决。默认 offline→FixtureRuntime 不经过上述门禁，T0.4 ADR 与 T0.5 保存复核可继续。

## 2026-10-08 T0.4 ADR 契约

- 开工前工作区干净，分支与远端 `308c8cb` 一致。仅写 ADR-014/015 与设计入口链接，没有实现接口、字段或迁移。
- 现有 Pydantic 模型特征实验：分别把 lodging_budget / field_sources 交给 TravelRequest.model_validate，均返回 extra_forbidden；ValidationCheck(status=unknown, code=lodging_budget_range_warning) 序列化往返通过。没有输出 token 或供应商内容。
- 自审：历史不新增表；预算细节列是 T3.3 的增量迁移，保留旧 conditions 以兼容旧严格模型；warning 使用既有 unknown/partial，不引入第四状态。
- 独立只读审查指出 explicit_fields 未明确参与幂等区分、来源 no-op 后缓存回执可能过时（P2）；已明确规范化 explicit_fields + 来源入口参与 operation identity，缓存命中重读来源，并列出对应 PG 测试。outbox 补身份/session 绑定和 401 失效。
- `python3 scripts/check_docs.py`：退出 0，10 份入口；`git diff --check` 退出 0。独立复核 P2 关闭、无新增发现。纯文档提交复用 T0.2 同代码完整基线（已知 7 失败保留），仅 SKIP=project-test 避免重复；project-check 仍执行。

## 2026-10-08 T0.5 保存与身份复核

- `f2a6a61` 普通 push，新查询远端 SHA 完整一致，开工前 git status 干净；`uv run python scripts/dev.py check` 退出0、249文件/3契约/10文档入口。提交输出没有显示钩子执行，以上为显式命令证据，不声称 git 钩子实际运行。
- 首次 `uv run python scripts/bootstrap_demo.py` 退出1，ModuleNotFoundError: backend；没有进入迁移。改项目容器使用的模块入口 `uv run python -m scripts.bootstrap_demo` 退出0，166样例导入（snapshot），不初始化真实用户或订单。
- `DEMO_MODE=true uv run python -m backend.server` 默认 offline、仅127.0.0.1:8000；`pnpm --dir apps/web run start` 127.0.0.1:3000。Next 提示 standalone 应使用 node .next/standalone/server.js，当前 start 实际可用，未改部署入口。私有过程日志 ignored `.cache/t05-api.log`、`t05-web.log`。
- 用户 Chrome 的 localhost 初始缓存已遭401，应用显示身份失效；该未知旧缓存不作为根因证据。新建两条合成会话用于受控复核，固定示例条件，0真实模型/供应商调用，0订单。
- 案例A：点击生成/确认 POST200，正式V1；刷新→我的行程仍V1。针对已核对的新建会话临时将用户有效期改为过去（原时间保存在ignored cache），刷新 GET request401/“身份已失效”；再刷新“还没有确认的行程”。只读SQL在故障前后：plans.current_version=1、plan_versions行数1、plan_drafts确认行1；payload哈希相同 `b30de0e9e4df749639be1de7cf34b81248883e116334aca56cdb90bb1827165a`。用户原有效期已恢复，清理后的浏览器身份未伪造恢复。
- 案例B：第二个合成草稿临时过期，点击确认 POST409/“草稿已过期，请重新生成”，卡片仍待确认；转我的行程空，SQL current_version=0/version_rows=0/confirmed_version=null，符合确未确认。草稿原有效期已恢复。仅改目标会话/草稿，连接工具强制URL host为loopback，不记录token/行程正文。
- `uv run python -m pytest tests/integration/test_plans.py -q`：10 passed/2.08s；`pnpm --dir apps/web run test`：25 passed/0 failed/0 skipped。前者真实随机PG库，后者含恢复helper测试，不能当成实际hook竞争已验证。未改代码，复用T0.2同代码完整基线，7项SDK失败保留。
- 脱敏摘要与4张本地页面截图在 docs/evidence/product-v2；原线上事件和确定性迟到hydrate仍未验证。P-01保持doing，T0.5只完成调查。
- 独立只读审查：4截图/摘要/PG边界与C6一致，未见秘密或过度结论；T0.5可关闭为调查完成，P-01仍doing。check_docs 10入口、diff check通过；文档提交未改业务代码，完整同代码基线不重复运行。

## 2026-10-08 T1.1 旅行与轮次历史接口

- `2dad10d` push远端完整SHA一致，git status干净后开工；ADR-014已接受。新增API与具体SQL/只读用例位于各现有层，不改表/迁移，不接第二运行时。
- 先红 `uv run python -m pytest tests/integration/test_history.py -q`：12 failed/1.00s，新增路径404（缺接口）；实现后相同命令12 passed/0.99s。测试日志可能含自动生成的本地临时测试令牌，仅存ignored `.cache/t11-red.log`，不上传原日志。
- 新SQL带user_id/session_id归属；Session创建时间/UUID与Run创建时间/UUID keyset，取limit+1；分页期间新建旅行/消息不移旧边界；无条件值null、只有实际当前正式版本存在才返回plan metadata。每轮presentation复用现有4项读取，不生成/确认/调模型。
- 扩展游标结构/版本/日期时区/UUID/limit、数据库失败非空列表等边界后，历史+sessions+runs+plans+契约专项：44 passed/28.60s（首次扩展版）。
- 初次dev check发现测试UUID导入未用；下一次mypy指出__table__.insert类型6项，改现有sqlalchemy.insert(Model)，不加ignore。dev check随后252文件Ruff/格式、三平台strict、3契约、10文档入口通过。
- 用 `uv run python -m scripts.export_web_schema` + `pnpm --dir apps/web run generate` 生成契约和类型，不手改生成文件；web-check typecheck/lint/test25 passed/build5路由全部退出0。
- 独立只读审查发现测试固定STAMP但新session用机器now（P2）；改明确STAMP+4h，runs页间新增也用固定delta。复核P2关闭，业务/归属/兼容/复用无其他发现；修正后专项与完整测试结果待补。
- 时间修正后的 `pytest tests/integration/test_history.py -q`：19 passed/16.29s；最终 dev check 退出0，252文件三平台strict/格式/3契约/10文档。完整同增量test仍运行，不能提前报全绿。
- 完整 `uv run python scripts/dev.py test`：1013 passed/7 failed/1 skipped/1 live deselected，253.10s；7失败名称与T0.2/P-05逐项一致，没有新增失败。完整运行期间最后仅修测试时间固定，故另用修正后的19专项覆盖；业务实现/生成契约未变。不跳过失败或放宽断言。


## 2026-10-08 T1.2 多轮对话恢复

- 开工前 `d180541`、git status 干净；只读列表作为历史来源，不把对话正文写入浏览器持久历史、不提交恢复消息。确认后清除本地 run_id 的旧路径仍能从 session 列表找到轮次。
- 首红：T0.5 Chrome 先确认再刷新，正式 V1 可读但对话无回复；新前端 recovery 测试首跑为25 passed/1 suite failed（模块缺失，不冒称三项行为断言失败）。接入API/helper后28 passed；新增刷新第一页保留早页回归后29 passed。
- 独立审查P2：直接替换历史页会抹掉已翻页及本标签实时全文；首次改merge后，复核还发现最新 GET 同sequence被900秒缓存淘汰后的简短说明覆盖。新增最新 GET 回归在返回incoming的旧行为下29 passed/1 failed，实际差异为answer全文→固定说明；修复后30 passed/0 failed/0 skipped（148.64ms）。合并按run_id/sequence，保留同序列已持有全文，接受服务端状态/卡片更新；固定持久化说明可升级为内存全文。没有改变服务端实时回复保留策略。
- `pnpm --dir apps/web run typecheck`、`lint` 退出0；最终 `test` 30 passed；`build` 退出0、5路由。第一次 standalone 使用错误的apps/web/server.js路径，退出1找不到模块；按实际生成目录改 `.next/standalone/server.js`，复制ignored static后本地启动成功。修复脚本首次调用无python命令，未写文件，改项目 `uv run python` 后执行；没有把随后检查通过误算为脚本成功。
- Chrome实际hook/路由：第二个T0.5合成会话，过期草稿轮次保留；新增草稿确认正式V1，再加普通查询，共3轮。确认后刷新→3轮消息/答案可读，进入我的行程V1→返回对话3轮仍可读。初始恢复中一度出现空欢迎，增加restoring/error保护后重新构建复测。
- 本地PG只读复核前后均run_rows=3/current_version=1/version_rows=1/confirmed_drafts=1，正式内容SHA256相同。恢复只GET，不产生新轮次/确认/供应商调用。截图及脱敏摘要见docs/evidence/product-v2/t12-*。分页接口与helper已测试；浏览器此次仅3轮，没有验证超过20轮按钮；实时原回复跨重启无法完整恢复为既有限制（本轮合成PG验证如下，不冒称真实模型实测）；卡片归属待T1.4。
- 补充保留边界characterization：`pytest tests/integration/test_runs.py tests/integration/test_history.py -q` 为28 passed/16.79s。只在隔离PG直接创建合成已完成deepseek轮次，填本地RunService.live_answers：GET全文、history固定说明；901秒过期与新RunService都返回固定说明且sequence=3，tasks空，0模型调用。这核实既有服务保留边界，首次即通过，不声称它是业务修复的首红。新增测试晚于完整测试收集，专项覆盖最终测试版本；再次dev check 252文件/三平台strict/3契约/10入口退出0。
- 完整 `uv run python scripts/dev.py test`：1013 passed/7 failed/1 skipped/1 live deselected，256.29s；失败名与P-05同7项一致。新增保留边界测试晚于收集，由最终PG28项专项覆盖，不冒称本次全量包含它。自审与独立复核两轮P2关闭，新characterization/脱敏证据审查无发现；未部署、未调用真实模型或供应商。


## 2026-10-08 T1.3 同身份旅行切换与临时outbox

- `d0f0222` push后新查远端SHA一致、git status干净。按ADR-014复用POST /sessions及旅行摘要分页，列表状态不落浏览器历史副本；选择较旧当前session时逐页有界查询到其摘要，正式plan_id来自服务端。新建不demo login。
- 首红 `pnpm --dir apps/web run test`：30 passed/1 suite failed（缺新API/storage模块）；实现后35 passed。随后定位跨标签归属问题，补旧标签A失败而shared local已有B测试，首次35 passed/1 failed；按owner精确清后首次仍失败于多余pending_message:undefined，改restore仅有合法pending才附字段，未修改行为断言，随后36 passed；旧API404语义回归加入后最终37 passed/0 failed/0 skipped（158.58ms）。
- 3项独立P2：401错误清了当前shared local owner、切换加载误显空欢迎、savedOnly旧API404误显“未确认”。按原失败token清标签outbox且只删除相同local owner；changeTrip restoring+generation finally；SavedTrip historyError禁止empty及404明确版本提示。两次独立复核关闭，未删断言/跳过检查。
- 保存条件同步当前旅行列表city/date时typecheck及build发现optional不兼容nullable；归一为null后typecheck/lint/build5路由均退出0，最新test37 passed。模型偏好移到sessionStorage并移除旧local键；Identity local只token/session，未响应消息以token/session绑定标签outbox；已接受/401清理，切换保留原旅行outbox、不自动重发，旧pending一次迁移。
- Chrome真实页面：旧京都3轮+正式V1；点击新建旅行1次，编辑第二次为札幌、发1轮离线问题，切回京都3轮及V1仍可读，切回札幌仅1轮。当前免费Fixture仍返回京都样本，不能当札幌真实供应商验收。PG只读：same_user=true，京都revision1/run_rows3/current_version1/version_rows1，payloadSHA256保持t12一致；札幌revision1/run_rows1/无正式版本。本地API新runner日志POST demo/login=0、POST sessions=1。
- 临时ignored本地wrapper只绑定127.0.0.1、验证PG host为loopback、live=false：目标request延迟6秒，Chrome目标札幌已选中、仅恢复status、没有空欢迎/旧对话；GET sessions/runs模拟404，/plans显示版本不支持且没有“还没有确认”。已删除模式标记、停止wrapper、恢复项目默认离线API及最终web构建，重新读取京都V1；0真实模型/供应商/订单，未操作Railway。
- 只读PG探针首次忘传database_url(configuration())，TypeError发生在连接前；修正后实际查询成功，不输出DSN/token/userUUID/行程正文。脱敏5截图及JSON在docs/evidence/product-v2/t13-*。outbox和local内容由真实helper调用测试，未读取浏览器隐藏storage；浏览器验收与存储helper证据分开。
- `uv run python scripts/dev.py check`：252文件Ruff/格式、三平台strict/3契约/10入口退出0；完整 `dev test` 1014 passed/同P-05的7 failed/1 skipped/1 live deselected（256.41s），包含T1.2新保留characterization；本任务Python源码无改。最新front type/lint/test37/build5路由均通过，独立审查最新同步列表/模型存储修改无发现。


## 2026-10-08 T1.4 卡片与事件归属

- `1786c37` push后远端完整SHA一致，开工git status干净。原京都已过期V1尝试离线修改返回酒店/路线证据失效，未生成新草稿；改新合成旅行、新鲜默认京都条件→生成草稿→普通室内查询。真实DOM两个reply：生成轮无draft badge，普通查询有旧draft badge，B17已复现。当时截图存ignored，现已审核并复制至docs/evidence/product-v2/t14-red-inherited-draft.png；视口截图仅部分上下文，两轮完整归属由真实DOM记录证明。

- 卡片来源helper首跑37 passed/1 suite failed（新模块缺失）；实现后40 passed。SSE错误原genericError导致401断言40 passed/1 failed，保留ApiError status后41 passed。审查P2历史酒店清缓存遮蔽持久引用：首次缺export suite失败，先抽原选择逻辑重新红41 passed/1 failed（undefined vs hotel_comparison）；cached存在且origin匹配才用后42 passed/163.25ms。typecheck/lint退出0；最终build5路由退出0。
- Chrome同场景修后生成轮1引用、查询轮0卡；PG该查询presentations为空，排除真实新草稿。实际hook probe：ignored本地wrapper正常鉴权后SSE先注入foreign session/run seq999，本轮六步完整、日志0次foreign-draft读。cursor过滤helper只是独立测试，不称完整hook竞态。
- 移除后台hydrate/读列表的identity持久化，仅内存持有plan_id，避免旧captured identity改共享选择。首次45秒延迟超过Next proxy timeout、500/socket hang up，不算成功；改18秒，另建新鲜合成草稿确认V1，再延迟GET /plan-drafts一次；旧标签恢复中另一标签选择札幌，旧标签后来显示已确认V1，另一标签刷新仍札幌。一次Chrome locator等待超时但诊断enabled，随后新AX确认成功；没有改等待断言假通过。
- PG只读新合成旅行4轮/普通query0presentation/current_version1；原京都version_rows1/current_version1/payload SHA256与t12一致。只有新合成旅行显式确认1次，没有重确认原旅行。截图5张与脱敏JSON见t14-*；Fixture仍京都样本，不算真实札幌数据。停止wrapper/删除flags，默认API恢复、live=false，0付费调用。
- `uv run python scripts/dev.py check`：252文件Ruff/格式、三平台strict、3契约/10入口退出0。完整 `dev test` 1014 passed/原7 failed/1 skipped/1 live deselected，257.51s，失败名与P-05一致；本任务Python源码未改。独立只读审查酒店缓存P2修复、复核后台storage变动无发现，全部实测证据后再提交。

## 2026-10-08 T1.5 全部正式行程列表

- `48cb062`push、远端完整SHA一致；git status干净后开工。Chrome当前札幌未确认进入/plans显示“还没有确认的行程”、无其他旅行入口，但PG已有原京都V1及新合成京都V1。先红真实UI截图t15-red-empty.png（当时ignored）。新列表状态回归首次42 passed/1 suite failed（缺helper）；计划内复用T1.1摘要，不新增接口/字段/表。

- 列表helper实现后44 passed；独立审查指出重试action清error但只有busy为true，新增回归44 passed/1 failed（empty vs loading）。修列表phase纳入busy后最终45 passed/168.13ms，typecheck/lint/build5路由退出0。savedOnly只读摘要和canonical正式计划，不因无关bookings/request失败隐藏计划；失败/404重读重新查摘要，成功清historyError。
- Chrome新页面当前札幌未确认仍列两份京都V1；分别选择、两不同GET /plans/{id}200，刷新保持选中。这里只读，不操作export/锁定/确认。临时wrapper仅127.0.0.1/校验PG loopback/live=false：GET sessions503→错误无空；6秒列表重试→status无空→列表/V1恢复；GET plans503→两份摘要保留+详情错误；旧API404→明确不支持、重读成功清提示；注入401→身份失效，再刷新→身份未保留，均非无行程。
- 401是注入API状态的UI边界，不冒称本轮真实expiry；T0.5曾真实本地令牌到期PG验证。关闭探针后，在仍持有有效合成身份的旧标签显式选择原京都，恢复本地测试入口，没有绕过鉴权；停wrapper，默认API恢复。PG再次只读两份V1/version_rows各1，原hash同t12；wrapper期间API0POST/PATCH/0付费调用。脱敏9截图/JSON见t15-*，截图视口不足时用真实DOM和API路径证据区分两同名合成旅行。超过20旅行未做浏览器大样本，PG分页/helper独立证据。
- `uv run python scripts/dev.py check`：252文件、三平台strict、3契约/10入口退出0。完整 `dev test` 1014 passed/同P-05的7 failed/1 skipped/1 live deselected，256.98s；本任务Python源码未改。读取进程时长初次sandbox ps拒绝，按只读pid/etime/comm获准后确认运行3m55s，未读参数/环境/终止无关进程。

## 2026-10-08 T2.1 业务结果与运行状态分离

- `b9121a5`push/远端新查SHA一致，git status干净后开工；先在ADR014确定可空业务结果/事件来源/确认投影，无新表/迁移。独立契约P2：旧presentation不能证明最后stage或同run来源；放弃旧成功回填，保守返回null；保留此失败设计尝试。
- 先红真实隔离PG `pytest tests/integration/test_run_business_result.py -q`：3 failed，runtime completed且回复“已通过，已保存”，但business_result缺失；两成功前提由真实PlanService暂存（partial/conflict），合成runtime不调用真实模型。

- 工具元数据使用既有execute_observed/事件；真实PG第一组三失败→3 passed/0.91s。新增最后stage、旧成功缺元数据、其他session引用、确认后history等边界。版本类型测试发现TypeAdapter把True转1：2 passed/1 failed→strict int/正数约束→3 passed/0.28s。trace单测确认私有事件保留元数据、公共追踪不含业务ID。
- 邻近测试原取消==GET断言实际66 passed/1 failed/20.37s，因cancel原view不含新增结果；改recorded_view复用GET/重复提交/取消，原断言未改，68 passed/19.37s。修复时停止旧全量进程退出130，未完成不算通过。随后完整1023 passed/9 failed/1 skipped/1 deselected/255.91s，其中7项原SDK、2项workbench旧快照预期；新契约要求confirm后仅business_result从draft_staged到confirmed，因此保持全对象比较且所有原runtime/presentation/event字段不变，明确新字段预期，不隐藏或忽略差异。
- 独立审查P2：最后stage开始后结果未落库，被误判answer_only或前次结果。真实PG先提交合成草稿、模拟tool_started/进程恢复，2 failed/8 deselected/0.88s；投影读取最后开始/结束事件，最后开始则unknown/null。中断+workbench17 passed/3.03s；最终邻近77 passed/21.27s。审查复核关闭P2，无新的可行动问题，未把合成中断冒称实际SDK崩溃。
- Chrome原合成京都正式V1再次生成：默认离线真实工具plan_exists，显示失败/草稿未生成；新第四旅行同身份保存合成条件、生成partial→尚未保存→显式确认1次→已确认V1；刷新恢复，另一轮普通查询仅回复完成。旧stage成功无元数据明确业务状态未知。0真实模型/供应商，conflict与runtime假称保存由真实隔离PG+受控runtime验证，不冒称Chrome/真实SDK。
- 本地PG只读核对新旅行2轮，confirmed与answer_only分别归属本轮、新正式V1/version_rows1；旧旅行最新stage_failed/conflict/plan_exists、原V1/version_rows1/hash同t12。API日志仅1次confirm POST。证据`t21-business-result.json`及5张`t21-*.png`（docs/evidence/，合成数据）；初截图只显示上方旧轮次，读图后滚动至最新失败/普通查询重新保存，未冒称旧截图证明新状态。临时探针第一次未给PYTHONPATH导致ModuleNotFoundError，再用PYTHONPATH=.成功；只查loopbackPG，无生产访问。
- web首红45 passed/1 suite failed（helper缺失）→47 passed；最终typecheck/lint/test47 passed/176.99ms，build5路由退出0。dev check254文件/三平台strict/3契约/10入口通过；修后完整回归仍在运行，最终结果随后追加。
- 最后完整 `uv run python scripts/dev.py test`：1027 passed/7 failed/1 skipped/1 live deselected，256.32s；失败清单逐项同P-05的原SDK压缩7项，无新失败。7项不是通过、不跳过/改断言掩盖，R6不得发布。最后生成OpenAPI/TS成功、git diff --check通过；独立只读记录审查无发现，截图/JSON未见凭据或真实用户信息。

## 2026-10-08 T2.2 失败原因与下一步

- 开工前`git status --short`空，HEAD/远端均`0b5d000914f1c3e4177512ee2c35497da8992d89`。T2.1 Chrome/PG已经真实证明plan_exists，但旧UI出现“局部patch”、缺本轮操作引导（截图t21-stage-failed）。复用ADR014既有safe reason，无新字段/API/表/依赖。
- 前端新增实际helper调用测试：`pnpm --dir apps/web run test`首次47 passed/1 suite failed（stageGuidance export不存在，186.19ms），实现后50 passed/169.89ms；覆盖已有正式行程、无效修改、修复次数耗尽、安全fallback、普通/旧回复不猜原因，输入含假称保存与内部参数但说明只用安全枚举。Conversation stage_failed只呈现固定说明，模型原answer仍由后端保留、UI不以其推断或重复原内部patch文案。
- 最新plan_exists提供两个动作；修改复用同session switchTrip读回canonical正式计划，成功后打开右侧/预填composer，0自动消息、PATCH或确认；新建复用既有同身份newTrip并清输入。历史失败只给说明不渲染操作按钮；connect不再把stage_failed模型answer放在全局error banner。代码自审后交独立只读复核，项目type/lint/build/check/full正在运行，Chrome行为证据待补。
- Chrome实际plan_exists说明含修改/新建选项，原内部patch回复不展示；修改点击复用同session读取，正式V1及预填“演示：修改第二天下午”可见。该阶段日志0POST/0PATCH、2次canonical GET200；未点击发送或确认。新建引导显式创建1个same-owner空session，0重新登录/消息/确认/PATCH，composer清空；旧V1保留。
- 然后返回原京都旅行，再显式发送1次普通离线query以验证旧失败成为历史：说明保留，“修改现有行程/新建另一趟旅行”两个DOM按钮count均0；不是引导自动发送。只读PG新空session0run/0formal，原V1/version_rows1/hash同t12。脱敏JSON分阶段记录实际计数（最终1session/1显式message/0confirm/0PATCH/0login），4张截图已逐张读图；0真实模型/供应商。截图仍有正式引用过期措辞/新旅行离线门槛，分别待T2.4/T3.7，不冒称本任务修复。
- `dev check`254文件三平台strict/3契约/10入口，webtype/lint/build5路由通过；独立只读实现审查无发现。完整test运行中，最终结果随后追加。
- 最后完整 `uv run python scripts/dev.py test`：1027 passed/7 failed/1 skipped/1 live deselected，255.69s；逐项仍为P-05原SDK压缩7项，无新增失败，无改断言/跳过。`git diff --check`与`uv run python scripts/check_docs.py`通过。
- 独立记录审查仅P3措辞补充：新建后查询是在返回原京都旅行后显式发送；已补明，避免与新session0run证据混淆。安全/过度结论无发现。

## 2026-10-08 T2.3 步骤错误类别

- 开工前checkout干净，HEAD/远端均`ebe54b669461065373672c1b0910c9a1813ee047`。读取既有activityEntries已存错误码但RunSteps只输出符号+名；新增八类/未知值测试首次50 passed/1 suite failed（missing module，190.16ms）→59 passed/180.84ms。无需接口/字段/依赖；生成AppEvent.code联合类型约束Record完整映射，Object.hasOwn排除prototype keys，unknown/null不回显参数。
- 独立审查P3：unavailable说“保存结果仍可读取”过度承诺。先改变读取边界期望，真实58 passed/1 failed/187.39ms，改为稍后重试读取且不代表数据丢失；不是改断言掩盖失败，是明确新说明避免混同存在与可用性。最后web/type/lint/build重新运行；Python源码未改，完整离线回归已运行中。
- Chrome仍保留T2.2旧bundle，实际在原合成京都V1显式生成：真实stage plan_exists/code conflict；展开5步，前4步成功，最后只“✗ 生成行程草稿”。旧状态实际DOM与截图`t23-red-no-category.png`，0真实供应商/模型调用。将重启新前端，再显式运行同离线失败路径验证分类，不改正式V1或重确认。
- 本次恢复验收发现终态run刷新后events未读，步骤无入口：Chrome先红`getByRole(button,name=查看执行步骤).count()`期望1/实际0，抛出明确断言错误。只补当前最新run的显式只读入口，沿现有reconnect/SSE、generation与归属过滤；不重新发送消息。记录P-17为计划外；全部历史轮次工具详情不在本任务范围。纯前端变动最后test/type/lint/build再运行，Python完整进程继续，其源码未变。
- 刷新后只读入口actual1（绿），同一原run GET SSE读回5步：前4步成功，stage失败行新增“状态冲突：条件存在冲突或行程版本已变化…”；运行前后请求计数完全相同（只有最初显式1消息，0确认/PATCH/登录/新session），未再生成一轮，更新原验收做法为同轮持久事件读回。
- 独立审查新入口P2：connect最终GET直接覆盖run/history，若标签全文已恢复但服务端缓存退化，会损失已读全文。有限loopback middleware仅某个合成run认证成功的GET响应：先返回标为合成的全文，后返回固定保留说明，run_id/sequence/metadata不改；Chrome点击步骤后全文退化，实际expectedFullKept=true/actual=false抛错，截图t23-red-answer-degraded。复用T1.2 mergeRun修run/history两处最终合并；不扩保留、不重跑SDK或记录真实模型回答。
- 该探针不是实际900秒/真实SDK验收，实际缓存有效期已有T1.2 PG证据。本任务Chrome验证的是响应退化时的读回分支。前端测试日志曾因服务日志路径复用被覆盖，已独立重跑恢复实际输出；最终测试统一保存`.cache/t23-web-final-tests.log`，不以覆盖文件冒称原始输出。

- 最后Chrome全文保护绿expectedFullKept=true/actual=true；步骤面板1、summary“执行了2步”。最初将summary误用button角色导致count0，按实际DOM纠正选择器并核对，JSON保存真实结果。探针0写请求、PG原answer/sequence7未改；已CtrlC停止探针、删除标志并恢复默认DEMO_MODE API，Chrome重载读取真实离线答复。原京都正式V1仍1行/哈希不变；八类映射为单测，Chrome实际错误类别只验证conflict。所有截图已人工查看，无凭据/真实用户私聊。
- 最终 `pnpm --dir apps/web run test` 59 passed/190.75ms；`run typecheck`/`run lint`/`run build`退出0（5路由）。`uv run python scripts/dev.py check`254文件/三平台strict/3分层契约/10文档入口退出0。`uv run python scripts/dev.py test`在最后源码修复后运行，1027 passed/7 failed/1 skipped/1 live deselected，256.87s；7项逐一同P-05基线SDK压缩，无新增失败。先前257.21s回归是在P-18前，不作为最终结果。最终独立只读源码与记录审查均无新发现；commit待完成。
- 实现commit `440afbea8ffa4481b36c1c2b4ce3e1925a3a078c`已push，`git ls-remote`与本地HEAD完全一致；最终diff check/check_docs通过。P-15–18验证与SHA已回写计划，STAR沉淀于同一批次案例。

## 2026-10-08 T2.4 正式版本与引用更新

- 开工`git status --short`空，HEAD/远端`317edf8b6929e4d8f3cb4e3bf964476aad6b8541`一致。按需读取设计02/03/05、既有PlanView/content_view/PlanResults与availability测试。根因目前是源码REASONED：共用草稿失效说明；不改后端存储或正式版本。
- `pnpm --dir apps/web run test` 首红54 passed/1 suite failed/199.53ms（既有availability文件增加3用例，helper export尚不存在导致该suite加载失败）；保存实际输出于.cache/t24-red.log。随后复用draft_id/needs_refresh/报价expires_at实现固定区分，不增加状态字段或后端接口。
- 初步web绿62 passed/186.99ms，type/lint/build5路由/check254/3契约/10入口通过。Chrome真实原V1草稿失效提示红count1→新正式保存提示1/错误提示0；住宿展开显示需更新1。只读PG进一步查3个失效到达路线/0失效景点，现有渲染未提示路线，Chrome明确expected3/actual0断言红；补对应route_evidence_id引用说明，不新增helper/元数据。最后前端检查将重跑；完整Python源码未变，当前完整进程继续。
- 最终Chrome路线提示3（由0!=3红→绿），景点提示0，对应PG失效route3/place0；正式V1仍可读，wrong draft notice0/saved notice1/hotel notice1。全程实际默认离线API，未改时钟或响应探针。只读PG仍1版本/V1哈希87e4…25f不变，前后POST/PATCH/DELETE均0。红截图只含版本上下文，错误提示在视口外，以实际AX/DOM计数证实；最终保存截图包含V1/保存提示/路线条目，已人工查看。证据t24-formal-expiry.json。
- 最后前端 `pnpm --dir apps/web run test`62 passed/184.83ms，`run typecheck`/`run lint`/`run build`5路由通过；`uv run python scripts/dev.py check`254文件三平台strict/3契约/10入口退出0。路线修复后全部前端检查重跑；Python源码全程未变，完整离线回归仍在运行。独立只读初次及路线增量审查均无发现。
- 完整 `uv run python scripts/dev.py test` 1027 passed/7 failed/1 skipped/1 live deselected/258.59s；7失败逐项同P-05，未改断言/跳过。Python源码全程未改，进程运行期间只补前端路线提示，其后前端62/type/lint/build/check全部重新通过。`git diff --check`/`scripts/check_docs.py`通过，独立审查两次无发现。
- 实现 `9d3d521f5c4c8af5921e8b4fd121ba4b8555f7ef`提交/push后，远端SHA完全一致；P-19/task证据与STAR已落盘，恢复点为T2.5。

## 2026-10-08 T2.5 确认与读取失败边界

- 开工`git status --short`空，HEAD/远端`cbb3b37ea2e101105239fcd751c465f93a2f2177`。读取confirm/action/refresh与真实PG并发确认测试。先前业务结果与最终读回需保留，确认POST事实与GET可用性分开；普通读取失败不能自动再写。
- 客户端实际confirmPlan流程新增3测试：POST成功回执先于GET503、POST409绝不报成功/不读、GET401保留身份失效处理。首红62 passed/1 suite failed/282.91ms（export未实现）→65 passed/270.38ms。API小helper复用api，只把确认与独立读取边界显式化；hook同步confirming ref防同轮双击，确认回执即移除可确认草稿。回执是标签临时UI，恢复以服务端列表为准，不新增持久字段。Chrome红/绿与PG回归待验证。
- Chrome新建专用合成旅行28c7…29e3，使用服务层设置离线京都固定条件，不更改已有旅行；显式生成1离线run。只读探针首次误假设PlanDraftRow有created_at导致AttributeError；更正为当前session恰一草稿断言，不绕过证据/确认。故障API仅指定plan成功认证GET返回503，POST确认仍实际事务执行。
- Chrome旧bundle确认POST实际成功，指定合成plan的认证GET返回503；busy结束后保存按钮仍enabled=true、已保存回执heading count0，明确抛出T2.5失败断言，截图t25-red-confirm-read-failure。没有再次点保存；之后解除该只读故障，红案例将只读恢复；新UI绿将使用另一独立合成旅行，不把不同旅行版本合算为重复写。
- 初次新UI绿旅行2475…4168：Chrome dblclick确认后已保存V1回执1、确认按钮0，POST目标计数待PG核对；但原run尚未保存标签count1，明确失败断言（P-21，计划外）。修为只依据同一草稿的可信POST回执、原planOrigin/session+run更新该轮次业务结果，保持最后GET/归属/generation。不重确认已知成功草稿；最终绿以另一独立合成旅行复核，所有版本分别核对。
- 独立审查P2指出普通refresh空plan时不读回执plan_id，无presentation不能恢复；现有presentation虽能恢复但不清回执。Chrome初绿故障解除重试实际formal heading1/receipt heading1，明确断言红（P-22）。补同session receipt优先canonical GET/active后清回执，再restoreConversation。最终绿将先显式普通查询令最新轮次无presentation，再重试，验证不依赖旧卡片；不再次POST已确认草稿。
- 最终第三独立合成旅行3d60…2dbb dblclick：receipt heading1/confirm buttons0/原轮次confirmed label1/unsaved0。精确认证GET503故障仍启用时，显式发1普通离线查询，PG最新run answer_only/presentation0；解除故障后只读重试formal V1 heading1/receipt0/save0，再刷新仍formal1/receipt0。计数targetconfirm1、总POST8/PATCH0重试前后完全相同；POST8包含红1confirm、初绿newsession+message+confirm、最终newsession+message+confirm+显式query，不冒称0总写入。
- 只读PG三个独立案例每个formal V1/版本行1/draft.confirmed_version1/confirm HTTP1，原已有V1哈希87e4…25f不变；所有请求为本地默认离线样例。故障探针已CtrlC停止、flag移除，默认DEMO_MODE API已恢复。全部截图人工查看，无token/密钥/私人对话。证据t25-confirmation-readback.json/红与两类绿截图。
- 最终前端 `pnpm --dir apps/web run test`65 passed/280.17ms；`run typecheck`/`run lint`/`run build`5路由退出0；`uv run python scripts/dev.py check`254文件/三平台strict/3契约/10入口通过。`uv run python scripts/dev.py test`1027 passed/7 failed/1 skipped/1 live deselected/255.38s，失败逐项同P-05；既有真实PG并发确认测试通过。全程Python源码未变，完整进程期间修前端P21/P22后前端全部检查重跑；不以旧前端检查代替最终状态。独立P2已修复并复核无新发现，最终只读源码/JSON无新发现，P3指出§7/P01陈旧“未实施”已按实测同步更正；commit待完成。
- 实现`ea419749b6ed869a4b5b168a904c409a6c3dd9a8`已提交/push，远端SHA完全一致；P20–22及T2.5证据已回写计划，§7/P01陈旧记录同步更正。P01原线上根因未知仍doing，C2整体候选；本次可复现确认/读回边界另沉淀STAR。

## 2026-10-08 T3.1 条件表单的无变化保存

- 开工`git status --short`空，HEAD/远端`cb4bdcc268a13b67a78a17002e6f7db80976150a`一致。按需读取Conditions/pace/api/saveConditions/domain apply_request_patch/PG no-op/ADR015边界。后端已有规范化no-op；前端全量注入隐藏默认（京都/日期/2成人/1房/5万/步行/9点/标准节奏），mergePace重新排序。采用diff/set-clear与空diff不发PATCH，保留卡片；未引入新字段/持久标志。
- `pnpm --dir apps/web run test`首红64 passed/3 failed/279.16ms（新diff模块缺失、未知pace错误默认、同pace重排）；实现后72 passed/289.95ms。Conditions单一空值form state，无示例/默认填入，原unknown children空输入保持未知；按原始条件diff/Decimal预算/零秒time规范化，显式清除用已有clear，未变saveConditions不进入action、不清卡片。儿童显式unknown/none/infant选择留T3.2。
- Chrome旧bundle原合成T2.5最终旅行不改可见字段保存：PG revision1→2/soft_constraints空→节奏标准，PATCH0→1；正式V1行数1/哈希d254…505d未改。明确assert revision unchanged失败，原问题本地VERIFIED。首次typecheck失败TS2739：生成TravelConditions输出类型要求序列化默认字段，不能把其全类型当set输入；改为既有Partial<TravelConditions>与已有clear类型，不为满足类型注入默认。lint/check已过，最终前端检查重跑待核对。
- 独立P2计数等价仍PATCH/清卡片（P23）：新增2.0/01实际回归72 passed/1 failed/299.20ms，扩有限数值等价比较。P3原生约束（P24）Chrome旧表单填0.50与09:00:30，DOM budget rangeUnderflow=true/time stepMismatch=true，两者validfalse且明确失败断言；仅填不提交，改预算min0.01/time stepany，保持既有后端契约。最终检查/同输入valid与无变化保存保卡片待验收。

- 最终 `pnpm --dir apps/web run test`73 passed/287.78ms；`run typecheck`/`run lint`/`run build`5路由退出0，`uv run python scripts/dev.py check`254文件/三平台strict/3契约/10入口。完整 `uv run python scripts/dev.py test`1027 passed/原7 SDK failed/1 skipped/1 live deselected/258.39s，失败清单逐项同P-05；Python源码未改，最终前端检查在P23/P24修后重跑。
- Chrome最终UI三次no-op（直接保存、2.0/01/50000.00、酒店卡片存在时2.0/01）：PG revision2/soft标准/PATCH1始终不变，唯一V1/哈希d254…505d不变。卡片验证前显式发1“演示：比较酒店”离线消息，真实生成1比较面板/3暂留按钮；保存后仍1/3，不冒称0总写入。P24相同0.50与09:00:30均validtrue/rangeUnderflowfalse/stepMismatchfalse，仅填不保存，reload丢弃。
- 切换已有空白T2.2旅行：form所有条件输入/未知select值为空；未改保存后只读PG revision0/child_ages null/八字段null，PATCH总数仍1（仅旧UI红那次）。未知儿童不被置[]；儿童显式三状态留T3.2，空白页旧离线门槛仍留T3.7。证据t31-condition-noop.json，两截图人工查看；初次卡片截图位于上方看不到卡，滚动后替换为三酒店可见图，实际DOM计数与PG为验收依据。
- 最终独立只读审查源码/测试/计划/ops/JSON/两截图，无阻止提交发现；P23/P24关闭。审查未运行测试/未修改文件。`git diff --check`与`uv run python scripts/check_docs.py`退出0；实现commit待完成。
- 实现`1809aa567aa0ec5e98c2bdc89d508584e7b72323`已提交/push，远端SHA一致、checkout干净；T3.1/P02/P23/P24状态与C3 STAR回写，恢复点T3.2。

## 2026-10-08 T3.2 儿童三状态

- 开工git status空/HEAD与远端825c4f5一致，读既有TravelConditions/RequestPatch/TravelService、PG no-op及ADR015边界；已支持null/[]/[0]与clear。选择使用仅表单本地child_state派生值，不新增持久字段/接口/ADR。未填不造[]；无儿童明确[]；有儿童年龄必须填、0合法。
- `pnpm --dir apps/web run test`新三状态实际回归先红：现有form无child_state，unknown→none不能生成[]，选择有儿童空年龄不报错；输出73 passed/2 failed（完整时长见后续日志摘要）。后端现有事实契约不改，绿将直接验证这些行为。
- 首红web73 passed/2 failed/260.10ms（新三状态/有儿童空年龄），实现后75 passed/273.98ms。既有年龄坏token测试加明确ages状态，空表单测试补unknown选择其余值空，不移除原断言；UI状态不持久。Chrome旧bundle实际儿童情况选择count0，expected1失败（VERIFIED）；新版Chrome三状态保存/读回待测。
- 启动新版构建时首次误用monorepo standalone/apps/web路径失败，查实际输出standalone/server.js后修正；项目无public目录，其复制失败无静态文件丢失，static已复制，server正常127.0.0.1。Chrome儿童getByLabel getAttribute超时，改读实际combobox角色/选中DOM，不猜值。
- Chrome仅无儿童保存，PG revision1/child[]/其他字段unknown/PATCH2（前1为T3.1红）但摘要无儿童count0且显示未设，明确断言红P26。补摘要以child_ages!=null显示既有partyLabel；不自动填成人/房间。Python源码没改，完整回归运行期间补前端后，最终前端全部重跑。
- Chrome/PG同一已有空白旅行null/rev0→无儿童[]/rev1→婴儿[0]/rev2→clear后null/rev3；每次只变儿童字段，其他八字段仍unknown。空年龄点击保存只中文错误、PGrev1/PATCH2未变；最终未知no-op仍rev3/PATCH4，4包括旧T3.1红1+本任务三次更新。刷新无儿童摘要count1；刷新婴儿表单selected ages/value0；clear后刷新unknown/age输入0，均VERIFIED，JSON t32-children-states。未创建正式版本/未真实供应商或模型调用。两截图人工查看。
- 最终web75 passed/304.54ms、type/lint/build5路由/check254三平台strict/3契约/10入口退出0；独立只读实现/P26复核无发现。完整 `uv run python scripts/dev.py test`1027 passed/原7 SDK failed/1 skipped/1 live deselected/258.13s，失败逐项同P-05；Python源码全程未变，前端检查在P26修后重跑。
- 实现`2f54458c19d3ccd48edb68d957bf9b938aa94147`已提交/push，远端一致且checkout干净；T3.2/P25/P26证据状态回写，STAR C15完成，恢复点T3.3。

## 2026-10-08 T3.3 住宿预算与现算关系

- 开工git status空，HEAD/远端b6fa30b一致；按ADR015读travel_request/repository/TravelService/validator/HotelService/HotelOffer/API schema边界。先补ADR响应预算关系及旧快照/缓存投影实现细节，再写测试；无新增依赖/paid调用/生产数据库操作。
- 领域新测试先红ImportError 1 error/0.08s（缺现算函数）；补有效proposal fixture（原测试空items违反既有至少一项，未改业务约束）→20 passed/0.05s。纯Decimal端点/房晚/total/币种未知/0晚/单端/结构非法和validator既有CheckStatus均覆盖。
- 真实PG三红3 failed/0.36s：新键直接写旧conditions导致冻结旧模型extra_forbidden；HotelOffer快照含新键同样不兼容；冲突search未raise。首次循环预创建两个coroutine导致失败后的unawaited warning，测试改lazy调用，仍原断言；不跳过失败。旧模型fixture冻结自b6fa30b自身源码（只测试），非上游复制。实现增量0013 nullable JSONB、旧conditions/Evidence/operations投影、cached回执读取当前事实、两入口冲突guard待绿。
- 增量列/旧快照/cache-current与两入口guard后真实PG3 passed/0.35s；酒店当前住宿上限红11 passed/1 failed/0.07s（card不接current），补当前request与nullable住宿flag/比较预算关系，领域+酒店+真实PG35 passed（确切时长见最终汇总）。0013 downgrade保留列与事实，upgrade使用ADD COLUMN IF NOT EXISTS避免回退后重升级重复列；回退/重升级保数据实际测试待补。
- 类型/工具链尝试：首次schema导出漏PYTHONPATH=.失败，补后再generate。dict serializer使HotelOffer.request输出schema变成unknown，bookings四项TS报错；改明确LegacyRequestSnapshot投影模型（仅住宿字段exclude），保类型与冻结旧读回。首次导入替换漏单行import导致NameError，修正后导出/generate/typecheck通过。Pydantic computed_field/property被strict mypy拒绝，改只读响应字段由from_request用唯一计算填充；测试嵌套JSON加实际isinstance断言，不使用ignore。
- 混合unit/integration具体文件命令57 passed/19 setup errors（postgres_url fixture发现失败，非业务assert）；分开原PG文件24 passed/2.72s、领域52 passed/0.25s，完整项目命令作为最终检查。不据此宣称pytest根因已定位。预算PG增补确认/API禁止伪造关系/0013降级再升级6 passed/0.94s；降级仅随机测试库，事实完整保留。
- 独立P2新增P28 known_quotes await交错：真实PG预算更新冲突后旧present返回，首红6 passed/1 failed/1.06s；新增resolve后_request复核。正在运行的完整test因新后端修改主动CtrlC（exit130），不计通过；将在修后重跑。P29仅全程预算摘要源码漏门槛，Chrome先红待验。

- 最终绿：预算PG7 passed/1.04s（P28新增实际数据库交错）；独立只读复核两增量无新发现。P29 Chrome仅budget60000原money0/empty1断言红，PGrev4/住宿null/其他未知；纳入预算存在门槛后刷新money1/empty0绿，金额及未知事实不动。
- Chrome/PG离线实际：rev5两预算50000/30000均存、缺晚数unknown；批量locator日期/时间fill未留到提交（PG为null），改原生AX setValue逐字段核对，补两晚/时间后rev6 conflict60000>50000。明确比较失败run1含一次search工具失败、0presentation；不是付费供应商比较。只改budget70000 rev7/住宿原样，diff仅budget；改全程50000/每晚20000–30000 rev8 warning40000–60000，成功run2/1presentation/3hotel_offer，15k/17.4k/19.8k上游序列，低于lower不被排除。刷新读回原值与警告。原V1一行/内容SHA256每次不变，证据product-v2/t33-budget-relations.json与两张已查看截图。只读probe首次误用TravelRequestRow.user_id AttributeError，改从SessionRow读取既有归属后通过，未改测试断言。
- 最终项目命令：uv run python scripts/dev.py check exit0（258格式文件，win32/linux/darwin strict各258，3契约/0broken，文档10入口）；uv run python scripts/dev.py test exit1：1055 passed/原P05七个SDK失败/1 skipped/1 live deselected/257.68s，失败名单与原基线一致，无新增失败。pnpm --dir apps/web test exit0：77 passed/0 failed/306.24ms；typecheck、lint、build均exit0/5路由。旧完整测试因后端新修复CtrlC130不计入此结果；脚本编排一次JS语法失败未执行文件命令，后重跑证据汇总断言通过。
- 本机开发库仅upgrade0013（先assertloopback），nullable列添加，无drop/reset；rollback/reupgrade仅随机测试数据库中实际验证。API与web已重启为最终离线bundle；无Railway/生产/付费调用。实现 `0febb2eaabdda7ad4b0e304de3e3b8c1c08dfd80` 已commit/push；git ls-remote读回相同SHA，无生产部署。

## 2026-10-08 T3.7 对话优先与字段来源

- 开工git status空，当前/远端a3f737a（刚push）；已按需读ADR015、design03条件/工具与02上下文边界、FixtureRuntime/demo/Conversation/TravelService/operations；第一次文件猜名不存在/未匹配zsh通配无源码操作，按rg返回路径继续。先补ADR明确来源只读回执/受阻字段、旧操作重试兼容、有限离线样例与JST相对日期范围，无新runtime/依赖/付费调用。

- 红测：来源两个PG TypeError（source未实现）2 failed/0.31s；离线首轮札幌未保存/空demo failed 2 failed/0.72s；Chrome新旅行比较chipdisabled/formGate1断言红。实现后4 passed/0.80s；来源UI helper缺文件77 pass/1 suite失败→79 pass/297.60ms；领域/fixture边界26 pass/0.17s。初次check import排序与一长fstring2错误，修后check通过。
- PG相邻37例先36 pass/1 fail/14.74s：旧并行工具测试未声明明确覆盖，现按user_form保护两次都no-op；测试原意验证真正并行写，参数补explicit_fields adults，保留原一成功/一conflict/计数断言，不放松结果。
- 独立审查P32真实旧key缓存+新ConversationRequestPatch重试先红2 pass/1 fail；P33裸节奏格式/P34假设与否定3例先红（确数后补）；将legacy fallback投影原schema、复用“节奏：”前缀、有限句式拒绝假设/否定更新，不引入解析运行时。

- P32首次legacy投影误用全model_dump注入默认null，邻近2 failed/3 passed/33 setup errors/2.40s；修正set.exclude_unset，原断言保留，38 passed/15.25s。类型测试budget用str被mypy拒绝，改Decimal不改变金额/断言。P34否定整句虽不写仍进入无关查询，真实HTTP另红2 pass/1 fail/0.82s；加明确未更新澄清、0工具，专项6 pass/0.89s。
- Chrome首轮无需右侧：gateenabled/formGate0；直接规定札幌句→右侧目的地/10-17至10-18/2成人/5岁/8万和6来源标签，助手追问房间数。独立P35“特别”误判红12 pass/1 fail/0.06s；浏览器又发现P36选择框仍未设，rightCity已正确/selectedLabel未设断言红，接着复用现有摘要更新逻辑。两项继续先红后绿，不覆盖原7SDK基线。
- P37 Chrome实际红：已保存慢节奏但收起摘要精确值count0；新增空旅行仅1间房，PG rooms1/rev1/其余未知，摘要roomValue0/empty1断言失败。未改数据/未补默认；将门槛补齐现有可展示字段并复用currentPace。
- 完整回归本轮exit1：11 failed/1070 passed/1 skipped/1 deselected/256.74s；原7 SDK之外新增diagnostics2/eval_metrics1/sdk_database1。固定工具响应未声明明确覆盖手填字段，新语义保护导致no-op。P38先记录实际红，再仅补explicit_fields测试输入保持原断言；不放开业务保护、不算本轮全绿。前一正在运行full因新修复主动CtrlC130，没有最终计数。
- 修后P35领域31 passed/0.18s；P33/P34同轮8 passed/4 failed/0.06s红→30 passed/0.17s；P36 helper文件缺失79 passed/1 suite红→81 passed。P38只补明确字段输入，专项8 passed/4.60s，原全部assert不变；首编辑误用python无命令未执行，改uv run python后重跑，未把无改动重跑当绿。
- Chrome/本地PG：规定首句rev1六来源，未知留空；仅手填成人4rev2/user_form，模糊3rev2保留4，明确改成3rev3/仅adults差异并告知；否定清空原8万/rev3不变且0tool；全程6万/住宿每房每晚2–3万/房1/慢节奏rev4都原值保存。另一个空旅行仅room1 rev1，摘要red0/empty1→green1/empty0；特别想去札幌rev2/cityonly，未补日期/成人/儿童/预算/节奏，标题无reload已札幌。主旅行切回后慢节奏精确count1。全部run completed，0presentation/0evidence/0付费调用，原V1一行/hash未变。证据t37-conversation-conditions.json含8阶段PG/9UI断言，早期未按sequence排序的run_results省略，仅最终ordered lists保留；两截图均已人工查看。
- 最终当前web81 passed/358.25ms；typecheck/lint/build5路由exit0；dev check263格式/三平台strict/3契约/10入口exit0。P37/P38独立只读增量无发现（未跑测试），完整回归重新运行中；不声明全绿。无Railway/生产/真实模型调用；实时SDK用既有提示与工具，无第二解析运行时，有限fixture范围在ADR015明确。
- 完整修后回归exit1：1074 passed/原7 SDK failed/1 skipped/1 live deselected/255.85s，P38四新增失败已消失。之后收尾发现P39金额币种子串：全程5万美元→JPY、住宿EUR→JPY，新增领域红13 passed/2 failed/0.06s；不是把本轮1074结果宣称覆盖后续修复。全程现有仅JPY契约不扩展，非JPY明确拒绝有限提取/对话澄清，住宿保明确币种而不换汇，修后重跑完整。
- P39 HTTP首次12 passed/1 failed/1.46s：测试错误要求异币种total_lower=None；既有T3.3规则在已知房晚时保留原币EUR40000并status unknown，不换成JPY。独立只读同样发现契约误解；仅改新测试为原币40000/EUR/unknown，保所有数值不转换断言。因断言修正主动停止未完成full exit130后重跑，不将它计作通过；未改变预算计算业务规则。
- P39独立P2发现guard只检查首个预算，同句“全程5万JPY，总预算8万美元”会写首金额；有限匹配范围内红15 passed/1 failed/0.06s（实际时长以日志为准），改finditer任一外币整句澄清/零工具，同句HTTP也纳入；不会假装解析通用多金额表达。未完成full因真实后端新增修复再次CtrlC130，最终版本重新回归。
- P39最终领域36 passed/0.07s、来源/HTTP/工具PG14 passed/1.49s；check263/三平台strict/3契约/10入口exit0。独立复核guard全部匹配与原币换算断言无新阻塞。实际Chrome/开发PG全程5万美元未写入/0tool/仍rev4/JPY60000，住宿EUR20000原币保存rev5/1房1晚总额EUR20000/关系unknown，明确恢复住宿JPY2–3万rev6且其他conditions完全相等；原V1/hash不变，0酒店/模型调用。证据JSON增加三阶段总11阶段PG；外币截图已查看，既有两张也已查看。最终完整测试运行中。
- 最终完整 `uv run python scripts/dev.py test` exit1：1080 passed/原7 SDK failed/1 skipped/1 live deselected/259.55s；失败集合逐名与前一已闭环1074结果和P05相同，无新增失败。不是全绿，R6前仍须解决P05。dev check263、web81/type/lint/build5路由已通过（P39仅后端/测试，前端未再改）；git diff --check/check_docs10入口exit0。实现待commit/push。
- 实现 `4108fb90fc84d4b7134c5038e41c9d6613f3b9e3`已提交/push；git ls-remote相同SHA，checkout干净。P30–39全部闭环，T3.7 done、C17 STAR落盘；恢复点T3.4。

## 2026-10-08 T3.4 节奏与重复景点

- 开工git status空/HEAD a41c6dd/当前分支，T3.7记录已push；首次猜测validator/design文件旧名不存在，按rg --files纠正，未改源码。按需读domain validator/itinerary/catalog/Evidence、既有itinerary与预算单测、design03 §5与05 R06/R07。拟沿用CheckStatus unknown/汇总partial表达非阻断警告，不新增报告字段/依赖/ADR；已知分类排除住宿/餐食/交通，按真实entity_id而非Evidence UUID计重复，以JST分天。
- `uv run python -m pytest tests/test_itinerary.py tests/test_persona.py -q`首次红：6 failed/44 passed/0.52s，四密度（慢4/标准8/特种兵9/未知8）、同entity三不同Evidence跨日重复、固定提示仍默认标准；其余分类排除/日本日边界/来源缺失/旧失败路径控制通过。未削弱硬冲突或改断言。
- 首绿validator/persona/预算70 passed/0.47s；初次check mypy同一函数两个循环复用visits（list[str] vs list[tuple[date,str]]）3错误，重命名第二循环变量，不ignore。P41补离线其他软条件少走路≠已知节奏，现missing_question跳过追问，领域红16 pass/1 fail/0.06s；改为检查已有规范节奏值，不删其他偏好、不默认标准。
- P42自审有界反馈：8景点营业时间未知时8 opening+7 route unknown在前，新增全局密度提醒排在第16项，SDK feedback只取12会隐藏。新测试首编辑漏helper hours参数造成18 failed/25 passed（NameError/参数错误，非业务红），按真实签名补参后原断言重跑，正确红记录下一条；不通过删除unknown来过关。
- P42正确红42 passed/1 failed/0.45s：反馈12项中无pace_warning；P43四类别+P42合跑42 passed/5 failed/0.50s，Google缺types映射16 passed/1 failed/0.22s。采用有限正向景点分类集合，其他/未知不计，不靠不断扩黑名单假称覆盖；Google仅缺类别回退改unknown，其他事实与请求数不变。
- T3.4最终相关领域/提示/fixture/预算/外部映射单测110 passed/0.62s；P42同unknown内优先全局提醒，硬conflict优先测试8闭馆在前8，12上限不变。P43正向类别集合，非景点/未知不计；Google缺types保unknown且名称坐标不变。dev check263格式/三平台strict/3契约/10入口exit0；完整离线test/web兼容检查与独立增量复核运行中。未调用真实模型/供应商，无DB迁移/生产操作。
- 最终 `uv run python scripts/dev.py test` exit1：1111 passed/原7 SDK failed/1 skipped/1 live deselected/259.98s；失败集合逐名与T3.7/P05相同，没有新增回归。web81 passed/363.27ms/typecheck/lint/build5路由exit0；最后dev check263/三平台strict/3契约/10入口exit0。独立只读P40–43复核无新增，不跑测试/不改文件。受控纯领域5案例t34-validator-warnings.json落盘，不冒称浏览器/实际模型验收；无新持久字段/付费/生产操作。git diff --check/check_docs10入口通过。
- 实现 `c7f71ec8f8a0bc29dacf947f3ba65c85f431b6c8`已提交/push，远端SHA一致/checkout干净；T3.4与P40–43 done，C18 STAR完成；恢复点T3.5。

## 2026-10-08 T3.5 中文状态与错误

- 开工git status空/HEAD d28eeef/当前分支；仅本人T3.5 doing记录。按需读persona/fixture_runtime/前端errorExplanation与当前历史状态/预订模板/design05语言规则。
- Chrome固定“演示：未知”实际failed，横幅和当前模板泄出validation且错误归因密钥/额度；只读本地PG revision6不变、0工具、0Evidence、原V1一行/hash不变；没有真实模型/供应商调用。P44/P45记录后开始固定红测。
- 固定红：web80 passed/1 suite failed/289.19ms（runFailureMessage不存在），独立node断言runStatus new_status!=中文回退；pytest persona/查询3 failed/18 passed/0.38s（中文专名规则、来源模式与空结果类别）。修后pytest含酒店专名34 passed/0.35s、web83 passed/298.97ms。日文酒店/房型card原样保持；fixture名称/来源标识原样，不用“含汉字”假称中文。
- 首check新增测试execute缺return annotation，mypy strict报1错误；补ToolResult类型、不ignore后check263/三平台/3契约/10入口exit0。web type/lint/build5路由exit0。本地服务首次猜错standalone/apps/web路径退出1；按实际standalone/server.js启动但未先复制static，Chrome ChunkLoadError。复制ignored static并重启后恢复，未改产品/部署配置。
- Chrome最新构建：刷新历史旧失败已中文；新发同固定输入，当前/历史/横幅中文，原raw banner与错误额度归因count均0。只读PG两次failed仅started/failed、0工具/0Evidence/revision6不变/原V1一行hash不变；截图t35-chinese-errors.png已查看，固定JSON保存，真实模型语言仍未验证。
- 独立P2/P46：已有部分answer使普通失败与历史timeout说明隐藏（源码REASONED）；新增同一runErrorMessage入口，两处同用、保留原回答，stageGuidance优先。新测试缺export先80 pass/1 suite fail/302.30ms→最终web84 passed/293.93ms；type/lint和最终build5路由exit0，独立增量关闭P2/无新发现。全量Python未修改P46无须重启，仍执行中。
- 最终完整 `uv run python scripts/dev.py test` exit1：1115 passed/原7 SDK failed/1 skipped/1 live deselected/256.98s；逐名比较T3.4原7完全一致，无新增失败，不宣称全绿。最终web84 passed/293.93ms/type/lint/build5路由、dev check263/三平台/3契约/10入口通过；最后check_docs与git diff --check exit0。P46独立只读关闭、无新发现。最终构建刷新两条历史错误均中文/raw validation0；未追加第三次失败写入。
- 实现 `8fc7b94f16899d77ecf00d7f45cf8f727efb8ef5`已提交/push；ls-remote一致。P44–46 done、C19 STAR完成，恢复点T3.6。

## 2026-10-08 T3.6 日期入口

- 开工git status空/HEAD296e014/当前分支；T3.5记录push完成。按需读Conditions原生date两字段，无新API/日期库/ADR；先浏览器复现点击正文与label，保留原生键盘输入及未知空值。
- Chrome实际红：打开编辑，开始标题107点击只focus年份110；截图无日历弹层。getByText exact因来源标签无匹配而超时，按实际AX标题点击，无猜坐标/数据修改。P47记录，拟复用原生showPicker、只click不focus触发，保留无支持浏览器/键盘输入。
- 首实现web84/type/lint/build/check263通过，但Chrome AX标题点击绿测仍无日历；独立P3 label转发重复路径REASONED。未宣称通过；getByLabel exact同样因来源text标签不匹配超时，后续按截图文字与已观察DOM date控件验证。P48记录，成功打开后阻止默认、失败时保留默认。
- 系统限制核实：cua.getApp Google Chrome找不到可见window；getState明确native apps失败因为Mac已锁定且无法自动解锁。Chrome扩展DOM/页面截图可用，但不能观察系统原生picker；先前“无弹层”只证明截图未捕获，不能证明实际picker未打开。DOM安全evaluate typeof showPicker未定义不能当作真实浏览器API无支持证明，未据此修改实现。已请求用户解锁，不绕过锁屏/换浏览器。T3.6保持doing/待原生弹窗与键盘验收；静态/type/lint/web84/build/check263通过，小型入口先保存WIP commit以保持下一独立任务开工clean，未宣称完成。

## 2026-10-08 T4.1 酒店分组

- 开工git status空/HEAD7bc3bdf/当前分支；T3.6 WIP已push、保持doing待系统解锁，不丢日期未完成状态。按需读rakuten/domain hotels/service/tool/cards/results/相关原测试；先在ADR014定保持flat契约、现有6报价上限与每家最多2套餐，limit不同酒店优先。P49记录；发现P50压缩层旧总价sorted违反D7，先新红再更正已过时旧测试，保8K/完整卡片验证。无扩供应商调用/付费/生产变更。
- 先红：adapter/压缩2 failed/24 passed/0.27s；web84 pass/1 suite failed/288.65ms缺hotel-groups。新增PG首1 fail/4 pass/0.49s，源目录第一六家各一套餐，红为4家/4offers，未证明只2家；将受控fixture按酒店相邻组织后原断言仍红、实际2家/4offers，保原所有assert。
- 首实现domain38 pass/1 fail/0.48s仅旧最低价排序assert；根据D7改为准确上游prefix，保整卡与8K断言。PG邻近6 failed/6 passed/4.47s是旧lookup固定helper limit2要求2offers；新酒店语义返回4，补P51，改输入limit1且原断言不变。最终领域44 passed/0.27s，web86 passed/402.82ms/type/lint通过。首check6类型错误（Evidence值JsonValue不能直接字符串索引、新测试dict invariance/卡片object未narrow），改用报价构造时已有typed rate keys与isinstance，不ignore。
- 最终相关PG12 passed/4.81s；初次check264/三平台/3契约/10入口exit0、web86/type/lint/build5路由通过，独立只读无阻塞。Chrome复用T33本地京都rev8：新离线比较6offers/3家/3选择框，各两套餐；选家庭房offer9e9f…d47f，价格15000→20000、含早/可退、最低价标签消失。启动本地mock_supplier，核实loopback；服务实际使用本地PG（工具启动说明误称内存，此处更正），只点击暂留，不确认订单；PG booking held且offer匹配、supplier hold1/order0、Evidence9不增、rev8/原V1 hash不变。截图数量与套餐两份已查看，JSON脱敏落盘。完整回归执行中，T3.6锁屏问题没有因酒店DOM通过而关闭。
- 首完整exit1：1120 passed/10 failed/1 skipped/1 live deselected/256.56s；原7外新增live_business/old_rows_snapshot/workbench三例，均旧limit套餐数量断言。SDK固定转发第3步assert3实际6导致HTTP线程中断/provider_error，非业务provider失败；另limit1实际同酒店2报价、demo3实际3酒店6报价。P51补记录，保六HTTP/工具顺序/旧快照/正式版本等原断言，只更正酒店+报价精确数量，并加强每条旧快照读回。

- 第二完整1122 passed/8 failed/259.96s，原7外eval_state[expired]未抛：setup只将records0过期，第二套餐仍新鲜，SQL无序取第一行可能是它；非hold规则放宽。新P52记录，强化每条旧报价hold拒绝先红，然后expired准备器更新全体，不以排序/跳过规避。
- 路径探查误猜backend/domain/presentations.py、tests/test_presentations.py、evaluation/evals不存在，已改用rg --files与实际eval/state.py；没有读取凭据/改变断言绕过失败。

- P52逐条报价拒绝首红1 failed/1 passed/0.86s→全文件18 passed/7.22s。独立P2指出任何ServiceError可能由supplier503产生；断言加409/conflict/evidence_stale:hotel_offer以验证证据前置。为避免测试中途修改源码，主动停止刚开始的第三全量exit130（不是结果），加强测试后重新全量。静态check265仍通过。

- 最终P52严格失败原因专项 `uv run python -m pytest tests/integration/test_eval_state.py -q`：18 passed/7.16s；`uv run python scripts/dev.py check` exit0，265文件三平台strict/3分层契约/文档10入口；完整第四次核对中（第三次主动中止未计成绩）。Python-only兼容/评测准备变更没有重复无关web测试，已建web86/type/lint/build证据仍有效。

- 最终 `uv run python scripts/dev.py test`：1123 passed/7 failed/1 skipped/1 live deselected/262.37s（exit1）；对T3.5逐名比较失败集合完全相同，新增问题均消除，非全绿。严格失效PG18/.7.16、兼容15/7.44、酒店PG12/4.81、领域44/.27、web86/402.82ms/type/lint/build/check265已验收。独立P52错误原因边界关闭。无生产变更/付费调用。

- 实现 `8f53e88`已提交/push，P49–52 closed/C20归档；T3.6仍未满足原生弹窗验收。恢复点T4.2。
- T3.6补验：开始2026-11-03→ArrowUp2027-11-03→ArrowDown还原；结束2026-11-05→2027-11-05→还原。未点保存；PG只读rev8、Evidence9/order0/原V1一行hash87e4…25f不变。截图t36-keyboard-restored.png已查看。cua.getState apps可列，getApp仍明确锁屏，不能把列表可读当解锁；T3.6保持doing。
- P05独立只读研究：当前CLI仍读取DISABLE_AUTO_COMPACT/PCT_OVERRIDE，但有window/reactive/precompute分支。后续R6可仅在测试helper使用官方CLAUDE_CODE_AUTO_COMPACT_WINDOW=100000，先观察人工usage/compact_boundary/summaryHTTP与关闭对照，再把实测精确SDK/CLI pair加入guard；还没运行、原因仍REASONED。公开依据 https://code.claude.com/docs/en/env-vars 与 https://code.claude.com/docs/en/model-config#default-auto-compact-thresholds；不扩大Guard端点/费用/改全局CLI。

## 2026-10-08 T4.2 三类酒店链接

- 开工git status空/HEAD0c5d7ec/远端一致；按需读既有QuoteFields、HotelCard、证据读回、Bookings/Supplier协议和0013迁移。ADR014先定internal excluded display_details与nullable sidecar。独立指出最初只strip add_evidence遗漏Booking/Supplier，改一处serialization排除方案；Pydantic最小无网实验确认nested dump/serialization schema排除，但不冒称仓库验收。P53记录方案/兼容取舍，先红开始。

- T42首红：pytest3 failed/0.28s（无内部细节字段/extra forbid）、PG2 failed/0.34s（字段无/不保存）；web86 passed/1 suite failed/293.46ms（helper不存在）。实现后领域34 passed/0.25s、三URL/酒店/旧预算快照PG20 passed/1.61s（down0013/up0014保数据、旧writer、livehold422、实际fixture Booking/SupplierHold冻结模型+幂等）。schema生成无DB/凭据；check270 strict三平台/3契约/10入口、web88/type/lint/build5路由通过。
- 失败尝试：初ruff检查6import格式可自动修/1行长由format修，最终未忽略；邻近pytest首次误猜test_session_history.py，exit4/0 tests；按rg --files实际test_history.py补正确命令，不作为通过证据。0014仅本地开发PG增量迁移成功，生产未操作。

- 独立P54：hotelInformationUrl仍必填，补missing/null/all_missing三例首红3 failed/0.28s；前次完整正在运行，没有中途改适配器。后续需改可空并复验，不把之前完整冒称涵盖新用例。Chrome当前三URL可读，实际点击介绍打开新tab精确https://example.com/?hotel-info=1（Example Domain），另两URL独立。截图两份已查看；仅一次示例导航，单测/业务无网络依赖，不预订。

- 最终P54 missing/null/all_missing红3/.28→领域37/.29；正式V1 stage/confirm/reopened get读回三URL、版本payload前后相等，PG21/2.09s；共用Hotel展示所有链接，非仅比较卡。check271 strict三平台/3契约/10入口exit0，web88/329.15ms/type/lint/build5路由exit0。独立P54关闭/无新发现。
- 前完整1128 passed/原7 SDK failed/1 skipped/1 live deselected/259.32s，未含新missing3和formal1；最终完整1132 passed/原7 SDK failed/1 skipped/1 live deselected/265.33s；逐名与T41/T35集合一致。未在前次完整执行期间改适配器，结果按版本分别记。
- Chrome最终共用卡3链接/刷新保留，精确介绍href/实际新tab URL=https://example.com/?hotel-info=1；仅点击介绍，没有点预订/选用/模拟确认。合成RawResponse两晚2次MockTransport，0真实查询；PGsidecar1/Evidence10/rev8/order0/原正式V1 hash不变。两截图与JSON已查看。正式V1恢复为专用临时PG而非Chrome；不冒称真实乐天链接语义/线上数据验收。
- 探查又误猜test_validator.py不存在，已直接用已读imports中实际test_planning.py；不计为测试证据。今后路径以rg --files确认。

- 最终完整命令 `uv run python scripts/dev.py test`：1132 passed / 7 failed / 1 skipped / 1 live deselected（265.33s），exit1如实保留；七项FAILED集合与T41/T35逐名相等，P05仍是发布门禁。对照日志首次误用简称路径exit2，按rg --files查到实际full-test-closed/full-test文件后比对通过。

- 代码 `2da2b16`提交/push，证据全部落盘；P53–54 closed/C21归档；恢复点T4.3，T3.6仍待原生弹窗。


## 2026-10-08 T4.3 空/失败酒店面板

- 开工git status空，HEAD/远端af83d73。按需读工具执行事件、真实酒店服务、离线脚本与既有hydrate/runCards；ADR014先定有限展示投影。保持成功显式present与所有守卫；空/失败复用同run持久事件，不新增字段/查询/报价。
- 路径探查失败：误用不存在presentation.ts/hooks/use-workspace.ts、test_execution.py/test_runtime.py、03-implementation.md，rg exit2；已按rg --files定位lib/use-workspace.ts、early-cards.ts、test_business_result.py、03-data-tools.md，失败不计验证。后续仅已列出路径。

- 事件首红19 failed/1 passed/0.32s（仅无关/成功边界通过）。首次PG4 failed/0.88s包含测试错误：RunView是dataclass无model_dump、住宿实际契约amount/basis=per_room_night；修正后有效首红3 failed/1 passed/0.82s。实现后事件相关31 passed/0.27s；PG3失败发现计数全schema共享了成功案例Evidence6，应按当前session过滤，已修正查询范围而非弱化零写入断言。

- 相关PG最终23 passed/2.96s，原empty测试改契约但增加零卡片/最低价/empty wrapper断言。独立只读无P2/P3：有限投影不改变工具返回/错误/业务状态/守卫，无额外调用与runtime。首次strict检查10测试typing错误，修正类型/范围；前端首次测试遗漏现有必需可空budget_relation，补null，同时后端空比较明确None。前端最终89 passed/291.51ms/type/lint/build5路由exit0；strict尚余测试error值object索引需窄化，不ignore。完整正在运行，源码保持。

- Chrome首加载ChunkLoadError，dev.logs给出精确chunk；本地当前.next/static存在，但standalone/.next/static不存在，补copytree当前静态文件（仅ignored构建物）后reload，不改产品或浏览器安全设置。

- 完整 `uv run python scripts/dev.py test` 1156 passed/原7 SDK failed/1 skipped/1 live deselected/265.11s，exit1；FAILED逐名与T42一致。最后测试error索引仅补isinstance窄化，原业务断言不变，相关单测31/.27再次通过；dev check273/三平台/3契约/10入口最终exit0。
- Chrome新标签同身份独立session 1c832335-ad27-4ca5-bbf6-4790d9cda541：12成人1房空匹配→面板0家/无最低价/刷新保留；改成2个大人→3家6套餐/原价；受控本地fixture OSError→unavailable/失败0家，原成功留历史禁行动，本轮零报价。故障API已停，恢复默认离线API；三态截图已查看。新标签资源可用，旧标签加载停留未据此判业务失败；无生产或付费调用。发现有限表达缺口P56另记待先红修复，不将未识别值自动写入。

- 默认API恢复后Chrome刷新：两个0家（旧空/最新失败）、故障原因1，旧成功仍3家但行动disabled。只GET恢复，不重跑工具；本地PG三轮依次completed/empty/0卡，completed/ok/6卡，failed/unavailable/error/0卡；rev3/Evidence6/booking0/hold0/order0/原正式V1一行hash不变。JSON与三截图已检查，成功截图标题上沿略裁但三店/价格可见，DOM另证明3家6套餐。
- 实際命令：领域 `uv run python -m pytest tests/test_hotel_empty_presentation.py tests/test_business_result.py tests/test_tool_failure_detail.py -q` 31 passed/0.27s；PG `uv run python -m pytest tests/integration/test_hotel_empty_presentation.py tests/integration/test_hotels.py tests/integration/test_lodging_budget.py tests/integration/test_workbench.py -q` 23 passed/2.96s；`uv run python scripts/dev.py check` exit0/273；`uv run python scripts/dev.py web-check` typecheck/lint/test89/build exit0；`uv run python scripts/dev.py test` exit1/1156/原7/265.11s。

- `ee56fc8`实现提交/push；P55 closed/C22归档。恢复点P56先红后继续T4.4。T3.6原生popup与P05仍为门禁。


## 2026-10-08 P56 对话明确表达补全

- 开工`50109fb`clean/远端一致。只补既有有限离线词汇的肯定表达，不改变SDK路径、来源/幂等、币种或付费调用。先红三类与冒号/数量变体，保否定/假设/no defaults/手填保护与明确改值。

- P56首红领域8 failed/22 passed/0.08s，真实PG1 failed/6 passed/1.29s；肯定表达补后领域30 passed/0.05s/PG7 passed/1.18s。独立P2纯无网实验核实十三→十/2.5→2/2或3→2/否定京都/多个城市误存，P57新开，先红边界12例中实际失败数见p57-red，不把肯定绿冒称完整修复。T3.7重新doing注明补修，原证据保留。

- P57真实新增12例11 failed/31 passed/0.09s（反向负数原已拒绝，其他边界红）；独立追加P58前8字越过字段权限，补4传播/1改去边界：领域15 failed/32 passed/0.10s；真实HTTP两方向2 failed/7 passed/1.40s，确证city/adults另一手填字段被错误覆盖。不能仅逗号split，空格两例同样红；计划P58记录实际写入VERIFIED。

- P57二次独立纯解析指出到/至/en dash/tilde范围与明确示例/否定，新增9例首红9 failed/47 passed/0.09s→56 passed/0.06s；只对人数/房数区间澄清，住宿预算区间原例仍可保存。P58改去/空格两方向已绿，来源工具本体未变。ADR015路径尾读又误猜exit1，已rg --files定位真实文件，失败不计依据。

- P59独立发现范围guard把人民币首字人当人数单位，预算CNY区间原本支持，新增三领域/两HTTP先红，原EUR保留；具体计数见p59-red/p59-pg-red。不能将COUNT全局拒绝当作预算区间保护完成。

- P59红领域2 failed/57 passed/0.08s、HTTP2 failed/18 passed/2.20s→相关领域78 passed/0.25s；人单位排除人民币/人均词内匹配，原budget解析不变。独立最终纯解析关闭全部P2：21负向、两CNY20k/30k、重复城市/不带儿童/原日期与EUR均正常；PG/Chrome/完整仍分开验证。

- 最终实际命令：`uv run python -m pytest tests/test_fixture_conditions.py tests/test_travel_request.py tests/test_business_result.py -q` 78 passed/0.25s；真实PG `uv run python -m pytest tests/integration/test_conversation_conditions.py tests/integration/test_condition_sources.py tests/integration/test_workbench.py -q` 30 passed/3.74s；`uv run python scripts/dev.py check` 273文件/三平台strict/3契约/10入口exit0；`uv run python scripts/dev.py web-check` web89/280.509ms/type/lint/build5路由exit0；`uv run python scripts/dev.py test` 1212 passed/7 failed/1 skipped/1 live deselected/267.85s exit1。FAILED集合逐名与T43完全相同，不将既有缺口算绿。
- Chrome合成session7c7cd007-033b-4a27-bd87-af365e5965da：首句6字段，句后人数标签更新，手填札幌/12后分别明确改成人和目的地只更新对应字段；十三不截十、两城市澄清，各0工具；住宿每晚2–3万人民币保20000/30000/CNY。刷新右侧成人仍user_form/目的地与预算conversation、全程unknown/noFX，截图p56-first-turn/p56-59-restored已查看。PG rev7/7轮/5update/2无工具/0报价/booking/hold/order；原V1/hash未变，脱敏JSON已存。只离线，没有模型/供应商调用。
- 浏览器/命令失败尝试：右侧overlay覆盖发送，关面板后原输入成功提交；精确getByLabel目的地因来源标签未匹配，读DOM后按textbox角色匹配。两次functions JS语法错误未执行，修输入后运行；不算验证。独立纯解析21负向与CNY及原格式复核无剩余P2，范围明确仅有限离线词汇。
- 失败集合首比对正则排除空格但包含换行，错误把后续行拼入ID导致assert失败；改逐行split取得精确节点，两个集合均7且相同。此为比较脚本错误，pytest结果未变化。

## 2026-10-08 T4.4 酒店基础展示字段

- 开工2be5f8c/git status空，ADR014先补四字段。官方空室API20170426输出明确datumType1=WGS度、address1/address2/reviewCount在large响应；现有adapter已请求1/large，无需新增正常查询。仓库唯一rakuten_vacant_sample是合成样本，真实fixture验收已单独问是否允许一次现有额度查询，尚未执行。
- 探查失败：未先确认apps/web/src路径而用了apps/web/components glob与shared目录、猜m3/m4操作文件，命令exit1/2；改rg --files全局类定义定位views.py和src/components/results.tsx。一次.cache递归内容搜索误扫测试临时目录导致过量输出，后续只列文件/精确路径。未将失败计通过或保存原供应商敏感内容。
- 首红6 failed/0.36s（四展示字段不存在）；实现后相关35 passed/0.26s，完整/部分/空/null/0与1调用、large/datum1/无sort参数/原价格均验。PG首1 failed/14 passed/1.10s是冻结旧模型本来无total属性的测试错误，旧模型仅用来验协议，改金额断言用当前业务模型；真实PG最终15 passed/1.20s，重开/旧三URL侧列/旧writer/正式V1 payload相等/旧报价模型通过。
- 命令失败：误猜persistence/evidence.py与tests/conftest.py不存在，随后按rg实际travel.py/integration/conftest.py；首次export_web_schema缺PYTHONPATH报ModuleNotFoundError，普通generate仍用了旧schema，随即正确PYTHONPATH=.导出后重新generate。首check275因测试total属性失败、web因results格式失败；修测试与Prettier后重跑，不ignore。
- 首修后check275/三平台/3契约/10入口exit0，web89/type/lint/build5路由exit0。独立P61回退P2：三URL旧模型extra=forbid，新的四键即使null仍拒绝。两组纯解析实证均四项extra_forbidden；原PG15只验证前向兼容，不冒称逆向。ADR014改0015独立hotel_metadata保三URL形状；当前同列版全量先跑完，之后冻旧模型/PG迁移再红绿，不能混版本成绩。
- 同列版完整1219 passed/原7 failed/1 skipped/1 live deselected/265.18s；没有将其算分列完成。冻结旧reader实际PG先红1 failed/0.33s（四extra_forbidden）→分列PG15 passed/1.33s，旧writer/0014 down/up/旧reader/正式V1未变；领域38 passed/0.28s含metadata拒URL/价格/ID。独立增量静态复核关闭P61/无新P2/P3，未冒称其跑PG。
- 0015仅应用本机开发PG成功；同列版行仅在临时测试DB，本机主开发DB未写该版。默认离线API恢复；本地web首错server路径/静态复制位置，按rg实际standalone/server.js与standalone/.next/static重启成功。一次ps读取被sandbox拒绝，未扩大访问。探查又误猜02-agent-domain/prompts路径，改rg实际02-architecture/agent/persona.py；不计验证。未做生产操作。
- 分列最终check277文件/三平台strict/3契约/10入口exit0；web89/type/lint/build5路由exit0。主PG只增量0015；Chrome独立session30ad6bdf-2ad8-4721-b7a7-afa326d4146e条件rev1，MockTransport两晚2次/3家合成（明确模拟）持久受控展示事件，完整/部分/未知地址与0/123/未知评价数刷新保留。PG3Evidence/两个metadata/第三null、旧列仅三URL；booking/hold/order0、原V1 hash不变；JSON与两张截图已查看。没有点击模拟暂留、外链或实时查询；真实fixture仍待用户决定，保持doing。
- 最终实际命令：`uv run python -m pytest tests/test_hotel_metadata.py tests/test_hotel_links.py tests/test_hotel_link_missing_info.py tests/test_hotel_selection.py tests/test_external_data.py -q` 38 passed/0.28s；`uv run python -m pytest tests/integration/test_hotel_metadata.py tests/integration/test_hotel_links.py tests/integration/test_hotels.py tests/integration/test_hotel_offer_lookup.py -q` 15 passed/1.33s；`uv run python scripts/dev.py check` exit0/277；`uv run python scripts/dev.py web-check` web89/343.886ms/type/lint/buildexit0；`uv run python scripts/dev.py test` 1222 passed/7 failed/1 skipped/1 live deselected/262.74s exit1，FAILED与P56–59逐名一致。这是分列版最终结果，未取代真实fixture验收或P05门禁。

- 实现992a0e5已提交/push，P61关闭；真实fixture待用户决定，T4.4/P60仍doing，C24暂不归档完成；独立T4.5可继续。

## 2026-10-08 T4.5 房型资格降级

- 开工048eb61/git status空；ADR014/015先定派生标签/两稳定组/偏好hard_constraints复用。预算/调用/上游序与旧报价保持；仅有限名称识别不冒称全面资格检查，缺偏好对话澄清。文档patch首次ADR015标题锚点不匹配失败、未落任何文件；读实际末尾再补，失败不计依据。
- 独立设计建议两P2已纳入ADR：search/refresh共用入口在任何供应商查询前检查明确房型偏好（可明确无要求），不改报价模型/历史读回；硬条件整字段手填优先，新增/对应组修改保无关航班等，普通追加不能跨字段猜明确授权。现有固定测试种子需显式提供新必要条件，保原业务断言，不以放松守卫适配旧输入。
# T4.5 资格门槛/输出投影增量（2026-10-08）
- 最终`uv run python scripts/dev.py test`：1243passed/原7SDKfailed/1skip/1live/264.90s，FAILED逐名集合与上次T4.4一致（或第一T4.5原7子集），不是全绿。最终check280/三平台/3契约/10入口，web89/290.811ms/type/lint/build5routes，领域72/.22、实际PG86/14.03。
- Chrome sid7cfc1941-439d-4398-b35a-cb3a15800bf5：基础事实只update且追问；缺偏好compare0工具；回答三偏好只update；纯MockTransport两晚/2次，五合成酒店2/5/1/3/4仅资格排序，36k/20k/4k/6k/7.2k价格保持；4k最低价宿舍有资格未知与不符标签。混合推荐句与无需双床各0工具，不增revision。只读PG rev2/5Evidence/0booking/0hold/0order/原V1一行hash87e4b4…25f；脱敏JSON/三个截图保存并查看。
- P65第二P2真实混合表达runtime红2/.35（推荐落入景点查询，不是澄清）；改共用room_updates返回None标识矛盾，ambiguous分支先返回0工具/不改revision。最终相关领域72/.22、PG86/14.03，包括两混合、两手填、live0provider/旧quote、qualification截断、原预订流程。
- 第一全量1232passed/9failed/1skip/1live/265.22：原7SDK+2明确输入种子缺偏好；HTTP种子补三项，长条件保持20hard/20interests/20soft，hard17×200+3声明偏好，增加原全请求JSON>8000压力断言，其他原断言不改。第二全量启动时仍旧种子已被导入，结果按中间版保存，不替代最终post-review版。
- 第一稳定版领域81/.23，PG42/10.21，check280/3平台/3契约/10入口，web89/290.811ms/type/lint/build5routes。该版完整回归仍在运行，后独立P2导致代码追加，不代替最终版。
- P64跨组手填两个方向红2/.36；P65直接否定/全无要求红4/9passed/.24；修复后领域72/.23，PG29/2.70。误读RequestView.request第一修复21PG失败已纠正；最后一个mypy对象membership错误改成真实list窄化。
- 工具投影原null回退首18PG/3.05全过；三URL/四元数据完整服务保持，未改其原断言。Web新Comparison默认投影字段在openapi-typescript默认规则仍必填，显式合成TS fixture补null，运行时历史旧模型缺字段仍默认读。
- 一次web-generate误设web cwd导致.cache重定向失败，一次启动误猜依赖bin/node不存在；都未执行目标操作。重读目录确认实际/opt/homebrew/bin/node并已成功启动本地Web，无安装/权限变更。
- 首红PG1 failed/0.29s（缺偏好不拒绝）；领域初collection缺模块不算业务红，空实现后7 failed/.06；相关领域80 passed/.23。
- 第一PG35例3失败：新测试误读RequestUpdate.revision改request.revision；两demo为结果过长。直接demo2例1失败明确blocked/结果过长。第一次check mypy五测试错误已定位（返回类型/回执读取），未改业务断言。
- 错方案服务卡去null：40PG38passed/2failed（原T4.2/T4.4显式null断言）；恢复原服务卡，只工具白名单未知展示键可省略，并更新UI可选schema。上限仍8000。
- 保留冻结v1/legacy全部文件与hash，机制种子明确合成无要求；不向eval prepare暗补输入。R6新规格实验前另建版本披露。
- 两次apply_patch上下文不匹配未修改代码，重读精确行再修；一条rg未确认fixture文件、一条shell glob不存在，均只读失败，无数据变化。
