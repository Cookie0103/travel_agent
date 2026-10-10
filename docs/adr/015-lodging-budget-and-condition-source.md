# ADR-015：住宿预算分项、现算预算关系与条件来源

状态：接受，2026-10-08；依据用户 D5/D6/U1、批次 §3.5 与 design/03 §2/§5。先定契约，T3.3/T3.7 实施；不新增依赖或第二套解析运行时。

## 预算模型与选项

全程 `budget`/`currency` 保持现有含义；新增可选 `lodging_budget`：

```json
{
  "amount": {"lower": "20000", "upper": "30000"},
  "basis": "per_room_night",
  "currency": "JPY"
}
```

- amount 用 Decimal；lower/upper 可分别为空，但至少一个非空，已知金额须 >0、最多 12 位/2 位小数，两个均知时 lower≤upper。明确单值“每房每晚3万”存 lower=upper=30000；“不超过3万”只存 upper；“至少2万”只存 lower。不把未说出的端点补成 0。
- basis 是 per_room_night 或 total；currency 为大写三字母币种，由已明确的币种/现有日元场景写入。全程预算仍遵守当前只支持 JPY 的契约；住宿分项可以保留其他明确币种，但与 JPY 不同即无法判断，不换汇、不将其转换为可比较的日元报价。
- lower 是用户预算表达的下限，不是酒店必须花到的最低消费；便宜但合适的酒店仍可推荐。比较报价以住宿上限作上限判断，不按下限排除便宜选项。
- 采用保留区间两端；不选只存上限（无法区分 D6 冲突与警告），不选另存 conflict 布尔标志（可能与值失同步），不选预算冲突拒绝写入（丢失用户事实）。

## 保存与 validator 的唯一判定

Pydantic 仅拒绝结构非法/负数/反向区间/无效日期；两个预算的业务矛盾仍保存。沿用会话行锁、expected_revision、set/clear、规范化后的语义 diff；一次语义更新增加一次 revision，无变化不增。

由一个纯领域计算供 validator、酒店比较前置检查、UI/工具提示共同使用，不在客户端和适配器各算一套，不持久化判定：

| 前提 | 结果与行为 |
| --- | --- |
| per_room_night | 每个已知端点 × rooms × (end_date−start_date 的晚数)；数量未齐则无法判断，不默认 1 房/2 晚 |
| total | 端点本身即住宿总额，无需晚数/房间数 |
| 下限 > 全程预算 | conflict；两个原值保存，先对话追问，以哪个为准；解决前阻止酒店比较（包括绕过先置搜索的直接比较入口） |
| 下限不超/未知，只有上限 > 全程预算 | warning；不升格 conflict，不调整值，告知可超预算的范围 |
| 两个预算任一个未知、必要数量未知、币种不同 | unknown/无法判断；不估算、不换汇、不宣称预算已满足 |
| 已知上限 ≤ 全程预算 | 预算分项上限未超；不能据此宣称实际行程所有费用齐全 |
| 仅下限已知且不超过全程预算 | 上限未知，关系仍不能完整判断；若下限已超仍是 conflict |

当天往返是合法日期；per_room_night 换算为零住宿晚数，沿用酒店前置规则不搜索住宿；不创造住宿报价。total 的用户金额仍原样保存与比较，冲突时追问。

行程 validator 在生成与确认时都检查预算关系。存在 conflict 的草稿 ValidationReport.status=conflict，沿用不可确认规则。范围 warning 用现有 ValidationCheck.status=unknown 配合独立 code/中文“预算警告”说明，汇总 partial（可确认但有未核实风险），不新增第四种 CheckStatus；无法判断同样 unknown，但 code/提示区分。不向旧报告 payload 添加旧 Pydantic 不认识的 severity 字段。

用户回答后仅更新其明确改动的那个字段；例如全程5万、1房、每晚3万、2晚原值都保存，计算6万→conflict；回答“全程改成7万”只改 budget，住宿仍3万，revision 正常增加。每晚2–3万×1房×2晚对全程5万是 warning。只给全程6万时住宿为 null，不按比例拆、不当每晚价。

## 来源与对话提取

- GET request 增量返回 `field_sources`：条件字段名 → conversation/user_form/none；无记录/旧数据/清除字段显示 none，不推测旧值来源。服务端从调用入口确定来源：PATCH API=user_form，update_travel_request 工具=conversation；来源不由模型或表单自由声明。
- 对话工具新增可选 `explicit_fields`（必须是本次 set/clear 字段的子集）。已标 user_form 的字段，只允许属于 explicit_fields 的明确新值覆盖；未声明的推测提取保留原值并要求澄清。明确更新的回执返回实际 changed_fields/来源与“已按对话更新…”提示，助手向用户告知；模糊表述不能假称更新成功。提取仍由现有 SDK/工具契约完成，离线演示复用同一 patch/来源优先规则，不另建通用自然语言解析器。
- 来源入口与规范化后的 explicit_fields 都须参与 operation identity：同一 set/clear 的模糊提取与明确更新可能产生不同结果，不能复用前次 no-op；不另造幂等框架，复用现有 operations.key/result。
- 相同值的确认不增业务 revision；必要的来源标注可在同一事务更新元数据，不使草稿/证据失效。缓存命中不能只据业务 revision 返回旧 field_sources，须从当前行重读来源构造回执；旧操作重试不能覆盖后来更新的来源。clear 删除事实、来源归 none。金额/兴趣来源变化不刷新入住报价，入住条件变化沿用已有 evidence_conditions/invalidated_kinds。

## 持久化、部署与回退

直接把新键写入现有 conditions JSONB 会被旧后端 `extra=forbid` 拒绝，不能称为兼容。因此选一列增量 nullable JSONB `request_details`，仅保存 lodging_budget、field_sources 与来源对应的 revision；既有 conditions JSONB 继续只保存旧模型认识的字段。一个值只有一个持久化位置，不在两列重复保存预算。

T3.3 在现有 Alembic 链增加迁移（届时取下一个编号），保留列与数据、不 drop/reset；旧行 null 读为住宿未知/来源 none；旧 INSERT/UPDATE 不要求新列。新后端从旧 conditions+details 合并模型，写时拆分；若旧后端曾改变 revision，来源 revision 不匹配时仅撤销不可信来源标签，不编造新来源或丢弃住宿金额。

- 旧前端 + 新后端：旧 PATCH 未带住宿字段即保持其值；缺字段不是 clear，新 validator 仍执行 D6。
- 新前端 + 旧后端：返回缺新字段意味着能力未就绪；UI 明确提示新预算/来源功能暂不可用，不能 silently 丢弃住宿金额后声称已保存，也不提交会被旧契约拒绝的新字段。既有条件/对话功能仍可用。涉及未受支持预算能力的比较/确认不冒称已校验。
- 回退保留新列；旧条件可读，新预算细节保留待恢复新版本。证据/草稿内嵌 TravelRequest 的序列化须投影兼容字段，新预算仍以 request_details 为当前事实；旧后端不具备 D6 功能，回退期间 UI 不宣称新预算保证有效。新实现必须测试旧模型实际读回，而非只读 schema 推断。

## T3.3 实施响应与旧快照细节（2026-10-08）

GET request 与 PATCH 回执 request 用只读 RequestView，现算增量 `budget_relation`（status=conflict/warning/unknown/within；换算总额端点、币种、中文说明），输入set仍为TravelConditions，不接受判定字段；关系不写入数据库或operations缓存。工具更新回执/业务上下文和酒店比较沿用同一纯计算。卡片增量nullable `lodging_exceeds_lodging_budget`与比较现算budget_relation用于住宿分项上限/未知提示，保留原全程标记且不改上游顺序、不按下限过滤。旧前端可忽略增量字段；新前端发现lodging_budget/budget_relation缺失明确提示能力未就绪，普通旧字段仍可编辑。

报价Evidence内嵌HotelOffer.request及operations缓存的request投影旧条件字段，住宿金额只在request_details保存。缓存回放读取当前request/details，避免旧operations回执丢住宿字段；保持原revision一致规则。酒店比较以当前request中的住宿上限/币种判断，不以旧报价快照的全程预算替代；入住Evidence条件不包含金额，单独预算更改不刷新入住报价。只读computed响应不向旧ValidationReport加字段，warning/unknown仍映射已有unknown CheckStatus。

## 必须验证

领域：conflict / warning / unknown 各至少一例；相等边界、total 无数量、缺晚数/房间数、不同币种、单端区间、未知预算、Decimal no-op、不排除低价酒店。真实 PG：冲突两值都落库、回答只改指定字段/revision、默认旧行、旧 PATCH 保留新值、来源事务与旧模型读取兼容；同补丁模糊 no-op 后明确更新不复用旧结果、来源 no-op 更新后旧操作重试返回当前来源；确认再校验 conflict。对话/UI：不填表直接发消息、空字段不注入样例、来自对话标签、手填优先/明确改值回执、所有模式共享规则。ADR 确立契约不等于这些实现或实测已完成。

## T3.7 实施来源与离线范围细节（2026-10-08）

RequestView增量field_sources为字段→conversation/user_form/none；metadata只保存已知来源，source_revision等于当前revision才可信，缺失/旧写入者不匹配时统一none。业务更新后沿用未改字段可信来源，来源-only更新同事务但不增加业务revision、不刷新报价。PATCH入口固定user_form；工具ConversationRequestPatch扩展explicit_fields子集，入口固定conversation，无法由输入伪造user_form。手填字段不在explicit_fields时跳过，回执skipped_fields要求澄清；实际更新回执message标“已按对话更新”及真实字段/值，不能假称被跳过字段已更新。

operations.key复用现有规范化，增加入口与规范化explicit_fields维度；旧无来源操作回执仅在还没有来源元数据时兼容回放，不据旧缓存推测标签；新操作重试重读当前来源，保留原revision检查。只存旧request投影/changed_fields/skipped_fields，判定和来源读回不冻结在缓存。

实时提取仍由Claude Agent SDK通过工具完成；固定提示说明每轮从当前用户表达提取、模糊指代追问、未提事实不填。离线仍是已有FixtureRuntime：扩展有限的中文演示表达与样例（包括批次指定札幌/下周末/2成人/5岁/全程8万），驱动同一update工具；只在离线使用，不用于真实模式，也不声称通用自然语言理解。无法识别或未齐条件先在对话里追问，不回退京都/50000、不要求右侧输入；日期相对表达以Asia/Tokyo当前日为基准，“下周末”明确为下个日历周的周六至周日，并在回执显示实际日期以便纠正。显式“改成/改为”列入explicit_fields，模糊样例不覆盖手填。既有演示比较/生成只在其需要的已知条件与支持范围满足时继续，不用隐含京都样例覆盖札幌条件。

有限金额表达必须读取明确币种后缀：住宿三字母币种及日元/美元/欧元/人民币沿用原币种保存，不把未支持后缀吞掉当JPY；当前全程预算契约仍仅JPY，明确非日元时不执行有限提取，直接对话说明边界/要求澄清，原句仍保存于对话历史。没有换汇，也不扩大真实调用。


P56–58补充：有限离线入口支持明确句首城市/目的地冒号及成人标签在数字前，仍不推断未说的字段。数值必须匹配完整token；不支持的中文数词、小数/负人数、人数或房数区间、多不同目的地、明确否定/举例继续在对话澄清，不能截取一个候选数字或城市。住宿预算区间是既有支持格式，保留原两端。explicit_fields只接受对应字段match内部的明确改值词或直接相邻的前置改值词，不能从前8字或其他字段传播授权；来源工具/事务/幂等契约不变。原对话句保留，有限parser不解析复杂作用域，未付费实测通用模型。

T4.5补充：房型偏好复用hard_constraints，有限离线肯定表达映射“住宿：独立房间”“住宿：接受宿舍”“住宿：接受舱房”“房型：禁烟”“床型：双床/大床”；不丢其他硬条件，不从未提及的项设默认。明确改变某组只替换该组，其他组保留；模糊/否定仍追问，不扩用户性别或资格字段。SDK提示同样先澄清偏好、列出用户明确项，不擅自声称房型资格适合。
各组“住宿：无要求”“房型：无要求”“床型：无要求”须用户明确表达，分别算已回答；同组多个不同规范值仍需澄清，不能任取一个。

## B20：有限房型别名规范化（2026-10-09，实施前）

- 沿用三个hard_constraints规范组，不新增第二份房型事实。仅明确房型标签与有限同义词（大床房/大床优先/大床最好、双床房、禁烟房、独立房等）在TravelConditions入界规范化；未知/否定/矛盾不猜。偏好“优先/最好”原文保留为补充约束，不把首选提升为已核实硬性房型适合。
- 读取旧文本、写新值、门禁与资格排序共用规范化，不仅改一个search判定。更改一个房型组时保留其他组/非房型约束；来源与明确字段仍由原服务保护。规范化相同值不增revision；空值仍未知，同组两个不同明确值仍需澄清。
- 分项预算null不阻塞酒店查询；不反复索要可选预算，也不把全程budget复制为住宿金额。餐饮+住宿的范围原话仍只在用户prompt/约束文本保留；本次未添加机器可读budget_scope，不冒称费用范围自动校验能力。

- 独立审查指出只保留未提及房型仍会丢非房型条件。对话hard_constraints改为保留旧未提项、仅替换本次明确房型组；删除具体旧文本新增可选remove_hard_constraints（需hard_constraints在explicit_fields及set中，且文本必须当前存在）。整体清除仍用clear。API手填仍整表set语义；来源守卫先执行，避免新删除字段绕过手填优先。删除列表排序/去重进operation key，空列表省略保持旧key。单字段回答、明确删除、no-op及旧操作兼容需PG回归。

- 真实DeepSeek合成两轮仍失败（原尝试保留）：它输出“住宿：独立房间，不接受宿舍青旅”，固定组未识别，第二轮又追问住宿。仅别名不足，工具ConversationRequestPatch新增room_preferences（lodging=private/dorm/capsule/any、smoking=nonsmoking/any、bed=twin/double/any）。这是输入投影，不新增持久房型事实；严格枚举先验证后映射既有hard_constraints组，返回当前房型投影。明确填值与泛型硬文本冲突时拒绝工具参数，先由模型修参数，不再将参数格式错误转嫁用户。手填/explicit_fields守卫与原revision保持。
- 旧复合文本只兼容“明确独立房间 + 明确不接受宿舍/青旅”的有限格式，不泛化到任意矛盾句；原词保留，canonical仅派生。合法旧20项不因附加规范词超出原上限而变不可读，在边界保原文本，通过同一词表派生识别，旧schema仍可读。

- typed投影跳过已有同一规范值，合法20项同值no-op不因重复追加成为21项；同组冲突仍拒绝，上限不扩大。


## P74：住宿查询地点与旅行目的地分离（2026-10-09，实施前）

- 增量可空条件 `hotel_search_location`（1–40字符），表示用户明确指定的酒店搜索城市/地点，不是整趟旅行目的地。工具沿现有set/clear/explicit_fields、HTTP PATCH来源、CAS和幂等语义保存，未提不默认；不得将机场起终点自动变为住宿区域，也不得默认把冲绳改成那霸。回执标“住宿查询地点”。前端旧表单忽略该增量字段即可，未带即保留。
- 仅在现有request_details保存该事实；legacy_request/LegacyRequestSnapshot投影排除它，旧conditions/报价请求/草稿/operations形状保持。details用hotel_search_city绑定当时旅行目的地（归属元数据），读时若与当前city不一致则不恢复过时地点；修改/清除city时，未同时明确提供新住宿地点则清除旧地点和来源。复用已有列，无表/迁移/依赖。
- 宽区域判定从Google适配器移到纯domain函数，Google、会话和酒店查询共用同一有限词表。在live酒店模式，宽区域city且无具体hotel_search_location时，conversation.missing_fields含hotel_search_location，hotel不ready，awaiting_field允许该值；如果该值也仍是宽区域，仍需细化。fixture酒店维持原支持范围；行程是否ready按原条件独立判断，不强迫具体城市覆盖全旅行目的地。
- 查询/刷新在任何外部请求前按同一判定给固定 `hotel_search_location_required`/validation；成功查询geocode使用住宿地点或原具体city，报价/行程city不被临时改写。酒店证据条件仅在该字段非空时包含它，以保持原无地点证据形状；更改地点失效酒店证据，不失效无关路线/景点。不能放宽原Rakuten宽区域门禁。
- 必须验证真实PG恢复、短答来源保护/no-op/清除与city改变、旧conditions/报价shape兼容；零HTTP拒绝、geocode使用指定地点、空/成功搜索和相应待办；预算未知仍可查、儿童/房型不重复追问。
- 右侧摘要只读展示已知住宿查询地点及来源；未知不显示示例值。现有表单未提供该字段仍保持事实，住宿地点可在对话明确更新；生成OpenAPI/前端类型同步新字段，不手改生成文件。
- 独立P75更正：仅绑定city不能识别旧writer改走再改回。增加hotel_search_revision归属元数据，地点仅在该值等于当前业务revision且city一致时有效；新writer每次业务更新同步，旧writer任何业务更新无法维持此证明，保留侧列原文但当前地点视未知重新澄清。不能借来源-only的source_revision更新重新认证旧地点，故不复用来源版本作地点证明。不丢住宿预算，不改变旧报价/条件形状。

## P84：报价旧投影与完整适用条件的核验（2026-10-09）

酒店报价内嵌request继续投影旧字段，不把hotel_search_location加回旧JSON。行程校验使用既有Evidence.conditions核验包括住宿地点在内的完整当前条件；同时将内嵌旧报价的日期/人数/房数/币种/城市与Evidence.conditions的旧字段部分比较，防止仅凭外层条件接纳内部不一致的报价。地点改变仍使旧Evidence失效，原来源/时效与修复计数不变。此次是落实既有分工，不新增响应字段或持久位置。

## 多城市与明确不限（2026-10-10，D1/D3，T1.1）

- `TravelConditions.segments` 是2–6个连续城市段，含原文城市、到达/离开日期、可选住宿查询地点；仅最后一段允许零晚。全局city/start_date/end_date保留，更新segments时在现有patch合并入口派生首城/首日/末日；同时明确给出不一致的全局值则拒绝。清除segments保留已派生的全局单城字段。完整旅行模型再次核对一致性，部分patch允许未带全局值。
- 城市段与 `lodging_budget_unlimited` 只存既有request_details JSONB；legacy_request/conditions/报价旧投影继续排除两者。不新增迁移、依赖或运行时。未用新字段的单城市写入不额外保存空侧列键，旧证据条件字典不变。segments语义变化同事务失效hotel_offer与route，不影响无关place/article。
- 住宿预算三态：金额为空且unlimited=False表示未回答；有金额表示明确预算；unlimited=True表示明确不限，与金额互斥。切换使用现有set/clear，不能把False序列化省略成未操作；原total/其他币种仍兼容。是否追问/如何比较按本批D4/D5，T3.1/T2.2实施。
- 来源/CAS/幂等复用现有规则；对话模糊设置segments不得通过派生覆盖手填城市/日期，明确改变segments可更新其派生值。派生值来源随同本次实际更新。空新字段不改变旧单城来源响应。
- `trip_segments` 为旧单城唯一派生入口；条件未齐返回空元组。`segment_request` 只生成酒店查询/证据用内存副本，绝不写回会话。`cities_on` 在转场日包括前后城市；`same_city` 仅规范本项目有限城市别名；`pace_of` 识别软硬条件及D6别名，硬条件优先。业务查询和校验在后续任务调用这些函数，不各自重新实现。
- 回退只到已部署 `33df5fe` 或之后：T0.2兼容读取已独立push并通过Railway API/Web同SHA成功及旧正式V1读取；该版本只读新格式，保护后续写入数据。
