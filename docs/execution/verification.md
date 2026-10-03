# 功能与验收测试矩阵

2026-10-03 用户补充 Goal / Acceptance Criteria 后建立。设计来源仍为 plan/01–06、docs/tasks 与已接受 ADR；仓库目前没有 docs/spec 目录，不因此另造一套需求。
本表映射需求到验证方法与缺口；实时状态、命令结果和提交只在[执行计划](travel-agent.md)维护。
单元/离线SDK/真实SDK本地脚本/真实模型/真实PG/浏览器/人工证据分别标明；M1.8已提交d239cc7；验证和独立审查结果从执行计划读取。

## 产品回归

| 需求 / 范围 | 正常与主要分支 | 边界 / 非法输入 / 预期失败 / 依赖故障 | 跨模块证据入口 | 仍需补充 |
| --- | --- | --- | --- | --- |
| R01 参数与错误 | search、注册工具、结果回填 | 截断参数、未知工具、额外身份、工具异常 | tests/test_mcp_bridge.py；tests/integration/test_travel_tools.py | 持续按新增工具补故障回归 |
| R02 SDK中断续接 | 实际SDK完整轮次分进程resume同一ID | 丢文件/半JSON损坏/条件/CLI版本/轮中修改，业务快照新建；私有归属 | tests/test_runtime_sessions.py；tests/test_sdk_lifecycle.py；tests/integration/test_sdk_recovery.py | M4持久卷/HTTP重启已验；小样本真实模型续接效果仍待测 |
| R03 工具与写入顺序 | 读上限1、写互斥、单会话执行 | 并发消息、版本竞争、取消晚成功 | tests/integration/test_runs.py；test_travel_tools.py | M2实际进程重启/取消晚成功裁决已验证 |
| R04 条件patch | set/clear/未写保留、无变更不增revision | 日期逆序、空值、未知字段、版本冲突 | tests/test_travel_request.py；tests/integration/test_travel.py | 浏览器条件失效已验证；M2真实响应丢失与恢复已验证 |
| R05 Evidence与卡片 | 服务端引用/来源/有效期 | 伪造、跨用户/会话、过期、旧revision、缺来源 | tests/integration/test_travel.py；test_hotels.py | 已验证持久presentation与浏览器刷新；真实模型质量待评测 |
| R06 行程校验 | 时间/营业/路线/预算、SDK修正反馈 | 闭馆、跨午夜、缺税、未知路线、预算下界、3轮上限 | tests/test_itinerary.py；tests/integration/test_planning.py；test_sdk_planning.py | 页面警告已验；真实模型修复效果待评测 |
| R07 局部修改 | 稳定item_id、无关项保留、重复地点 | 锁定/不存在项目、旧base、超长合法草稿 | tests/test_plans.py；tests/integration/test_plans.py | 网页差异/锁定端到端已验证；模型改程效果待评测 |
| R08 确认保存 | 用户API确认、不可变正式版本 | 并发/重复确认、过期/硬冲突/旧条件整笔回滚 | tests/integration/test_plans.py；test_sdk_plans.py | 网页确认及HTTP重复操作已验证 |
| R09 预订幂等 | 同client_ref仅一订单、独立用户确认 | 重复/并发确认、服务重建、跨用户、长条件、51条历史后的恢复 | tests/integration/test_supplier.py；test_bookings.py；test_sdk_bookings.py；test_recovery.py | 实际供应商提交前/后kill对账与浏览器已验证 |
| R10 供应商失败 | 正常预订、有界429重试 | 429/500/实际超时/损坏响应/关联错误/非法Retry-After，终态分类 | tests/test_supplier_adapter.py；tests/integration/test_bookings.py；test_supplier.py；test_recovery.py | 单进程恢复已验证；多worker明确不在实现范围 |
| R11 丢响应对账 | 实际HTTP断传输unknown→查询→booked | 查询500、暂时查无保持unknown、过期锁内缺席证明、不重复下单 | tests/integration/test_bookings.py；test_supplier.py；test_recovery.py | 业务进程强制退出后0/1订单核对已验证 |
| R12 恢复与SSE | 启动只读裁决partial/cancelled，SSE补发；patch/stage稳定业务结果 | API/业务子进程真实kill、供应商提交前/后、条件版本/证据过期/默认参数差异、事务回滚 | tests/integration/test_recovery.py；test_api_restart.py；test_sdk_recovery.py；tests/test_operation_keys.py | HTTP/API重启、浏览器断线刷新/原消息重试/只读SSE复连与401入口已验证；未完成SDK轮次安全新建而非透明恢复 |
| R13 上下文 | 当前条件/正式plan指针/近期引用注入、原生自动压缩后SDK续接规划校验 | 长历史有界、旧Evidence、Skill/工具配对、快照读取失败零请求、摘要接口失败不保存完成指针、轮间版本变化 | tests/integration/test_sdk_database.py；test_sdk_context.py；docs/review/M3.md | 实际CLI/PG机制已测；脚本摘要与人工usage触发不能证明真实模型压缩质量 |
| R14 偏好 | 认证用户查看/部分修改/清空、保留墓碑版本 | 两用户、旧版本/竞争、首次空删除、非法字段、攻略不能写入、旧SDK及旧回答隔离 | tests/integration/test_preferences.py；test_sdk_preferences.py；tests/test_checkpoints.py；docs/review/M3.md | PG/实际CLI/浏览器保存刷新清空已验证，独立两P2关闭；真实模型偏好效果仍需评测 |
| R15 注入隔离 | 正常搜索/攻略实际SDK回填完成 | 恶意攻略不扩权限、无Shell/文件/偏好写入 | tests/test_sdk_guard.py；tests/integration/test_sdk_article_injection.py；test_travel_tools.py；test_preferences.py | 实际CLI/PG正常与恶意脚本成对已验；不冒充真实模型抗注入统计 |
| R16 确认边界 | 模型只暂存，用户独立确认保存/模拟订单 | 模型无下单工具、伪造user_confirmed、越权确认 | tests/integration/test_sdk_plans.py；test_sdk_bookings.py；test_bookings.py | 本地SDK暂留后订单为零与API确认已验证；真实模型恶意对照待M3 |
| R17 失败归因 | 正常Trace与工具span、API提交事件导出 | 写盘故障不影响结果、未知字段名脱敏、partial/awaiting_user状态 | tests/test_tracing.py；tests/integration/test_run_trace.py；docs/evidence/m26-failure-regression-2026-10-03.json | 五类实际注入/unknown及三个不同真实输入矩阵已有；scope正常邻例数据失败/规划质量partial仍开放 |
| R19 对外只读MCP | 官方客户端legacy/auto、四查询与直接handlers同事实/来源 | 鉴权、跨用户、非法/未知工具、空结果、DB/工具故障、Host/Origin/请求大小 | tests/integration/test_mcp_server.py；docs/review/M3.md | 真实TCP/PG及独立复核通过；仅本机演示Bearer，不声称企业OAuth/公网部署 |
| 酒店比较/刷新 | 同入住口径、并列最低、服务端报价 | 缺人数/税费、不匹配、过期、无库存 | tests/test_hotels.py；tests/integration/test_hotels.py；test_sdk_hotels.py | 网页过期与恢复 |
| M1.8工作台 | 条件→比较→草稿→确认→局部改程 | 类型、SSE分块、错误显示、失效确认、锁定拒绝 | 前端类型/lint/build、PG链路、真实浏览器 | 类型/lint/build/10前端测试、PG全链与浏览器正常/失效/锁定/刷新通过；M2实际丢响应与重启恢复已验 |
| Trace/评测/角色 | 本地OTLP、规则评分/版本、角色草案 | 导出失败、模型费用守卫、规则坏例 | tests/test_tracing.py；test_eval.py；test_persona.py | 历史30/冻结60设施与离线三轮已验；Langfuse UI、实际多次模型统计、人工校准仍未满足 |
| M3.4 业务评测/固定流程 | 每案例新PG身份与条件、SDK/schema/数据相同、完整固定步骤 | 非法初始条件、目录漂移不覆盖、先fsync后付费、上限非法拒绝、空/失败阶段不推进、usage不全为unknown | tests/test_workflow.py；tests/integration/test_database_eval.py；docs/evidence/m34-hotel-comparison-2026-10-03.json | 酒店两组各n=1真实规则通过；完整行程对照、更多案例/重复和语义评分仍待验 |

R18与C档实现按既定plan明确排除；C档仅交付ADR。新增主要功能同时补正常、分支、边界、输入和合理依赖故障，不只增加happy path。

M3.5供应商/原币种：test_sdk_providers覆盖显式选择/无key不回退、非法/未核定模型/日预算、USD零授权在SDK前拦截、CNY旧账本字节与结算不变、跨币种拒绝、缓存上界、截断/缺usage/超上下文、固定HTTPS/auth。test_travel_sdk_offline用真实SDK/CLI与本地脚本验证两供应商相同旅行工具与resume；test_checkpoints验证切供应商失效；test_tracing验证USD原币种与混合拒绝。Anthropic真实API、模型对照和新版Sonnet仍未验证。

## 交付检查

M4.1容器：tests/test_stack.py覆盖密码重用/损坏不覆盖、Docker不可用/构建失败不启动、停止保留卷。实际独立Compose从新卷初始化、Next同源代理→认证→条件→比较→草稿→局部修改→确认→模拟预订与重复确认、隔离/非法版本/禁止live、停止重建后只读计划/订单/SSE恢复。合成嵌套dotenv实际构建排除；浏览器确认刷新V1及截图见[M4](../review/M4.md)。容器默认离线，不代替真实模型与Langfuse UI；该历史验证时远端CI尚未运行，当前结果见末尾。

M3.6归因：tests/test_diagnostics.py 与 integration/test_diagnostics.py 使用实际工具/PG/本机供应商HTTP注入五类单根因，并验证正常、已恢复、completed但业务规则失败、错run/调用、重复/乱序、缺失/矛盾附件、合法参数反证与私密字段不导出。eval默认缺事实附件的失败标unknown；注入不是三真实dev坏例验收。integration/test_travel_tools.py覆盖最大8条真实目录搜索与完整详情/证据保留；test_live_business.py通过真实SDK/CLI、PG和本机六HTTP酒店链路检验API入口，合成费用写测试临时账本。实测规划同输入三次与最后规则通过已留证据；不同dev坏例矩阵已集中review/M3；正常邻例/完整模型质量仍未满足。

- Python：dev check（ruff、format、mypy strict、分层、文档地图）、dev test（默认不付费；真实PG必须可用）。
- 前端：生成契约一致性、TypeScript、官方Next ESLint、Prettier、生产build；浏览器宽/窄布局与核心流程操作。
- 跨模块：API→Agent/SDK→工具→真实PG→持久事件→浏览器；模拟供应商与恢复故障不能只mock数据库。
- CI：配置与本地对应检查分别记录；未push/未远端执行不写CI成功。
- 审查：每个增量独立审查，修复重大问题并复核；检查重复规则/接口、过度抽象与失败路径。
- 未满足项保持开放；外部权限、预算不足或人工校准缺失不得包装为全部完成。

M4.2评测设施：test_eval_suites保护冻结前拒绝、hash/20/40/历史不改与正常对照；test_eval_report保护独立三轮、异常后停止所有轮次、分母/原币种/未知token与HTTP。integration/test_eval_state用真实PG/HTTP验证正式plan/setup隔离、精准改程及错误目标/幅度、锁/历史/偏好改写、expired/stale报价刷新、未知税本轮卡片、500/429/实际超时、unknown不重复下单、禁止副作用、本次专用库。规则机制与离线重复不计真实模型三次统计。

SDK终止与完整规划链：test_sdk_cli_offline保留真实CLI max_turns/tool_use复合终止和四次截断请求计数；integration/test_sdk_planning保留9HTTP/8工具三日草稿链，失败不写正式版本。integration/test_plans保留同草稿混填酒店参数拒绝、无卡片后正确展示；不放宽业务校验。真实模型原dev的最后展示失败另记证据，不将脚本化SDK成功当模型质量。

M0.7：test_persona_judge覆盖原旅行bytes不变、实际temp0、采样/工具非法输入收费前拒绝、私有flag混入DB/supplier/workflow/provider/多prompt启动前拒绝、缺温度/身份/轨迹证明不评分、JSON错误单列/真人字段保留、durable attempts与运行异常停止后续。实际CLI零工具正常/非法JSON/未授权Bash响应三分支验证；真实DeepSeek小样本见m07-persona-judge证据，真人校准缺失仍开放。test_runs持久化故障注入要求恢复核对，日志不含原SQL/参数。

评测指标增量（71bd308，独立两P2已关闭）：test_eval_metrics覆盖逐调用参数schema/独立答案、错run/重复/缺附件、成功不等于正确、非法选择与输入、未知分母、首次进度缺失/异常时间；integration/test_eval_metrics使用真实PG证明合法但日期错误的成功工具仍记incorrect。默认事件没有独立语义答案时accuracy为unknown；B0/单因素配置已实现并验证机制，实际模型对照尚未完成。

两P2反例已补：跨run结束事件/倒序时间不能配对；旧报告缺指标不是零调用。test_eval_assess覆盖原案例选择、私有参数附件评分、无效输入脱敏、附件不改；该离线人工参数入口不等于已对真实模型全量逐调用评分。文本未语义分类不自动计首次进度，避免ACK刷低延迟。

ADR012对照配置：test_evaluation_variants覆盖共享注册表、非法配置收费前拒绝、数据库要求、workflow/judge/多轮冲突、FixtureRuntime不能冒充效果；integration/test_evaluation_variants用实际SDK/CLI+真实PG核对schema/偏好/快照/无checkpoint/业务不改，并验证首次校验后修复阻止、原候选可暂存、conflict可展示而用户确认拒绝且正式V0。新增no_compaction及B2：同人工usage/阈值原生自动压缩与关闭两分支；test_claude_runtime覆盖未知SDK/CLI在初始化前拒绝、意外压缩中断且无session ref。零工具公开状态探针只证实锁定版本能力；带工具不逐轮探测，不放宽费用。B2同时关闭偏好和压缩是组合基线，与单因素区分。真实模型压缩质量和统计对照仍未满足。

内容评审增量：test_eval_content覆盖原case/context/hash/原文位置绑定、正确/错值/typed bool、过期/版本/来源/外国或重复附件、未完整标注/漏必需事实、显式unknown、估算不能冒充确定值、真人分非法与缺失、脱敏CLI及原results/manifest/attempt一致性（改原文/身份、重复、坏manifest、无捕获）。integration/test_eval_content用真实PG捕获本人事实/保留失效报价与旧revision、拒绝跨用户，实际目录name/opening_hours和酒店card.total/缺税/错值评分，捕获依赖失败使验证不完整并停止后续而保留HTTP计数。独立两P2（整对象错判子字段、未解决unknown陈述仍完美准确率）均已补反例复核关闭。机制已验不代替实际语义/人工校准；通用内容LLM辅助入口已补，内容真实单样本入口已验；实际内容模型统计/人工配对仍未满足。

内容辅助评审：test_content_judge验证三维严格类型/错用语气JSON/缺或非法kind启动前拒绝、真实温度与工具证明不足不评分、真人三维原样保留、每维独立校准、已评分离线补真人记录而不重付费。test_persona_judge原实际SDK三分支扩展到两种rubric（合法JSON/坏JSON/未授权工具），原语气断言保留。共享同一执行循环/预算/SDK/Guard，无第二runtime；合成配对仅测试统计，不当实际真人验收。

M3.6逐案例矩阵及来源hash核对集中review/M3：箱根/冲绳共享59cf7b3修复、规划99da71b修复，同输入多次只算一例；范围批次抹茶邻例失败原样保留。无效SDK轮数实验撤回有原记录与默认代码证据；模型阈值优化前预声明未找到，按历史偏差记录，不补造已通过条件。

Windows评测CLI：test_eval强制非UTF8/ASCII环境启动四个真实子进程，失败输入仍返回脱敏中文/退出1、不吐Unicode traceback；复用既有configure_environment而不要求用户设shell变量。首次四失败保留定位记录，修后92相关通过。内容辅助入口一次真实模型三维JSON已验，n=1/真人0不是质量统计；证据m34-content-judge。

新用户授权预算回归：test_sdk_budget保留有限5CNY/100次的原三个边界，另验证无累计限下101次与跨日累计历史、日硬限15包含旧账/未结占用/重启且不受env100扩大、更低配置与USD0。日界沿用UTC；单run/工具/修复保护不改，不以新增授权改冻结规则。

M4.2首次完整真实test三轮：原40×3、实际DeepSeek/SDK/PG/HTTP，94/120规则通过、26失败、0error/not_run；三轮分别31/31/32，全部120安全三断言通过。绑定原源码/数据/用例/schema与实际费用/时延/缓存，源文件结束哈希一致、独立身份120与临时库清理确认；见m42-model-repeat证据/M4集中记录。规则不是语义完成率，379参数语义unknown、27次运行首进度unknown、真人0，B0结果见末尾，其他对照未完成。远端web/docker-demo已实际success，但Linux Python静态11错待修，测试尚未执行；不把Windows本地Passed当全CI通过。

B0同版本真实120次：17通过/103失败/0error/not_run，三轮6/6/5；120HTTP/0.646906CNY，零工具首进度120 unknown。源版本/冻结用例/状态/schema变更边界见M4与公开证据；不得当事实准确率。CI平台保护新增两原红色失败回归，修后8生命周期测试通过；三平台各216源码strict及原静态检查全通过，完整钩子与远端待验。

原记录比较：test_eval_compare覆盖完整配对、失败/错误/未跑分母、源/期望/状态/数据/schema/配置漂移、缺/重复/乱序/未结束、attempt/组内组间身份重复、混模型/SDK漂移、缓存摘要不符、缺指标/币种不同/非法数字、UTF8脱敏CLI失败。比较不产生真实模型调用；73相关专项（含PG对照机制）通过，独立审查/全仓关卡待完成。

CI恢复：558e7d2两事件37130689536/37130692016的Python/web/docker-demo全success，首次失败保留；不是只有配置。比较1P2已红→绿→独立关闭，partial费用total null/小计单列，34比较测试通过，原120精确费用差不变。

- 558e7d2 Linux Python实际CI日志：651 passed、1 skipped、2 deselected，149.27秒。CLI2.1.114实际安装运行；1项为已有Windows Job平台专属语义，本机8项生命周期已通过，2项真实模型默认排除，不为CI新加skip或删测试。

M1.8页面缺口追加：integration/test_article_pages真实独立PG验证20公开攻略与各详情/归属来源一致、unknown404/长ID422/空库及依赖503、公开阅读不创建User/Session/TaskRun/Evidence。前端新HTTPS链接失败输入与持久plan_id首读失败重试；现有旧代响应/微任务用例保留。浏览器实际验证带编码ID修复、攻略引用不发送、匿名空页、确认V1正式页以及自有API断线500→恢复/重读同V1。卸载登录延迟未做浏览器注入，不把helper测试叫完整hook测试。证据m18-pages-2026-10-04。

CI竞态原失败保存：bf6dc52 push两个评审未经许可工具时guard HTTP2（原要求1），同HEAD PR通过；新增守卫响应allowlist无需依赖SDK回调，原两种rubric×3实际CLI断言未修改。test_sdk_guard追加违规名完整usage结算后拒绝/下一请求不转发与非法名保留预占三反例；63相关专项Passed。所有已计费用保留，不以拒绝违规结果退款。完整钩子和新CI尚待。

R15追加：test_sdk_article_injection真实SDK/CLI+PG、本地脚本normal/injected成对；marker只从get_article的tool_result回填，不入system。normal2HTTP完成/checkpoint；injected2HTTP后Bash越权被blocked，费用不重放、无checkpoint，完整Preferences/请求revision/本人Plan与Booking均不变；finally恢复原article避免污染。25相关专项Passed7.39秒，独立无P1/P2，P3明确拒绝根因已补；不是模型抗注入效果。7d1d0f6完整默认钩子Passed且pushSHA核验一致；系统进程CIM只读查询遭默认ACL拒绝，未扩大权限，普通进程摘要确认仍在正常验证。

- 24b5dcb R15正常完整check/test钩子Passed、普通push远端SHA一致；7d1d0f6两新CI37132750339/37132753268全部success，Linux Python693passed/1已有平台skip/2live deselected，158.64秒。
- 验收审查发现M1.5/M2.2卡片漏报价儿童信息，现复用partyLabel读取card.stay/booking.offer.request；未知不当无儿童，不改价格或报价。14前端专项/type/lint/build Passed，独立无P1/P2。实际浏览器原比较及held报价2成人/儿童0,8/2房；当前改成儿童5/1房，旧held仍显示原人数、旧条件警告、确认disabled。旧正式V1酒店仍无儿童/1房。只有模拟hold，不确认下单；原state smoke --verify Passed。证据m15-party-display-2026-10-04，最终正常完整钩子/push继续。
- 下一离线缺口：plan05约束/预订/恢复分项统计需复用原校验与业务观测添加报告，partial/unknown/conflict分开，不把valid_draft布尔当全部硬条件满足；无真实恢复观测保持未测，旧记录缺项unknown，不重付费或改变冻结期待。


M4.2业务分项追加：复用一次PG事后核对与get_draft当前身份/条件/正式版本重校验，保存完整check_counts，complete/partial/conflict/无候选/不可用分开；partial不算全部硬约束验证通过，覆盖不足时总比率null。模拟暂留/unknown/预期故障且无额外订单单列，冻结集没执行恢复目标仍unmeasured。新manifest版本与逐行字段/适用范围/摘要严格核对；旧paid记录不补造，原full/B0各120缺观测、规则94/17和费用未改变。116相关测试含实际PG/HTTP 28.55秒Passed；222源码三平台strict/ruff/格式/3分层契约/10地图Passed，独立无P1/P2。正常完整钩子/push继续；证据m42-business-metrics-2026-10-04，0新付费。
