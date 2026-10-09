# 产品 V2：实现与验收范围

> 更新：2026-10-04。本地核心功能已实现并真实跑通；Railway V2 发布、Claude API 和 V2 同轮 Cloud trace 实测仍未完成。
> 本文收敛原实施提案，不再把历史任务当待办。实时进度只看 [执行计划](../execution/travel-agent.md)，实际运行证据只看 [V2 验收记录](../operations/product-v2.md)。
> 原 [前端方案](FRONTEND-REDESIGN.md) 和 [后端调查](BACKEND-CHANGE-INVESTIGATION.md) 保留为背景，不再指导本轮开发。

## 1. 已交付的产品行为

用户选择离线或 DeepSeek，提出日本国内旅行需求，Agent 通过现有 Claude Agent SDK 调用工具，返回酒店比较与按天行程；草稿可以确认，正式行程能导出 ICS，浏览器重开后恢复同一会话和行程。

| 原任务 | 最终实现 | 主要入口 |
|---|---|---|
| B1、F1 模型选择 | 离线 / DeepSeek / Claude；不可用项置灰并说明原因；删除逐条计费勾选 | `backend/services/models.py`、`apps/web/src/components/composer.tsx` |
| B2 日本目的地 | Google 地理编码限定日本；海外拒绝；北海道、冲绳等大区域追问住宿城市；大阪、札幌、那霸、箱根已真实验证 | `backend/adapters/google_maps.py` |
| B3、B4 景点和路线 | Places (New) 搜索与营业时间；Routes 时长和可取得的票价；缺失或失败保持未知，历史快照降级明确标来源 | Google 适配器、既有目录与规划服务 |
| B5、F3 乐天酒店 | 实时空房、照片、评分、乐天链接；同酒店/方案/房型逐晚核算；儿童或缺一晚等口径不明时不编造总价；实时卡片没有模拟暂留按钮 | `backend/adapters/rakuten.py`、`backend/services/hotels.py`、`components/results.tsx` |
| B6 天气 | Open-Meteo 16天预报；超出范围明确未知；按城市和日期范围在 PG 共享缓存3小时 | `backend/adapters/open_meteo.py` |
| B7、F4 日历 | 正式行程导出 RFC5545 ICS，每个景点一个事件；已实际导入个人 Google Calendar，6/6 活动成功 | `backend/services/calendar.py`、`backend/services/plans.py` |
| B8、F5 跨天恢复 | 默认30天身份；localStorage 保留身份、会话和模型选择；重启前后正式行程读回已验 | `backend/services/sessions.py`、`apps/web/src/lib/use-workspace.ts` |
| B9 SDK环境 | 数据密钥与配额经既有白名单传给 SDK 子进程；模型密钥仍仅在守卫代理使用 | `backend/providers/claude_agent/environment.py` |
| F2、F6 前端 | 回复下展开工具步骤、可编辑城市、示例入口、中性色界面；酒店、景点、路线和草稿可展示及操作 | `apps/web/src/components/` |

离线流程继续使用原 FixtureRuntime 和 Mock Supplier；实时流程复用 GuardedRuntime、进程内 MCP 和既有业务工具。不新增第二套 runtime，不引入新依赖，不重写已工作的模块。

## 2. 存储、缓存和调用边界

Google 存储边界已由用户明确批准：只持久保存 place ID 和不超过30天的经纬度；地点名称、营业时间、完整响应仅在本轮内存使用。取消原提案的完整景点七天缓存。正式行程保存自己的规划与引用，读取时按需取得地点详情；没有详情时保持未知，不伪装成已核实。实时 SDK 会话、checkpoint 和事件中的供应商详情不长期落盘。

| 数据 | 最终位置和有效期 |
|---|---|
| Google ID / 坐标 | `google_coordinates`，坐标30天；不保存完整地理编码响应 |
| Google 地点详情 | 当前 run 内存；跨 run 按需查询，界面读回也消耗 Places 配额 |
| 路线 | 不做共享缓存；持久证据保留引用，详情按当轮使用 |
| 乐天报价 | 当前用户私有证据15分钟，不做公开缓存 |
| 天气 | `weather_forecasts(city,start_date,end_date)`，3小时；迁移 `0012_weather_cache` |
| 请求计数 | `external_api_usage(day,api,calls)`；迁移 `0011_external_api_usage` |

每个真实 HTTP 尝试先用独立 PG 事务扣计数，失败也计数，超限不发请求。缓存命中不扣次数。日上限默认 Geocode 50、Places 25、Routes 150、乐天150、天气200；单 run 上限为 Geocode 2、Places 3、Routes 12、乐天 `min(住宿晚数+1,8)`、天气1。

2026-10-04 用户为最后三城验收明确批准 Places 额外3次：仅后端进程临时设28，完成后已重启恢复25，未改历史计数。今日实际28次，因此恢复后当天新景点查询会被拦截，UTC下一日恢复可用。不得为了演示清账或继续提高额度。

Google 官方政策依据：[Places政策](https://developers.google.com/maps/documentation/places/web-service/policies)、[服务条款](https://cloud.google.com/maps-platform/terms/maps-service-terms)。这项经批准的修正替代旧缓存设计，不属于遗漏。

## 3. 配置和数据来源

个人作品使用个人账号。密钥只填本地 `.env`，不提交或输出到日志：

- Google：`GOOGLE_MAPS_API_KEY`，启用 Geocoding、Places (New)、Routes；绑定结算账户，Key 限制到三项API。控制台每日配额和预算提醒由账号持有人配置；代码配额不能证明控制台设置已完成。
- 乐天：`RAKUTEN_APP_ID`、`RAKUTEN_ACCESS_KEY`；联盟ID `RAKUTEN_AFFILIATE_ID` 可选。`RAKUTEN_REFERER` 必须与应用获准网站一致，服务同时发送 Referer 和 Origin；本地已配置既有注册应用网站。
- DeepSeek：`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DAILY_BUDGET_CNY`，沿用逐HTTP预算账本。
- Claude：`ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`、`DAILY_BUDGET_USD`；未配置或未获美元授权时禁用，本轮没有真实调用。
- `DEMO_TOKEN_DAYS` 默认30；外部API日上限见 `.env.example`。

乐天卡片原样显示 `Supported by Rakuten Developers`，卡片区域只放乐天链接；天气显示 `Open-Meteo.com (CC BY 4.0)`。乐天正式部署的访问方式与条款确认仍属于部署工作，本轮没有修改供应商账号设置或操作真实订单。

定价和免费额度以供应商账单与官方当时规则为准，不能保证绝对零费用；每日限额只是保护措施。模型账本金额是保守上界，不能当供应商实际消费。

## 4. 最少必要验证

默认测试不访问供应商；复用现有异常与业务测试，不扩展 evaluation。

| 层 | 交付入口 | 运行约束 |
|---|---|---|
| L1 | `tests/fixtures/*_sample.json`、现有数据/PG测试 | 四份样本为合成结构，包含正常解析、缺失和错误路径；绝不存原始 Google 详情或真实公开报价 |
| L2 | `tests/live/test_real_apis.py` | 手动指定 `TRAVEL_REAL_API_PROBE` 为 geocode/places/routes/rakuten/weather，一次只测一个接口；默认 live 排除，不放CI |
| L3 | `scripts/smoke_live.py` | 明确 `--execute --city`，只运行单城一轮；记录工具状态、计数增量、模型HTTP和费用上界；失败先定位，不自动重跑 |

Windows 示例（不要循环执行，也不要为已经成功的路径再跑一次）：

```powershell
# 单个真实接口探针，仍须符合授权与当日额度
$env:TRAVEL_REAL_API_PROBE='geocode'
.venv\Scripts\python.exe -m pytest -m live tests/live/test_real_apis.py -q

# 单城真实 SDK/API/PG 冒烟
.venv\Scripts\python.exe -m scripts.smoke_live --execute --city 大阪

# 默认离线检查
.venv\Scripts\python.exe scripts/dev.py check
.venv\Scripts\python.exe scripts/dev.py test
.venv\Scripts\python.exe scripts/dev.py web-check
```

本轮真实流程：大阪在前端完成酒店比较、草稿展示、确认、日历响应和重启读回；札幌、那霸、箱根各完成真实景点/天气/路线工具与行程草稿。那霸主流程遇到酒店不可用后正常降级，另做单晚和两晚接口定位均返回真实酒店；不把这次独立酒店探针写成同轮全成功。日历导入采用离线合成行程验证文件解析，与真实大阪规划验收分别记录。

## 5. 明确保留的范围

- 本地 V2 核心产品完成；Railway 现有站点仍是旧离线 Demo，未发布本轮实时能力。
- Claude 真实 API 与 V2 同轮 Langfuse Cloud 实测未进行；已有接线和历史 Cloud 证据不能代替本轮实测。
- 不做真实订房、付款、跨城市住宿、多 OTA、多 Agent、Calendar OAuth、账号体系或新增评测集。
- 核心 DoD 达成后停止。旧研究性评测记录仅为历史，不恢复为开发任务。
