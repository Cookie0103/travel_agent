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

截至2026-10-04，Railway V2发布、Claude真实API、V2同轮Cloud trace实测未进行。2026-10-05代码发布见下节；云端真实模型/供应商能力仍未开启。核心流程没有已知P0/P1；额度耗尽是实际运行限制，不能通过清账隐藏。旧Cloud证据和已接线代码不能替代本轮实测。

## Railway代码更新（2026-10-05）

用户授权操作其已登录Chrome，将当前本地最新代码发布到既有项目 `449ee30a-0ff4-437a-a35a-53ddc5c4ef93` 的production。三个代码服务原绑定旧前端分支，API上一轮因SupplierClient拒绝固定模拟供应商私网地址而健康失败。按ADR-008只补精确 `supplier.railway.internal`，不放开任意私网/公共域名；无新依赖或runtime。27专项通过、236文件三平台strict及格式/lint/分层/文档检查通过，独立只读窄审查无P0/P1/P2。功能提交 `75318535b5494bd247d862d37eeaeb4146f26080` 的正常check和完整test钩子Passed，普通push成功，ls-remote完整SHA一致。

已将api/web/supplier切到 `batch/2026-10-04-product-v2`，Details核对仅三项Branch变化后Deploy Changes。三个代码服务与Postgres均Online，api/web部署详情链接精确功能提交。该轮部署ID：api `d42e637d-9695-4b20-9035-5dd5431743e0`、web `faf35171-0145-46fe-9f1f-4573a44ea30b`、supplier `18e3a7ed-feb1-4150-af4b-937f947c0279`。保持既有自动部署、Dockerfile、私网代理、迁移/快照导入启动及Postgres卷；以后push同一分支自动更新，新分支须更新三个服务绑定。

公网 [web](https://web-production-0aaac.up.railway.app)：同源health HTTP200/status=ok，models HTTP200且仅offline可用，articles HTTP200/20条。复用 `scripts.smoke_demo`、只在运行时改BASE和STATE，完整core_flows退出0：比较酒店、生成/确认行程、修改第二天下午、模拟供应商确认幂等、非法版本/其他用户拒绝、live拒绝、SSE末次游标读取与恢复均通过。合成身份/模拟订单的私有恢复状态在ignored `.cache/railway-v2-smoke/state.json`，不写入提交或日志。Chrome实际进入最新版工作台，分景点/酒店/天气的数据说明及官方链接均可见。此次0真实模型或旅行数据API调用，不操作真实订单/付款；模型/供应商密钥和.env未上传，云端未以--live启动。

环境恢复：首次正常提交的610项非PG测试通过，187项PG用例因Docker未运行而setup失败；未跳过测试。启动Desktop后发现两处残留AF_UNIX套接字导致后台崩溃。仅元数据检查确认 `C:/Users/user/AppData/Local/Docker/run` 及 `C:/Users/user/AppData/Local/docker-secrets-engine` 含0字节运行时套接字、无凭据/配置/数据后，核对精确绝对路径，原目录重命名备份并重建。保留 `Docker/run.travel-agent-20261005-0310`、`Docker/run.travel-agent-20261005-0311` 和 `docker-secrets-engine.travel-agent-20261005-0311`；未删除任何文件、修改安全设置或触碰数据库卷。Docker28.5.1恢复，dev db-up退出0/既有项目PG Healthy，重新正常提交钩子全部Passed。自动审批拒绝展开云端变量值（可能暴露DATABASE_URL）后保持遮罩，通过日志/健康/既有API脚本完成部署验收，未读取数据库凭据。
