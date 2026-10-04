# 产品 V2 原型实施计划（交给 Codex 实现）

> 状态：**待实施**。读者：实现者（Codex）。目标：用最少改动跑出一个能连**真实数据**的原型。
> 本文取代同目录下 [FRONTEND-REDESIGN.md](FRONTEND-REDESIGN.md) 的视觉部分；[BACKEND-CHANGE-INVESTIGATION.md](BACKEND-CHANGE-INVESTIGATION.md) 是背景调查，仅供参考。
> 标注：**[已核实]** = 读过代码或官方文档；**[待核实]** = 实现时先查证，查证失败就按文中的降级方案处理，不要自行扩展范围。

---

## 0. 目标与验收

**一句话**：模型下拉框里有「离线 / DeepSeek / Claude」三项，未配置的置灰；选 DeepSeek 或 Claude 时，Agent 通过 Google Maps 查真实景点和路线，通过乐天トラベル查真实空房和价格，通过 Open-Meteo 查天气，生成按天行程；确认后可以导出 `.ics` 导入 Google Calendar；关掉浏览器第二天回来还在。

**验收（全部满足才算完成）**
1. `离线` 模式行为与现在**完全一致**，现有测试全部通过（回归是第一道关）。
2. 配好 `DEEPSEEK_API_KEY`、`GOOGLE_MAPS_API_KEY`、`RAKUTEN_APP_ID`、`RAKUTEN_ACCESS_KEY` 后，在 DeepSeek 模式下发送「大阪 11/3 到 11/5，2 个大人，预算 6 万日元，帮我比较酒店并排两天行程」，能看到：
   - 乐天真实酒店卡片：有照片、价格、「去乐天查看」链接，没有「暂留」按钮；
   - 景点来自 Google Places；路段耗时来自 Google Routes；
   - 回复里提到天气；
   - 行程草稿可以确认保存。
3. `GET /models` 能正确反映哪些模型可用；没配 Anthropic Key 时，Claude 选项置灰并显示原因。
4. 已确认的行程能下载 `.ics`，导入 Google Calendar 后每个景点是一个日程。
5. 关掉浏览器重开，页面仍是同一会话、同一行程（30 天内）。
6. 外部 API 失败（没配 Key、超时、429）时，对话里出现一条说明原因的回复，不会出现 500 或白屏。
7. 项目原有检查全部通过（见 §9）。

**明确不做**：登录和邀请码、预订和下单、多 Agent、多家 OTA、跨城市逐段换住宿、会话列表侧栏、Google Calendar OAuth、新的评测集、改动离线脚本与模拟数据。

---

## 1. 技术选型（每类只用一家）

| 能力 | 选用 | 为什么 | 需要的配置 |
|---|---|---|---|
| 地图：地理编码、景点、路线 | **Google Maps Platform**：Geocoding API、Places API (New) Text Search、Routes API `computeRoutes` | 成熟，一个 Key 覆盖三项 | `GOOGLE_MAPS_API_KEY`（在 Google Cloud 项目里启用这三个 API，并绑定结算账户） |
| 酒店 | **乐天トラベル** `VacantHotelSearch` | **[已核实]** 有实时空房、方案、价格、照片、评分和 `reserveUrl`，覆盖全日本；只能查询、不能下单，正好符合需求 | `RAKUTEN_APP_ID`、`RAKUTEN_ACCESS_KEY`，可选 `RAKUTEN_AFFILIATE_ID` |
| 天气 | **Open-Meteo** Forecast API | 不需要 Key，覆盖日本，可预报 16 天 | 无。**[已核实，官方条款]**：免费版仅限非商用（个人项目符合），每天少于 10,000 次；数据按 CC BY 4.0 授权，界面上必须署名 |

**免费额度与计费 [已核实，2026-10-04 读取官方定价页]**

| 服务 | 本项目用到的计费项 | 每月免费 | 超出后（每 1,000 次） |
|---|---|---|---|
| Google Geocoding | Essentials | 10,000 次 | $5.00 |
| Google Places Text Search | **Enterprise**：因为请求了 `regularOpeningHours`，这个字段属于 Enterprise 档；`displayName`、`location`、`types`、`googleMapsUri` 只到 Pro 档 | **1,000 次** | $35.00 |
| Google Routes `computeRoutes` | 基础请求是 Essentials；TRANSIT 是否算更高一档，官方页面没写明（待核实） | Essentials 10,000 次（Pro 5,000、Enterprise 1,000） | $5.00（Pro $10、Enterprise $15） |
| 乐天トラベル | — | 官方页面**没有公开任何价格**；条款写明“如公司另行规定，开发者须支付使用费” | — |
| Open-Meteo | — | 每天少于 10,000 次 | 不适用（非商用免费） |

结论：只要按 §6.5 控制调用次数，个人原型的外部数据费用应为 **$0**。其中最贵、额度最少的是 Places Text Search（每月 1,000 次免费），代码里必须用缓存和调用上限保护它，见 §6.5。**不要在 FieldMask 里加 `places.rating`**：它同样属于 Enterprise 档，而且景点用不到评分。

**乐天条款中会影响实现的部分 [已核实，`webservice.rakuten.co.jp/guide/rule`；英文版仅供参考，以日文版为准]**
- **必须显示署名**（第 13 条和 credit 指南）：使用官方 HTML 片段，**不得修改**。本项目使用文字版：
  `<!-- Rakuten Web Services Attribution Snippet FROM HERE --><a href="https://developers.rakuten.com/" target="_blank">Supported by Rakuten Developers</a><!-- Rakuten Web Services Attribution Snippet TO HERE -->`
  实现前请到 `https://webservice.rakuten.co.jp/guide/credit` 原样复制当时的最新片段。
- **使用乐天 API 的区域内，不得链接到乐天以外的网站**（第 8(4) 条）：酒店卡片上只放 `reserveUrl` 或 `hotelInformationUrl` 这类乐天链接，不要放 Google Maps 链接。
- **不得暗示与乐天有合作关系**（第 10(1) 条）；**不得储存在可被不特定多数人共享的地方**（第 10(9) 条）：报价只作为当前用户自己的证据存入 PG，有效期 15 分钟，不做公开共享的缓存。
- **需要用户确认的风险**：第 10(10) 条禁止“在只有特定人可以访问的环境中使用”，除非乐天许可。如果把应用部署成只有你自己能访问的私有网站，可能属于这种情况。本机开发调试一般理解为开发行为，但官方没有明确说明。正式部署到 Railway 前，建议发邮件向乐天确认，或者把应用设为公开访问。**这一条不影响本计划的实现，只影响部署方式。**
- 联盟推广只能通过“乐天联盟”（第 3、10(4) 条）。`RAKUTEN_AFFILIATE_ID` 为可选项，留空即可。
| 日历 | **`.ics` 文件导出** | 参考仓库 awesome-llm-apps 的 travel planner 也是这么做的 **[已核实，README]**；不需要 OAuth，Google、Apple、Outlook 都能导入 | 无 |

为什么不用 Airbnb 或 Booking：Airbnb 没有公开 API，参考仓库用的社区 Airbnb MCP 并没有说明数据怎么来，可能是抓网页；Booking 的 Demand API 需要合作伙伴资格。乐天是唯一拿到 Key 就能用的真实酒店数据源。

**关于 MCP**：项目里的工具已经通过 Claude Agent SDK 的**进程内 MCP 服务器**提供给模型（`backend/mcp/bridge.py` 的 `build_server`，读取 `backend/tools/contracts.py` 和 `backend/tools/travel.py` 的同一份定义）**[已核实]**。本次新增的天气工具注册到**这一个** MCP 服务器里，地图和酒店替换现有工具背后的数据源。**不新增任何 MCP 服务进程。**

---

## 2. 总体设计：只在“实时线路”背后换数据源

**[已核实]** 现在的执行路径：
- **离线**：`RunService._runtime("offline")` → `FixtureRuntime(TravelToolExecutor(TravelService(db)))`，在 API 进程内执行，读模拟和快照数据。
- **实时**：`GuardedRuntime` → `providers/claude_agent/live.py:run_live` 启动 SDK 子进程 → 子进程内由 `providers/claude_agent/database_tools.py` **另行构造** `TravelToolExecutor`。

所以只要在 `database_tools.py` 构造执行器时注入“真实数据源”，离线路径一行都不用改。

```
离线：   TravelToolExecutor ── HotelService(rates=fixture) ── PlanningService(routes=fixture) ── CatalogService(snapshot)
实时：   TravelToolExecutor ── HotelService(rates=Rakuten) ── PlanningService(routes=Google) ── CatalogService(snapshot + Google Places 写入)
                           └─ get_weather_forecast(Open-Meteo)   [新工具，两条线路都注册；离线返回 unavailable]
```

**实现方式：数据源注入，而不是 if/else 散落各处。**
- 新建 `backend/adapters/live_data.py`，定义一个 `LiveData`（dataclass），字段为 `google: GoogleMaps | None`、`rakuten: Rakuten | None`、`weather: OpenMeteo`。
- `TravelToolExecutor` 的构造函数增加可选参数 `live: LiveData | None = None`，原样传给 `HotelService`、`PlanningService`、`CatalogService`；`None` 就走现有逻辑。
- 只有 `database_tools.py`（实时）传入 `LiveData.from_environment(os.environ)`。

---

## 3. 后端任务（按顺序做，每步都能单独测试）

> **分层硬规则** **[已核实，`pyproject.toml` 的 import-linter 契约，由 `dev check` 强制检查]**：
> - `backend.domain` 不能导入任何项目层。
> - `httpx`、`claude_agent_sdk`、`anthropic`、`mcp` 只能在 `backend.adapters`、`backend.providers`、`backend.mcp` 中导入。
> - `backend.api` 只能经过 `backend.services` 或 `backend.agent` 访问其他层，不能直接导入 providers、adapters、domain、persistence。
>
> 因此：`/models` 的判断逻辑放在 `backend/services/models.py`（由它调用 providers）；`.ics` 生成放在 `backend/services/plans.py`；新的 HTTP 适配器全部放在 `backend/adapters/`。

### B1. 模型三选一

**文件**：`backend/services/runs.py`、`backend/providers/claude_agent/live.py`、`backend/providers/claude_agent/runtime.py`（及 `backend/agent/runtime.py` 中把 prompt 传给 `GuardedRuntime` 的那条路径）、`backend/api/app.py`。

1. `MessageInput.mode`：`Literal["offline","live"]` 改为 `Literal["offline","deepseek","claude"]`。
   - `task_runs.mode` 是 `String(10)`，不需要迁移。
   - 读取旧行时，`RunView.mode` 原样返回 `live`，前端显示为「实时（旧）」。
2. `RunService.submit`：把 `if message.mode == "live" and not self.live_enabled` 改成 `if message.mode != "offline" and not self.live_enabled`，错误文案不变。
3. `RunService._runtime(mode, …)`：`mode == "offline"` 分支不变；其余分支把 provider 传给 `GuardedRuntime`，映射规则是 `deepseek → "deepseek"`、`claude → "anthropic"`。
4. 把 provider 一路传到 `run_live(..., provider: Provider)`。`live.py` 里两处 `load_runtime_settings(os.environ)` 改为 `load_runtime_settings({**os.environ, "LLM_PROVIDER": provider})`。这是**最小改动**：`settings.py` 不用改，两条线路的预算账本各自独立 **[已核实]**（人民币对 DeepSeek，美元对 Anthropic）。
5. 新增 `GET /models`，不需要身份：
   ```json
   [
     {"id":"offline","label":"离线演示","available":true,"reason":null},
     {"id":"deepseek","label":"DeepSeek","available":true,"reason":null},
     {"id":"claude","label":"Claude","available":false,"reason":"未配置 ANTHROPIC_API_KEY"}
   ]
   ```
   - 判断逻辑写成纯函数 `model_options(environment, live_enabled) -> list[ModelOption]`，放在 `backend/services/models.py`；`api/app.py` 只调用这个服务。
   - 对每个 provider 调用 `load_runtime_settings({**env, "LLM_PROVIDER": p})`；抛 `ProbeError` 就记为 `available=false`，`reason` 取 `str(error)`。
   - `live_enabled` 为 false 时，两个模型统一显示「服务未以 --live 启动」。
   - **不返回任何 Key、预算数值或模型 ID 以外的配置。**
6. 测试（`tests/`，参考现有 `test_runs`、API 测试的写法）：
   - 三种 mode 都能提交；
   - 未开启 live 时 deepseek 和 claude 返回 403；
   - `model_options` 覆盖有 Key、无 Key、预算为 0、未开启 live 四种情况；
   - `/models` 的响应里不出现 Key 字符串。

### B2. 去掉城市硬编码（只做日本）

**文件**：`backend/domain/catalog.py`、`backend/domain/hotels.py`、`backend/domain/travel_request.py`、`backend/agent/persona.py`，以及 `tools/travel.py`、`domain/itinerary.py` 里的提示文案。

1. 4 处 `city: Literal["京都"]` 改为 `str`：
   - `TravelConditions.city` 用 `Field(min_length=1, max_length=40)`；
   - `Place`、`Article`、`HotelRate` 的城市字段保留默认值 `"京都"`，这样快照和模拟数据不用动。
   - 时区 `Asia/Tokyo` 和币种 `JPY` **不变**。
2. `domain/catalog.py:search` 的城市归一化保留京都别名，其他城市按原样比较（`casefold`）。
2a. **日本国内任意城市都要能用（实时线路）**。城市的规范化和校验交给 Google Geocoding，不维护城市列表：
   - `GoogleMaps.geocode(city)` 请求时带上 `components=country:JP`。如果结果的 `address_components` 中，`types` 包含 `country` 的那一项的 `short_name` 不等于 `JP`，就抛出 `ServiceError(422, "validation", "目前只支持日本国内目的地")`，模型会据此回复用户。
   - 返回值包含：经纬度；规范名称（用 `locality` 的 `long_name`，没有时退到 `administrative_area_level_1`）；`viewport`。
   - `update_travel_request` 写入城市时**不调用**外部 API，保持现状。城市会在第一次查询景点、酒店或天气时才做地理编码，结果缓存（见 §6.5）。
   - **范围很大的目的地**（比如只说了“北海道”“冲绳”，或 `viewport` 对角线超过 30 km）：景点搜索用 viewport 作为 `locationRestriction`；乐天酒店搜索只覆盖以中心点为圆心、半径 3 km 的范围（这是 API 的上限），覆盖不了整个区域。这时工具结果里加一条 `note: "目的地范围较大，请让用户指定具体城市或区域"`，由模型去追问。
   - 东京、大阪、名古屋、札幌、福冈、那霸、金泽、奈良、神户、箱根这类市区或町村，按中心点处理即可。验收时至少测试 **大阪、札幌、那霸、箱根** 四个地点，见 §6.5 的预算。
3. `persona.py`：
   - 删掉「只支持京都」以及「京都以外先询问是否改京都」这两句；
   - 改成「支持日本国内城市；海外目的地说明暂不支持」；
   - 「没有指定兴趣时用京都作为宽查询」改为「用用户所说的城市作为宽查询」。
4. 提示文案「京都当地时间使用+09:00」改为「日本时间使用+09:00」。
5. 离线演示 `agent/demo.py:82` 的「固定演示仅覆盖京都二至三日游」**保持不变**。
6. **评测影响**：改了 `persona.py` 的提示词，冻结评测（`eval/`）不再可比。不要修改评测用例或历史结果；`tests/test_persona.py` 里断言旧文案的地方按新文案更新，并在提交说明里写明原因。

### B3. 真实景点：Google Places

**新建** `backend/adapters/google_maps.py`，提供类 `GoogleMaps(api_key, http: httpx.AsyncClient)`。`httpx` 已是项目依赖 **[已核实]**，只能在 adapters、providers、mcp 中导入。三个方法：

| 方法 | 端点 | 关键参数 |
|---|---|---|
| `geocode(city) -> GeoPoint(lat, lng, name, viewport)` | `GET https://maps.googleapis.com/maps/api/geocode/json?address={city}&components=country:JP&language=ja&key=…` | 见 B2 第 2a 步的国家校验；结果写入 PG 缓存（§6.5） |
| `search_places(geo, query, limit) -> list[Place]` | `POST https://places.googleapis.com/v1/places:searchText`，请求头 `X-Goog-Api-Key`，以及 `X-Goog-FieldMask: places.id,places.displayName,places.formattedAddress,places.location,places.types,places.regularOpeningHours,places.googleMapsUri`（**不要**加 `rating`，见 §1 的计费表） | 请求体 `{"textQuery": f"{query} {geo.name}", "languageCode":"zh-CN", "regionCode":"JP", "pageSize": min(limit, 8), "locationBias": {"circle": {"center": …, "radius": 15000}}}`；如果是范围很大的目的地，改用 `locationRestriction.rectangle = viewport` |
| `route(origin, dest, transport, departure) -> (minutes, fare)` | `POST https://routes.googleapis.com/directions/v2:computeRoutes`，FieldMask 为 `routes.duration,routes.travelAdvisory.transitFare` | `travelMode`：walk→`WALK`，transit→`TRANSIT`，taxi→`DRIVE`；只有 TRANSIT 传 `departureTime` |

**接入 `CatalogService`（`backend/services/catalog.py`）**：
- 构造函数增加 `live: LiveData | None`。
- `query()` 里，如果是景点查询，并且 `live` 和 `live.google` 都存在，就先调用 `google.search_places(arguments.city, arguments.query, arguments.limit)`。
- 把结果转成 `Place`，用现有的 `persistence.catalog.import_catalog`（幂等）写入 `catalog_entries`，然后**继续走原逻辑**（`search` → `_publish`）。这样 `get_place_facts`、证据、校验、展示全部复用。
- Google 结果转成 `Place` 的规则：
  - `place_id = "gplace:" + id`；
  - `city` = 用户给的城市参数（**不能**用 Google 返回的地址，否则校验器里 `request.city != place.city` 的检查会误判冲突）；
  - `name = displayName.text`，经纬度来自 `location`；`coordinate_kind="node"`；`category = types[0]`；`indoor=None`。
  - `osm_id`：这个字段现在是必填，改为 `str | None = None`。
  - `opening_hours`：把 `regularOpeningHours.periods` 转成现有解析器支持的 OSM 子集字符串（例如 `Mo-Fr 09:00-17:00; Sa 10:00-16:00`）。转换失败就填 `None`，校验器会按“未知”处理，不能当成营业中。
  - `source`：`Source(provider="google_places", source_ref=googleMapsUri, content_version=retrieved_at 的 ISO 字符串, retrieved_at=now, license="Google Maps Platform Terms", license_url="https://cloud.google.com/maps-platform/terms", attribution="Google Maps", data_mode="live")`。
  - 这要求把 `Source.provider` 扩成 `Literal["osm","wikivoyage","google_places"]`，`Source.data_mode` 扩成 `Literal["snapshot","live"]`。
- `EvidenceRecord.data_mode`（`domain/evidence.py:29`）扩成 `Literal["fixture","snapshot","live"]`。全仓库搜索对 `data_mode` 取值做判断的地方（包括 `persona.py` 里「fixture 必须注明…」那条规则），给 `live` 补上一句：「live 为第三方实时数据，注明来源与查询时间」。
- 失败处理：Google 超时、429 或非 2xx 时，**不要抛异常中断**；记一条日志后回退到现有快照查询。快照里没有这个城市就返回空结果，现有逻辑会提示没找到。

### B4. 真实路线：Google Routes

**文件**：`backend/services/planning.py`（`routes()` 方法，约第 32–75 行）**[已核实]**。

- 构造函数接收 `live`。`live.google` 存在时，不调用 `load_routes()` 和 `estimate()`，而是对每一段调用 `google.route(...)`。
- 起终点坐标取自 place 证据记录里的经纬度：`record.value["latitude"]`、`record.value["longitude"]`。
- 生成 `RouteEstimate`：
  - 有耗时：`minutes = ceil(duration 秒数 / 60)`，`confidence="estimate"`；
  - 有 `transitFare` 时 `fare = 单人票价 × 人数`（人数 = `adults + len(child_ages)`），否则 `fare=None`（**[已核实]** 这个字段本来就可以为空）；
  - 失败时 `confidence="unknown"`，`minutes=None`，`fare=None`。
- 证据记录：`provider="google_routes"`，`source_ref="google:routes"`，`data_mode="live"`，有效期 15 分钟（与现在一致）。

### B5. 真实酒店：乐天

**新建** `backend/adapters/rakuten.py`，提供类 `Rakuten(app_id, access_key, affiliate_id, http)` **[已核实，官方文档]**：
- 端点：`GET https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426`
- 参数：`applicationId`、`format=json`、`formatVersion=2`、`checkinDate`、`checkoutDate`、`adultNum`、`roomNum`、`latitude`、`longitude`、`datumType=1`（WGS 坐标，单位为度）、`searchRadius=3`、`hits=10`、`responseType=large`，可选 `affiliateId`。
- 请求头：`accessKey: <RAKUTEN_ACCESS_KEY>`。
- **响应的嵌套结构文档里没写明**。先用乐天的 API 测试页抓一份真实响应，存到 `tests/fixtures/rakuten_vacant_sample.json`，再按它写解析和测试。

**总价口径（必须遵守）**：
- 文档写明 `dailyCharge` 只有**第一晚** **[已核实]**，`rakutenCharge` 的含义取决于 `chargeFlag`：0 表示每人，1 表示每间房。
- 算法：
  1. 第 1 晚按经纬度搜索，得到候选的 `(hotelNo, planId, roomClass)`。
  2. 第 2 到第 N 晚，用 `hotelNo` 列表（每次最多 15 个）加上当晚的入住和退房日期再查一次，按 `(hotelNo, planId)` 匹配。
  3. 每晚价格 = `rakutenCharge × (adults if chargeFlag==0 else rooms)`，多晚相加。
  4. 任何一晚匹配不到，或 `child_ages` 不为空（儿童价格口径未知），就 `total=None`，`comparison.reasons` 写明原因。
  5. 最多 7 晚，超过就 `total=None`。
- 税费：乐天的价格已经含税和服务费。`tax_amount` 和 `fee_amount` 设为 `None`，界面显示为“含税，明细未知”，现有界面已经支持未知值。
- 乐天返回的 `latitude`、`longitude` 不使用。

**接入 `HotelService`（`backend/services/hotels.py:_quote`，约第 46–86 行）[已核实]**：
- `live.rakuten` 存在时，先用 `google.geocode(request.city)` 拿到经纬度，再调用乐天。
- 结果直接构造成与 `quote()` 返回值**同类型**的报价对象（先读 `domain/hotels.py` 里 `quote()` 的返回类型和必填字段），然后组装 `EvidenceRecord`：
  - `provider="rakuten_travel"`
  - `source_ref = hotelInformationUrl`
  - `content_version = 查询时间`
  - `valid_until = now + 15 分钟`
  - `data_mode="live"`
- 要给界面看的新字段：`image_url`（取 `hotelImageUrl`）、`review_average`、`booking_url`（取 `reserveUrl`，没有就用 `planListUrl`）。
  - 把这三个字段作为**可选字段**加到报价模型和 `UiHotelCard`（由 `services/hotels.py:cards()` 生成）上。
  - 然后执行 `uv run python scripts/dev.py web-generate` 重新生成前端类型，**不要手改** `apps/web/src/lib/api-types.ts`。
- 失败处理（乐天 429、超时、没配 Key）：抛出现有的 `ServiceError(503, "unavailable", "乐天酒店查询暂不可用：<原因>")`，模型会看到错误结果，并在回复里说明。

**去掉实时线路的预订**：
- 在 `live.py` 组装 `definitions` 时（约第 88 行）**[已核实]**，过滤掉 `hold_hotel`。
- `bookings` 表、`mock_supplier` 和相关测试**全部保留**，离线线路也不变。

### B6. 天气工具（新增一个工具）

- 新建 `backend/adapters/open_meteo.py`，调用 `GET https://api.open-meteo.com/v1/forecast?latitude=&longitude=&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia/Tokyo&start_date=&end_date=`。
- 在 `backend/tools/travel.py` 里新增 `ToolDefinition("get_weather_forecast", "按当前旅行条件的城市与日期查询每日天气预报；超过16天或未定日期返回unknown。", kind="read")`。
  - 参数只有 `expected_revision`，城市和日期从服务端的当前条件读取，不接受模型直接传入。
  - 返回每日的最高温、最低温、降水概率和天气描述（把 WMO 天气代码映射成中文）。
- 离线线路（`live is None`）返回 `unavailable` 和“离线模式不提供天气”。
- 在 `persona.py` 加一句：规划户外景点前先查天气，降水概率 ≥ 60% 的那天优先安排室内景点。
- 不做天气卡片，只在文字回复里体现。

### B7. 日历导出

- 新增 `GET /plans/{plan_id}/calendar.ics`，鉴权和归属检查复用 `GET /plans/{plan_id}`；生成逻辑放在 `PlanService.calendar()`（`backend/services/plans.py`），API 层只调用它。
- 用标准库手写 iCalendar（不新增依赖）：
  - 每个行程项生成一个 `VEVENT`，包含 `UID={item_id}@travel-agent`、带时区的 `DTSTART` 和 `DTEND`（`TZID=Asia/Tokyo`，同时写一段 `VTIMEZONE`；或者全部转成 UTC 加 `Z`，这种写法更简单）、`SUMMARY=name`、`DESCRIPTION=source_ref`。
  - 换行用 CRLF，文本按 RFC 5545 转义（`,`、`;`、`\`、换行）。
- 响应：`Content-Type: text/calendar; charset=utf-8`，`Content-Disposition: attachment; filename="trip-v{version}.ics"`。
- 测试：生成的文本包含 N 个 `VEVENT`、特殊字符已转义、别人的计划返回 404。

### B8. 跨天保留会话（最小做法）

- 令牌有效期：`services/sessions.py:create_demo_user` 里写死的 `timedelta(hours=24)` 改为读环境变量 `DEMO_TOKEN_DAYS`，默认 30 天。
- 前端会把令牌改存到 `localStorage`，见 F5。
- **不做**会话列表接口。

### B9. 把密钥传进 SDK 子进程（容易漏）

- **[已核实]** 工具在 SDK 子进程里执行，子进程的环境变量由 `providers/claude_agent/environment.py:worker_environment` 按**白名单**构造。
- 在白名单里加上 `GOOGLE_MAPS_API_KEY`、`RAKUTEN_APP_ID`、`RAKUTEN_ACCESS_KEY`、`RAKUTEN_AFFILIATE_ID`，否则实时线路拿不到这些 Key。
- 不要把 `DEEPSEEK_API_KEY` 和 `ANTHROPIC_API_KEY` 加进白名单：它们只在 API 进程的守卫代理里使用。

---

## 4. 前端任务（apps/web）

依赖关系：F1 和 F2 依赖 B1；F3 依赖 B5 和重新生成的类型；F4 依赖 B7；F5 和 F6 没有依赖，可以先做。

### F1. 模型选择器（替换现有 `<select>` 和计费勾选）
- **文件**：`components/composer.tsx`、`components/workbench.tsx`；新建 `lib/models.ts`。
- 页面加载时调用 `GET /api/models`（同源，经 Next 的 rewrite 转发）。请求失败时只显示「离线」一项，标为可用。
- 自定义下拉菜单（按钮加弹出列表，键盘上下键可选，`role="listbox"`），三项依次是：
  - 离线演示 · 免费 · 模拟数据
  - DeepSeek · 实时数据 · 按 API 计费
  - Claude · 实时数据 · 按 API 计费
- `available=false` 的项：文字变淡、不可点击，下面一行小字显示 `reason`。
- 默认选中值：上次的选择（存 `localStorage`）；如果它不可用，就选第一个可用项。
- **删除** `liveConsent` 状态和「允许本条消息计费」勾选，以及它关联的所有 disabled 条件。`workspace.send(text, mode)` 的 `mode` 类型改为 `"offline" | "deepseek" | "claude"`。
  - 注意 `lib/use-workspace.ts` 里 `send()` 的签名和 `pending_message.mode`。旧标签页里存的 `"live"` 读出来时按不可重试处理：显示提示，并清掉 pending。
- 发送失败（HTTP 403、503 等）：在对话里显示一条失败样式的助手回复，内容是服务端返回的 `message`，而不是只显示顶部横幅。

### F2. 删除「Agent 活动」顶部按钮
- 删除 `components/activity-drawer.tsx` 在工具栏上的入口。
- 每条助手回复下方加一行可折叠的「执行了 N 步 ▸」，展开后显示步骤列表：中文工具名（`components/tool-names.ts`，补上 `get_weather_forecast` → "查询天气"）以及 ✓ / ✗。
- 数据仍然来自 `workspace.events`。

### F3. 酒店卡片（真实数据）
- **文件**：`components/results.tsx` 的 `Hotel` 和 `HotelResults`。
- 有 `image_url` 时，顶部显示 16:10 的图片：`<img loading="lazy" referrerPolicy="no-referrer">`。**不要用 `next/image`**，那样需要配置远程域名白名单。
- 显示评分 `★ 4.3`。
- 价格加千分位，统一用一个 `formatYen()` 函数：`Number(value).toLocaleString("ja-JP")`。这只用于显示格式，金额本身仍是后端给的字符串，不要拿它做任何计算。
- 有 `booking_url` 时，主按钮是「去乐天查看 ↗」（`target="_blank" rel="noopener noreferrer"`），并且**不渲染**「暂留模拟房间」按钮；没有 `booking_url` 的离线卡片保持现状。
- 标签：离线卡片显示「模拟报价」，`data_mode` 为 `live` 的卡片显示「乐天实时」。卡片区域底部原样放入乐天官方的署名片段（见 §1 的「乐天条款」，**不得修改**）。在 React 里写成 `<a href="https://developers.rakuten.com/" target="_blank" rel="noopener">Supported by Rakuten Developers</a>`，文字和链接地址都不能改，两侧加上官方要求的注释。实现前从 credit 页面再核对一遍。
- 乐天卡片区域内**只能出现乐天的链接**（第 8(4) 条），不要放 Google Maps 链接。
- 天气署名：只要回复用到了天气，就在页脚的「数据说明」里加上「天气数据：Open-Meteo.com（CC BY 4.0）」，链接到 `https://open-meteo.com/`。景点和路线的「来源与版本」里写「Google Maps」。

### F4. 日历导出按钮
- 已确认的正式行程（`!plan.draft_id`），在 `PlanResults` 头部和 `/plans` 页加「导出到日历 (.ics)」按钮。
- 实现：带 `Authorization` 头 `fetch('/api/plans/{plan_id}/calendar.ics')`，转成 Blob 后下载。不能用 `<a href>`，因为它带不上令牌。
- 下面加一行小字：「下载后在 Google Calendar →设置→导入」。

### F5. 跨天保留
- `lib/use-workspace.ts`：`STORAGE` 用 `localStorage` 读写，替换 `sessionStorage`（第 48、62、150、154 行附近）**[已核实]**；键名改为 `travel-demo-v2`，避免读到旧格式。
- `apps/web/tests/recovery.test.ts` 如果断言了 `sessionStorage`，同步修改。

### F6. 视觉：简洁现代风（不要暖色，不要手账风，不要刻意做日本特色）
参考对象：Linear、Vercel、ChatGPT 网页版这类中性、干净、留白多的界面。
- 在 `app/globals.css` 的 `:root` 里**替换**为：
  ```css
  :root {
    --bg: #ffffff; --bg-subtle: #f7f7f8; --surface: #ffffff;
    --ink: #18181b; --ink-2: #3f3f46; --muted: #71717a; --faint: #a1a1aa;
    --line: #e4e4e7; --line-strong: #d4d4d8;
    --accent: #4f46e5; --accent-hover: #4338ca; --accent-soft: #eef2ff;
    --ok: #16a34a; --warn: #d97706; --danger: #dc2626;
    --radius: 12px; --radius-sm: 8px;
    --shadow-sm: 0 1px 2px rgb(0 0 0 / .05);
    --shadow: 0 1px 3px rgb(0 0 0 / .06), 0 8px 24px rgb(0 0 0 / .06);
  }
  body { background: var(--bg); color: var(--ink); font-size: 15px; line-height: 1.65; }
  ```
- 字体：在 `app/layout.tsx` 用 `next/font/google` 加载 `Inter`（拉丁字母）和 `Noto Sans SC`（中文），设为 CSS 变量。这是 Next 自带的，不新增 npm 依赖。字号最小 12px，正文 15px，区块标题 16px/600，页面标题 22px/650。
- 布局（保持现有三栏结构）：对话区最宽 760px，居中；右侧行程面板背景 `--bg-subtle`，左边一条 1px 分隔线；去掉卡片的厚边框，改用 `--line` 加 `--shadow-sm`。
- 按钮：主按钮用 `--accent` 实心白字，次按钮白底加 `--line-strong` 描边，高 36px，圆角 `--radius-sm`。
- 输入框：一个整体圆角卡片，`textarea` 自动增高、不能拖拽（`resize:none`），底部一行放模型选择器和发送按钮。
- **必须修复的截图问题**（来自 2026-10-04 的实际截图）：
  1. 「旅行条件」只出现一次：摘要和表单不能同时显示，「编辑」打开表单，保存成功后自动回到摘要。
  2. 空值不显示：新会话的摘要显示「还没有设定条件，直接在对话里告诉我」，不要拼出「· —」「间房数未知 · 间 · ¥ · 出发」。
  3. 时间显示 `09:00`，不要显示 `09:00:00`；价格加千分位。
  4. 示例按钮在第一条消息发出后仍然可以使用：收进输入框左侧的「💡 示例」按钮。
  5. 条件表单里的城市改成可编辑输入框，默认「京都」，删除 `conditions.tsx` 里写死的 `city: "京都"`。
- 不做暗色模式。

---

## 5. 配置清单（`.env.example` 增加以下项，只写变量名和注释，不写真实值）

```
# 真实模型（任选其一或都配；选择器会自动置灰没配的）
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=
DAILY_BUDGET_CNY=
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=
DAILY_BUDGET_USD=
# 真实数据（仅 DeepSeek/Claude 模式使用）
GOOGLE_MAPS_API_KEY=
RAKUTEN_APP_ID=
RAKUTEN_ACCESS_KEY=
RAKUTEN_AFFILIATE_ID=
# 会话保留天数
DEMO_TOKEN_DAYS=30
# 外部 API 每日调用上限（见 §6.5）
GOOGLE_GEOCODE_DAILY_CAP=50
GOOGLE_PLACES_DAILY_CAP=25
GOOGLE_ROUTES_DAILY_CAP=150
RAKUTEN_DAILY_CAP=150
WEATHER_DAILY_CAP=200
```

启动实时线路：`uv run python -m backend.server --live`（已有参数）。

---

## 6. 测试要求

- **默认测试不能访问外网**（项目现有规则：`dev test` 排除 `live` 标记）。所有适配器都用录制的样本做单元测试：`tests/fixtures/google_places_sample.json`、`google_routes_sample.json`、`rakuten_vacant_sample.json`、`open_meteo_sample.json`。可以用 `httpx.MockTransport`，或沿用项目已有的打桩方式。
- 每个适配器至少覆盖：正常解析；字段缺失；超时；429；非 2xx。乐天还要加上：`chargeFlag` 为 0 和 1、多晚中缺一晚、带儿童，这三种情况都要得到 `total=None`。
- Google 营业时间转换：普通时段、跨午夜、全天营业、缺少 `periods`。
- 回归：离线三条演示脚本（比较酒店、生成行程、修改第二天下午）的现有测试必须原样通过。

### 6.5 真实 API 联调：既要保证真能调通，又不能多花钱

目标：每个阶段结束时，都要证明真实 API **确实被调用并成功返回**；但调用次数要有硬上限，只要不超过免费额度，就不会产生费用。

**A. 代码里的硬性保护（属于 B3–B6 的一部分，必须实现）**
1. **调用计数表**：新增迁移 `0011_external_api_usage`，建表 `external_api_usage(day DATE, api VARCHAR(20), calls INT, PRIMARY KEY(day, api))`。`api` 的取值为 `geocode`、`places`、`routes`、`rakuten`、`weather`。
   - 每次真正发出 HTTP 请求**之前**，在同一个事务里执行 `INSERT … ON CONFLICT DO UPDATE SET calls = calls + 1 RETURNING calls`。结果超过上限就**不发请求**，直接返回 `unavailable`，原因写「今日 X 调用已达上限」。
   - 实时工具运行在 SDK 子进程里，内存计数无法在多次运行之间共享，所以必须用 PG。
2. **每日上限**，用环境变量配置，默认值如下：

   | 环境变量 | 默认 | 说明 |
   |---|---|---|
   | `GOOGLE_GEOCODE_DAILY_CAP` | 50 | 免费额度为每月 1 万次 |
   | `GOOGLE_PLACES_DAILY_CAP` | 25 | **最关键**：每月免费 1,000 次 ÷ 30 天 ≈ 33 次，留出余量 |
   | `GOOGLE_ROUTES_DAILY_CAP` | 150 | 免费额度为每月 1 万次；按 Enterprise 档的每月 1,000 次估算也不会超 |
   | `RAKUTEN_DAILY_CAP` | 150 | 官方没有公开限额，自我约束 |
   | `WEATHER_DAILY_CAP` | 200 | 远低于每天 1 万次 |

3. **单次对话上限**：每次 run 最多调用 Places 3 次、Routes 12 次、乐天 `住宿晚数 + 1` 次、Geocode 2 次、天气 1 次。超过的部分返回 `unavailable`。在 `TravelToolExecutor` 里按 run 计数即可，单次 run 在一个子进程内完成。
4. **缓存**：先查缓存，命中就不计数、也不发请求。

   | 数据 | 缓存位置 | 有效期 |
   |---|---|---|
   | 地理编码 | 新表 `geocode_cache(query PK, payload JSONB, fetched_at)` | 30 天 |
   | 景点 | `catalog_entries`（已有），需要新增一列 `fetched_at`，或者把 `retrieved_at` 写进 `payload` | 7 天 |
   | 路线 | 不缓存 | 证据本身已有 15 分钟有效期 |
   | 酒店 | 不缓存 | 乐天第 10(9) 条限制储存；报价只作为当前用户的证据，15 分钟有效 |
   | 天气 | 以 `(城市, 日期范围)` 为键，存入证据或内存 | 3 小时 |

   **[待核实]** Google Maps Platform 条款对缓存的限制：一般理解是 `place_id` 可以长期保存，其他内容有时长限制。实现前请查阅 Google Maps Platform 服务条款中的缓存条款。如果条款更严格，就缩短景点缓存的有效期，但不能取消缓存。
5. **Google Cloud 控制台的额外防线**（由用户操作，写在 §10）：给每个 API 设置每日配额，并设置预算提醒。即使代码有 bug，Google 侧也会拒绝超量请求。

**B. 测试分三层，费用逐层增加**

| 层 | 内容 | 外部调用 | 何时运行 |
|---|---|---|---|
| L1 单元测试 | 所有适配器、计费保护、缓存，用 `tests/fixtures/*_sample.json` 录制的样本和 `httpx.MockTransport` | **0 次** | 每次提交（`dev test`） |
| L2 接口探针 | `tests/live/test_real_apis.py`，标记 `@pytest.mark.live`；每个 API **只调用 1 次**：Geocode「大阪」、Places「大阪 美术馆」(pageSize=3)、Routes 一段、乐天 1 晚、天气 1 次。断言 HTTP 200 并且关键字段存在；同时把响应脱敏后**更新 L1 用的样本** | **5 次** | 每个阶段结束时**最多 1 次**：`.venv/bin/python -m pytest -m live tests/live/test_real_apis.py -q` |
| L3 端到端冒烟 | 新增 `scripts/smoke_live.py`：创建会话 → 用 DeepSeek 模式发 1 条规划消息（大阪 2 晚 2 人）→ 等待完成 → 打印本次 run 用到的工具，以及 `external_api_usage` 当天各 API 的增量 | 约 Geocode 1、Places ≤3、Routes ≤12、乐天 ≤3、天气 1；另有 DeepSeek 若干次请求 | 阶段 3 和阶段 4 结束时各 **1 次**；最终验收时对 §2a 的 4 个城市各跑 1 次 |

**C. Codex 执行联调时必须遵守**
- **L2 和 L3 运行前要告诉用户**，用户同意后再执行；**禁止**放进循环、重试脚本或 CI。
- L3 失败时，**先读日志和 L2 的输出定位问题**，用 L1 样本修复并验证，**不要反复重跑 L3 来试错**。同一个问题最多再跑 1 次 L3 确认修复。
- 每次 L2 和 L3 运行后，在 `docs/operations/` 追加一条记录：时间、命令、各 API 调用次数、成功或失败、DeepSeek 的费用估算（取自现有预算账本）。
- 整个 V2 开发周期的总预算参考：Places ≤ 100 次，其余各 API ≤ 300 次，L3 ≤ 10 次。这些数字都远低于免费额度。

## 7. 部署到 Railway（最后做，可单独推迟）

- 三个服务：`web`（`docker/web.Dockerfile`）、`api`（`docker/backend.Dockerfile`）、Railway Postgres。
- 必要的代码改动：
  - `backend/server.py`：端口改为读 `PORT` 环境变量（默认 8000）；`--host` 的可选值加上 `::`。
  - `apps/web/next.config.ts`：放宽 `TRAVEL_API_ORIGIN` 的校验，允许 `http://*.railway.internal:<port>`。
  - `api` 服务的启动命令先执行迁移和导入：`python -m alembic -c backend/persistence/alembic.ini upgrade head && python -m data.import_catalog && python -m backend.server --live --host ::`。
  - 数据库地址用 Railway 注入的 `DATABASE_URL`，`persistence/database.py` 已经支持 **[已核实]**；注意把 `postgresql://` 转成 `postgresql+psycopg`，代码里已有这一步。
- **[待核实]**：`claude-agent-sdk` 的 Linux wheel 是否自带 CLI。macOS 环境里已确认有 `_bundled/claude`；镜像构建后执行 `python -c "import claude_agent_sdk, pathlib; ..."` 确认。没有的话，在后端镜像里 `npm i -g @anthropic-ai/claude-code`，并设置 `TRAVEL_CLAUDE_CLI` 指向它。
- 不部署 `mock_supplier`。
- 没有登录：这个 URL 公开后谁都能用。用户已明确接受这个风险（只有自己用），成本由每日预算账本兜底。可以在 Railway 设置里不生成公网域名，只在需要时临时开启。

## 8. 实施顺序

| 步 | 内容 | 预计 |
|---|---|---|
| 1 | B1 + B9 + F1 + F2（模型三选一，删除计费勾选） | 0.5–1 天 |
| 2 | B2 + B3 + B4 + §6.5-A（城市、Google 景点和路线、调用计数、上限与缓存） | 1.5–2 天 |
| 3 | B5 + F3（乐天酒店和卡片） | 1 天 |
| 4 | B6 + B7 + B8 + F4 + F5（天气、日历、跨天） | 0.5–1 天 |
| 5 | F6（视觉和截图问题） | 0.5–1 天 |
| 6 | §7 Railway | 0.5 天 |

每一步完成后单独提交，提交说明写清楚做了哪些步骤。第 2、3、4 步结束时，按 §6.5-B 各运行 1 次 L2；第 3、4 步结束时各运行 1 次 L3；最终验收时，对 B2 第 2a 步列出的 4 个城市各运行 1 次 L3。

## 9. 每一步完成时都要运行（用项目自己的命令，贴出真实输出）

```
uv run python scripts/dev.py check      # ruff、格式、mypy 三个平台、分层契约、文档地图
uv run python scripts/dev.py test       # 全量 Python 测试（不含 live）；集成测试需要本机 PG 5434
uv run python scripts/dev.py web-check  # 前端 typecheck / lint / test / build
```
- 本机注意：`uv run` 如果因为全局 `exclude-newer` 解析失败，改用 `uv sync --frozen` 后执行 `.venv/bin/python scripts/dev.py <cmd>`；前端可以用 `corepack pnpm run <script>`。**不要**修改 `uv.lock`、`pyproject.toml` 的依赖版本，也不要改 `apps/web/pnpm-lock.yaml`。
- 新增依赖之前先确认现有依赖能不能满足；确实要加，就按项目规则在 `docs/adr/` 写一份 ADR。
- 不修改 `AGENTS.md`、`PROJECT_STATUS.md` 的已有结论；完成后在 `PROJECT_STATUS.md` **末尾**追加一段带日期的「V2 原型变更」说明。

## 10. 开始前需要用户准备
**账号建议：这是个人作品集项目，建议两个服务都用个人账号**（理由见对话记录：费用和条款责任应归个人，避免占用公司资源）。

1. **Google Cloud**（个人 Google 账号即可）
   - 新建项目，启用 **Geocoding API**、**Places API (New)**、**Routes API**。
   - 创建结算账户并绑定信用卡：Maps Platform 需要结算账户。
   - 创建 API Key，在「API 限制」里只勾选这三个 API；如果是从本机调用，再加上 IP 限制。
   - **APIs & Services → 每个 API 的 Quotas** 里设置每日上限，作为代码之外的第二道防线：Places Text Search 30 次/天，Geocoding 50 次/天，Routes 200 次/天。
   - **Billing → Budgets & alerts** 新建预算，金额设为 $1，并在 50% 和 100% 时发邮件提醒。
2. **乐天 Developers**（需要乐天会员账号，个人可以注册）
   - 在 `https://webservice.rakuten.co.jp/app/create` 注册应用，必填项有：应用名称、应用 URL（本机开发可以先填 GitHub 仓库地址）、应用类型、允许的网站、数据用途、预计 QPS（填 1）。
   - 拿到 `applicationId` 和 `accessKey`。
   - 部署到 Railway 之前，按 §1 的说明就第 10(10) 条（是否允许只有特定人访问的环境）向乐天确认。
3. **DeepSeek**：使用现有的 Key 和预算配置。Claude 可以暂时不配，这时选择器里它显示为灰色。
