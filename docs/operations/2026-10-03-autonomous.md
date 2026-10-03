# 2026-10-03：长程自主开发

## 用户授权与目标

- 用户要求取消逐 M0.xx / milestone 的人工确认；按实现、测试、自审、独立审查、修复、继续执行，最终集中审阅、运行与学习。
- Claude Agent SDK 和旅行业务设计保留；可以自动拆任务、补规格、记录决定。执行规则以本次用户要求取代旧人工关卡。
- 用户明确回答：DeepSeek 本轮累计最多 5 元人民币、100 次真实请求，仍遵守 .env 每日预算；优先离线。未授权 Claude/OpenAI/Gemini 收费调用。
- 当前 Codex 使用 workspace-write + auto-review；不修改权限配置，不使用 Full Access，不 push / 合并 main / 真实预订。

## 操作

1. 从 1d75f79 干净工作区读取执行入口、04、M0 规格及相关资料；核对 OpenAI harness engineering、safe execution、Windows sandbox 与 execution plan 官方文章。
2. 找到旧规则里的人工合并、每阶段确认、两次失败即停、学习问答先行等停工条件，准备替换为自动质量关卡；质量标准保持。
3. 已创建本对话长程目标，并启动独立只读审查 agent autonomy_review 核查流程遗漏。无需用户另开聊天，也不调用项目 API key。
4. 从现有 SDK 文档提交建立 batch/2026-10-03-travel-autonomous；保留原分支和 main，未改写历史。

## 恢复入口

读 docs/execution/travel-agent.md 的当前状态、最近完成、下一步、预算授权和未解决项；然后核对 git status / git log。未完成的命令不能仅凭日志“开始”当作成功。断网或电脑关闭时没有执行能力；环境恢复后从落盘状态续接。
## 工作流迁移验证

- 已把 AGENTS.md 缩为地图，新增执行计划、工作流和工程标准；同步 plan、M0 规格、ADR 与学习页面。历史审阅记录保留，不当成当前停工指令。
- 编辑助手第一次因 M0.md 的旧引用文字不完全匹配而中止；修正匹配后从未完成的位置续接，没有覆盖已写入的文件。
- `uv run python scripts/dev.py check`：通过，31 个源码文件、3 条分层规则。
- `uv run python scripts/dev.py test`：70 passed / 1 deselected；本次没有真实模型调用。
- 独立审查已启动复核；待问题修复后保存工作流提交，继续新版 M0.2。


- 独立复审的三项问题已修复：所有功能增量均独立审查、允许修复后的有预算重验、迁移 ADR-000 的旧章节引用。无未解决重大问题。
- M0.2 准备：uv add 首次被沙箱网络限制拒绝（10013）；自动审批允许下载后成功安装 claude-agent-sdk 0.2.163 / MCP 2.3.0。仅安装依赖，没有模型费用；依赖改动留待 M0.2 提交。


## M0.2 离线实施

- 安装锁定 claude-agent-sdk 0.2.163，传递 MCP 2.3.0。Windows发行包没有bundled CLI，使用本机原生CLI 2.1.114；只运行 --version 确认，未修改系统CLI。尝试只读官方安装脚本返回403，不执行脚本或安装更新；实际本地往返已证明当前组合支持本探针。
- ADR-004 记录标准库回环请求守卫；真实密钥不传到SDK。新JSONL账本先预占整个模型上下文与输出上界，完整最终usage后结算，未知费用保留全额。禁用其他凭据来源和内置工具。
- 开发中格式与mypy发现长行/类型推断问题，已修复；失败不是用户审批点。
- 独立审查发现五项问题：慢流总超时、CLI孤儿进程、最终usage缺失、工具结果核验不足、非零退出假成功；已逐项补实现与失败测试，提交复核。
- Windows挂起测试首次揭示沙箱内taskkill不可用且旧Popen等待后代输出；该轮依靠已授权的定向清理结束，不把这次受干预的结果当有效证据。改为标准Windows Job Object回收，重新跑生命周期3项测试1.38秒通过；无需系统设置或WMI权限。
- 最新 dev check 通过：49源码文件，3条分层规则（已含claude_agent_sdk）。dev test：114 passed / 2 deselected，6.32秒。其中实际SDK/CLI+本地假响应完成MCP工具往返，不能代替真实DeepSeek验收。
- 新授权API消耗仍为0。下一步独立复核费用与清理边界后做一次受限live，优先使用最小往返，不重跑旧Messages探针。

- 复核又发现终结顺序/用量倒退、入Job前抢跑、DNS总期限缺口；已补启动握手、完整块检查、单调用量与有界HTTPS进程。Windows文本管道CRLF导致握手初次失败，兼容LF/CRLF后14项专项通过。
- 最新完整验证：dev check 50源码文件/3契约通过；dev test 119 passed / 2 deselected（6.83秒）。独立最终复核未发现阻止live的P1/P2问题。
- 开始受限SDK真实往返：用户已授权累计5CNY/100次；.env安全读取仅确认模型deepseek-flash、每日CNY5.0、USD0。只运行新SDK live测试，守卫单轮至多4请求，累计额度始终拦截。结果待命令结束后记录，不预记通过。

- SDK真实测试通过：1 passed（4.16秒），两次请求，输入439与150+384缓存、输出56与70；人民币高峰保守估计0.002954，账本已结算全部预占，累计2/100次。一个旧pytest缓存权限警告，不影响测试，也不重跑收费实验消除警告。
- 脱敏结果存 docs/evidence/sdk-roundtrip-2026-10-03.json；私有session_id及transcript留在.cache，不提交。
- M0.2 关卡离线/真实/独立审查通过，接下来本地提交后自动推进M0.3；没有向用户发逐项审批请求。

## 简洁复用规则与提交复核

- 用户追加要求：优先复用 SDK 和已有函数/接口，仅为旅行个性化业务或已证实的 SDK 缺口写代码。已写入 AGENTS、工程标准 §3.4 和复用清单，纳入独立审查。
- 阅读 commerce-agents 固定版本的 make_options/run_turn、工具契约/注册、build_sdk_tools/collect_turn；核查官方 SDK 最新发布为 0.2.163，与当前依赖一致。参考组合方式，不复制上游代码或引入多运行时抽象。
- 审查发现探针重复校验参数且错误字段与 SDK 不匹配；改用 SDK JSON Schema const，并通过实际 SDK/CLI 的本地错误回填测试。删除与外层进程总期限重复的 socket watchdog，单行转发包装改为 partial。
- 最新完整离线测试 120 passed / 2 deselected（8.36 秒）；后续删除 watchdog 后生命周期专项 5 passed（2.61 秒）、mypy 50 文件通过。独立只读复核确认没有新增 P1/P2，必要保护保持。
- 首次 M0.2 提交钩子中的离线 CLI 启动曾失败一次（ProcessError，守卫无失败），提交未生成；加入不含原始 stderr 的固定类别诊断后完整测试 119 项通过，尚未复现根因。继续正常钩子验证，不绕过检查。
- 本轮精简和规则更新没有真实模型调用；累计仍为 2 次、0.002954 CNY 保守估计。
- 再次提交复现 CLI 启动错误，脱敏诊断指向 git-bash。Git 钩子改变 PATH 后 CLI 的自动定位不可靠；从当前 Git 安装根显式定位 bin/bash.exe，仅注入 SDK 子环境。新增 3 项路径/错误配置测试，独立审查通过。
- 正常提交钩子 check/test 全通过（123 离线用例），保存为 d2a1b13。继续 M0.3，不绕过钩子或修改全局 CLI 配置。

## M0.3 应用边界

- 新增最小 RunContext/RuntimeEvent/SessionReference 契约、Agent.run 与 FakeRuntime；引用绑定用户、业务会话、SDK/CLI版本和计费来源/模型。只定义进程内续接，不假称业务恢复已完成。
- ClaudeRuntime 用 ClaudeSDKClient 与原生 options/resume；MCP 桥接从同一工具定义注册，注入业务执行器，错误正文不透传下游异常。
- 自审统一 ToolResult 为 plan03 的正文状态格式；旧CLI缺少字面输入能力时明确拒绝 @/斜杠展开语法，不用提示词假装隔离。
- 增加脚本化正常/错误/取消/限次/半流、会话归属/模型切换、工具桥接错误测试。首轮 mypy 发现类型收窄及 SDK context manager 可能吞异常的返回路径，已修复；144 离线测试与 check 通过。
- 交独立审查 agent 检查生命周期、会话隔离和简洁复用；正式工具 CLI 在 M0.4 接入。API 消耗未增加。
- 独立审查发现桥接事件异常可能被 SDK 原文回填、执行期间切换 runtime 可误标会话来源；已将事件/序列化纳入脱敏，运行开始固定 runtime/identity 快照。失败与并发测试保护这些不变量。
- 最新完整套件148项通过（9.10秒），之后增加切换模型并发回归，10项会话专项与check59文件/3契约通过；等待最终只读复核后正常提交。
- 最终只读复核通过：无剩余 M0.3 阻塞项，继续正常提交检查。
- 正常钩子通过，M0.3 提交 e2d848d（149 离线测试）。自动继续 M0.4。

## M0.4 旅行工具与 CLI

- 按 ADR-000 把已安装的 Pydantic v2 声明为直接依赖（uv add --offline），一份 SearchInput 同时生成 SDK schema 和直接业务输入验证，不另写规则副本。
- 新增 20 景点/12 攻略人工 fixture；标签属于测试设置，营业时间未知，不冒充已导入的 OSM/Wikivoyage 真实事实。城市硬过滤、别名、空结果/失败、返回长度和工具次数限制共用 SearchExecutor。
- 将 M0.2 的9个预算/网络/环境/进程模块移动到正式 claude_agent 包，探针改为引用；invoke_worker 也抽到同一 process 模块。没有复制第二套费用或清理实现。工具允许集合由本轮契约显式注入，探针默认限制保留。
- 实现默认离线 CLI、FixtureRuntime 和显式 live 的隔离工作进程。CLI 默认不读取 .env；真实密钥仍只在父守卫/HTTPS进程，SDK只拿本地令牌。
- 实际 SDK/CLI + 本地脚本 API 验证了两个旅行工具及同 SDK 会话续接（本地3次请求），未调用收费模型。SDK流式测试响应生成函数复用，修复测试模块导入路径和迁移后的 monkeypatch 路径。
- 最新 check 67 文件/3契约通过；dev test 161 passed/2 deselected（11.54秒）。独立审查进行中，尚未新增真实请求。
- 独立审查发现攻略 schema 暴露不支持的 indoor 过滤、max_tokens 回答可能误判完成。已用共享基础输入加景点专属字段修复；攻略补测试类别；SDK 终态和父进程最终 HTTP stop_reason 均核对完成状态，费用结算不变。
- check67文件/3契约及40专项通过，独立复核无剩余 live 阻塞。开始一次两工具旅行查询 live：本次守卫至多4请求，累计5CNY/100和.env每日预算继续生效。运行结果结束后再记，不预记通过。
- 真实旅行 CLI 通过（7.73秒）：3次HTTP，search_places成功1次、search_content成功3次；最终回答同时引用两个fixture来源、明确人工数据及未知营业时间。新增保守费用0.017716 CNY，累计5次/0.020670 CNY，全部预占已结算。
- 脱敏证据导出 docs/evidence/travel-query-2026-10-03.json；含实际模型/版本/usage/工具状态，不含密钥、用户prompt、工具完整结果或SDK会话ID。
- 最终 check67文件/3契约通过；dev test166 passed/2 deselected（11.37秒），git diff --check无问题。保存后继续Trace与评测。
- M0.4 正常钩子通过，提交727778b。

## M0.5 Trace

- 核查官方 Langfuse v4 Compose/OTel文档：自托管需要Redis等项目排除组件；按ADR000采用可选Cloud。只检查.env变量是否存在，三项均缺失，未输出值；UI验收记docs/blocked/langfuse.md。
- ADR005 后通过uv安装官方OTel SDK/OTLP HTTP exporter 1.45.0；应用事件新增实际时间与服务端工具调用ID。默认仅保存本地JSONL，显式--trace-cloud才启用网络导出。
- 新增本机HTTP collector验证真实OTLP路径/认证/摘要，不连模型或Langfuse Cloud。首次完整173项通过（12.09秒）。
- 独立审查发现4处P2，已修复并增加失败测试：失败请求预占单独记账、CLI/live共享导出降级、拒绝旧事件缺时间/重放保留原时间、复用SDK内存exporter后显式检查导出结果。付费运行先保存私有报告，再尝试Trace。
- 最新check69文件/3契约通过；dev test176 passed/2 deselected（12.01秒）。累计模型费用不变5次/0.020670 CNY。
- 恢复点：当前未提交M0.5完整增量；独立复核后正常提交，继续M0.6。已只读查看DataMind21用例及工具选择评分思路，后续只提交改编案例，不复制内部源码。
- M0.5 独立复核无剩余阻塞，正常提交钩子通过，提交837b8f0；Langfuse UI缺口保留。

## M0.6 初始评测

- 原21个ID改写中文用例并映射工具；澄清plan类别计数重叠，保留京都规划未实现工具的失败要求。不复制内部TypeScript代码，不把上游skip当通过。
- 评测复用Agent/FixtureRuntime和正式run_live，没有第二套模型循环；规则检查轨迹/成功/空结果/弱文本，失败、异常、未跑分开；每条结果立即flush/fsync便于恢复。
- 首次dev eval-dev输出21行，offline_fixture规则1/21；这是固定脚本的基线，不是模型效果。结果`.cache/eval/20261003T051858Z-1737903b`。
- 初轮check发现import排序及条件字典推断不变性问题，已按格式工具/显式dict[str,object]修复，无放松检查；完整183项离线通过（11.97秒），check73文件/3契约通过。随后补孤立工具结果失败用例。
- 独立审查正在进行；未增加模型费用。下一步复核后在既有累计授权内跑一次真实初始基线，不自动重试，不为刷分改用例。
- 独立审查3处P2已修复：范围外弱规则要求明确限制表述；manifest绑定HEAD/dirty与真实文件/schema哈希；联网前fsync case/身份关联，断电后可定位私有会话与费用，不自动重跑pending。新增反向评分、manifest与执行中断测试，10项评测测试通过。
- 最终独立复核通过；check73文件/3契约、完整186离线测试通过（12.21秒）。按已有整体授权执行一次`uv run --env-file .env python scripts/dev.py eval-dev --live`。
- 运行目录`.cache/eval/20261003T052330Z-cddd4fe6`：京都抹茶4请求通过；箱根3请求但多余工具失败；冲绳4请求仍tool_use，守卫阻止第5次，SDK未完成，后18条未跑。没有自动重试。
- 只读核对私有报告/账本：新增11次/0.055462 CNY，总16次/0.076132，无未结预占。失败属于范围说明不够明确导致无效检索，未扩大次数限制或改断言；下步随中性prompt补明确范围再回归。
- 导出docs/evidence/m06-baseline-2026-10-03.json，不含正文、私有session ID或密钥；保留版本hash/规则失败/用量。真实基线为partial，不能把1/2弱规则分当21条任务成功率。
- 准备M1规格时只读核对Docker：沙箱管道访问拒绝，按已有授权提升只读检查后确认Docker28.5.1运行、无运行容器。未改本机PostgreSQL或启动新库。
- M0.6正常钩子通过，提交b83edc3。

## M0.7 与 M1 环境准备

- 中性persona.md由Pydantic读取，同一规格供SDK prompt与语气规则共享；加入范围明确说明/缺信息澄清/空结果有限放宽指导，业务权限仍在代码。
- 评审rubric/JSON解析/真人配对计算已有失败测试；当前没有真人分，也未执行固定温度0 LLM judge，记docs/blocked/persona-calibration.md，不阻塞业务。
- check76文件/3契约通过，dev test193 passed/2 deselected（12.19秒）；独立审查无阻塞，建议评审带原用户输入，已补并7专项通过。
- 在授权内只回归两个坏例加京都正例：`.cache/eval/20261003T053049Z-d759aa44`。箱根/冲绳各1次不查询工具并说明范围，通过；京都抹茶3请求、两类工具均执行但无结果，失败保留。不能由此宣称总体质量提升；fixture无抹茶/甜品/餐厅相关字段，待M1数据补充。
- 新增5次/0.022318 CNY，总21次/0.098450，全部结算。导出不含正文的m07-scope-regression证据。暂停额外模型实验，继续业务代码。
- M1规格独立审查后补基础TaskRun/持久事件/取消交付、Evidence适用revision和路段失效、确认返回同一结果及conflict/unknown边界。
- DB变量均为空；核对5434可用后只填写.env的POSTGRES_USER/DB/PORT和随机密码，未改LLM或其他已有配置，不输出密码，DATABASE_URL留空由后续配置派生。
- 按ADR000 uv添加FastAPI0.142.2、SQLAlchemy2.1.3、psycopg3.3.6、Alembic1.20.0和uvicorn直接依赖。此项将随M1.1提交。
- dev db-up成功：项目容器travel-agent-postgres-1健康，PostgreSQL17，127.0.0.1:5434，新建项目卷；未连接或改本机5432/5433的服务。
- 核对官方SQLAlchemy每任务独立AsyncSession、psycopg Windows需SelectorLoop；SDK子进程仍使用独立运行环境，后续API使用线程启动现有同步live入口，不在DB事件循环里直接启动SDK。

## M1.1 API 与真实数据库

- M0.7正常钩子通过，保存59cf7b3。M1.1按ADR000/006使用FastAPI、SQLAlchemy/psycopg、Alembic及python-dotenv，避免手写配置解析器；httpx仅测试直接依赖。
- 实现用户/会话表、事务服务和API；DemoLogin契约单份复用，服务端生成身份，令牌只存摘要；同一SQL核对会话与所有者，非法/过期身份拒绝。
- dev db-migrate已在项目库成功；独立随机测试库升级两次并检查模型无漂移。完整203项通过（18.00秒），不调用收费模型。CI配置已写入，未推送或声称远端通过。
- 真实启动发现Uvicorn自定义loop回调误返回类，修复为SelectorEventLoop实例并新增回归；stdout/stderr显式UTF-8。实际HTTP health200、两次登录201、创建会话201、本人200/他人404。只停止本次启动的临时API进程，证据m11-api-smoke-2026-10-03.json。
- 独立审查发现测试URL query可能覆盖随机数据库/本机host；清空测试连接query，增加实际方言参数测试。无连接回归首次因方言附带类型适配context而全字典相等失败；改为精确路由断言并禁止hostaddr/service，未放宽隔离规则。7项专项通过。
- check87文件/3分层契约通过；最终完整验证/独立复核待记录。无新增模型请求。
- 最终dev test205 passed/2 deselected（17.60秒），独立复核无剩余P1/P2，准备正常本地提交。
- M1.1正常提交钩子通过，保存d2cfb12。

## M1.2 真实数据与营业时间

- 核对Wikivoyage Copyleft（CC BY-SA4.0）、OSM Copyright（ODbL1.0）、MediaWiki revision与Overpass官方文档。单独保留数据许可，不把仓库代码许可应用于第三方数据。
- 获取中文京都extract版本196315。主Overpass节点504；备用官方列表实例先返回40个节点，再取消输出截断并加入主要景点，最终146个对象/28个含opening_hours。无持续重试；公开原始文件/请求/UTC时间/hash写入data/snapshots。
- 导入切20段攻略；Place/Article/Source共用Pydantic契约，JSONB目录保存完整来源，已有search继续负责匹配；不另写第二套搜索框架。M0 CLI仍fixture，M1.4接正式DB工具。
- 营业时间支持星期列表/范围、固定时段、off、24/7、单规则跨午夜；复杂节假日/季节和交互跨午夜规则均unknown。缺indoor不按类别推断。
- check94文件/3契约通过；专项首次15通过/1失败为测试错误假设原始数字ID顺序等于DB字符串排序，改按稳定ID逐条核对来源；最终16专项通过（0.57秒）。
- dev db-migrate和python -m data.import_catalog在项目真实库成功，entries_processed166。数据库失败回滚/重复导入已由真实测试覆盖。独立审查/最终完整测试进行中，无新增模型费用。
- 最终dev test221 passed/2 deselected（18.31秒）；独立审查无P1/P2，建议明确OSM的2026-06-01数据基准已采纳。M1.4接入时必须使用snapshot标记，不继承fixture警告。
- M1.2正常提交钩子通过，保存6443071。

## M1.3 条件与Evidence

- TravelConditions单份字段契约同时供当前状态和RequestPatch的set使用，clear显式清空；省略不变、无变化不增revision，children未知与明确无儿童分开。
- 新增旅行条件/Evidence表与0003迁移；同一会话行锁覆盖读取版本、条件更新及相关证据失效。Evidence引用同时检查用户/会话、revision、适用日期人数、有效期；源字段缺失保持unknown。
- services/common提取已有事务/错误边界供两个服务共用，无BaseService/通用仓储；HTTP GET/PATCH条件与工具将共用TravelService。
- check102文件/3契约通过；领域+真实PostgreSQL+会话专项20 passed（5.94秒），覆盖并发只一方成功、写后异常回滚、伪造/他人/过期/条件不符/旧revision以及不变更新。
- 自动质量关卡交独立审查；新增HTTP合并日期/所有者失败测试，完整验证待记录。未调用模型。
- 完整dev test237 passed/2 deselected（18.91秒）。独立审查发现把酒店晚数要求误用在所有旅行日期，已允许同日旅行并在hotel_requirements单独要求overnight_stay；新增对照，11领域专项通过。
- 修复后check102文件/3契约通过，dev db-migrate项目库升级0003，完整dev test238 passed/2 deselected（18.83秒）；独立复核关闭M1.3关卡，无剩余P1/P2。

- M1.3正常钩子提交通过，保存723575a。

## M1.4 旅行工具与消息执行

- 搜索输入/匹配复用领域函数；旅行执行器单份schema连接目录查询、实体详情、条件更新和两份白名单Skill。串行读写界限1，按run绑定身份/计数，结果保留snapshot和来源警告。
- SDK worker复用现有Guard/预算/进程清理；Windows通过专用Selector线程转发同一数据库工具执行器，SDK保持Proactor，不另建模型循环。
- 新增TaskRun消息ID唯一约束、有序持久事件、同会话数据库行锁、取消与状态接口和SSE读取。最终状态与最终事件同事务提交；重复取消和相同消息无二次执行。API默认离线，只有server --live并且请求mode=live才进入既有付费守卫。
- 独立审查修复：worker不能提前公开completed；cancel错误不被tool_use停止原因覆盖；run重复检查移入预算锁；共享persona按工具实际data_mode说明历史快照。
- 新增故障专项11 passed（3.97秒）：真实PG并发消息去重/单执行/取消、两个实际API身份的SSE隔离、重建应用不重跑、事件半行/他人身份、真实子进程取消清理。
- 父进程失败回归+真实SDK/CLI/DB本地响应专项6 passed（4.44秒）。本地脚本2次HTTP工具往返完成快照读取/条件修改，不消耗真实授权。
- 首轮全量252通过/1失败（23.81秒）：离线fixture缺少原有中文人工测试集标签；补回按data_mode区分的中文说明，未改原断言。测试替身Guard工厂的严格类型失败已用明确签名修复。
- 独立审查指出多轮缺业务回顾：补TravelService.business_context，最多2轮有界历史和8个有效证据引用；旧revision/过期/他人证据不带入，历史文本不授予权限，不能确定指代就追问。最近15专项通过（3.41秒），check116文件/3契约通过。
- 恢复点：M1.4尚未提交；待独立复核、最终全量测试、开发库0004迁移和真实HTTP/SSE烟测。真实授权仍21次/0.098450 CNY，无新增调用。
- 追加独立审查修复：Python3.12 TypeAliasType需读取__value__才能枚举Literal；8种合法错误码逐项回归。Agent转换取消异常后deadline不再抛TimeoutError，改检查expired()；10ms真实PG验证failed/timeout状态及末事件。
- 专项13项父进程/错误码通过（2.28秒）、5项真实PG run通过（1.30秒），独立复核无剩余P1/P2。
- 项目库迁移0004成功。真实临时Uvicorn HTTP烟测离线完成，7个事件有序，重复消息同run、snapshot中文标签正确；证据m14-http-smoke-2026-10-03.json，已停止本次自有服务进程。
- 最终check116文件/3契约通过，dev test263 passed/2 deselected（23.94秒）；独立复核关闭，准备正常本地提交。
- M1.4正常提交钩子通过，保存baa7cf9。

## M1.5 模拟酒店与比较

- 6虚构酒店、12种房型/早餐/退款组合，按房晚/周末加价计算，金额Decimal，5分钟有效；包含缺税与缺费样本，不连接真实供应商。
- HotelOffer复用TravelRequest入住字段和evidence_conditions比较口径，报价直接保存为不可变Evidence.value，避免两份价格事实表。卡片和最低价由服务端生成。
- search/refresh/present复用现有TravelToolExecutor权限、次数、schema和SDK桥接；旧ID刷新只定位本人查到过的rate，必须按当前完整条件生成新报价。模型不能输入卡片价格。
- 已验证15项领域/真实PG专项（0.56秒）：6/12样本、房晚周末税费、未知金额、日期人数币种差异、过期/他人/伪造ID、条件变更刷新、缺儿童年龄、空与不可用区分；check121文件/3契约通过。
- 独立审查进行中；无新增真实模型调用，授权仍21次/0.098450 CNY。M1.5未提交。
- 首轮完整dev test278 passed/2 deselected（24.26秒）。独立审查未发现阻塞项，建议补present统一evidence_ids、拒绝重复offer_id，已采纳并补失败测试。
- 新增真实SDK酒店3次本地HTTP流程：先查询，再使用实际返回ID补卡。首次失败来自测试脚本跨轮复用tool_use_id；改为唯一ID后通过，不是生产价格/归属规则放宽。
- 两份数据库SDK测试共用启动helper，消除环境/预算/worker配置重复。最新17专项通过（5.08秒）、check123文件/3契约通过，准备最终全量与保存。真实授权未变化。

## 模型切换与工程地图

- 原Astra独立审查收尾因workspace额度失败；用户明确切换gpt-6.1-sol high继续。新小范围审查只给M1.5必要文件/证据，不传整段历史；只读复核通过，无P1/P2，不重复跑全量。
- 读取OpenAI Harness engineering及官方长程任务文章：AGENTS做地图、知识就近落库、计划外置、规则自动验证。没有照搬其架构或扩大项目范围。
- 新增ARCHITECTURE.md及docs的DESIGN/FRONTEND/RELIABILITY/SECURITY/QUALITY_SCORE短导航；业务设计继续plan，进度继续execution单一来源。修正plan/README过时“SDK尚未接入”字样，改为只指向执行计划。
- 新增轻量check_docs到dev check，10份入口存在/短地图/仓库链接检查；不扫描缓存历史或获取外网，外部链接/标题锚点不在验证范围。3个文档失败/正常路径+原dev测试共15 passed（0.08秒），check125文件/3分层契约通过。
- dev test增加-q减少正常输出；失败仍显示细节。模型切换前最后一次全量会话72523已不可恢复，不将缓存nodeids当成功；接下来运行一次最终全量并记录真实结果。
- M1.5与新增规范独立复核无P1/P2；修正安全文档措辞，明确SDK供应商认证仅回环令牌，但业务数据库DSN通过自有worker stdin传入。最终dev test282 passed/2 deselected（26.47秒）；静态125文件/3契约和10文档地图通过，准备正常本地提交。
- 正常提交钩子通过，M1.5及工程地图保存5415e60；自动进入M1.6。

## M1.6 行程校验与SDK修复反馈

- 新增证据引用行程/路线契约、纯validator、PlanningService和两个固定工具；复用所有者/revision/时效与MCP，不写第二个runtime。
- 自制4对步行/公交双向估算，无外部路线调用；未覆盖unknown，金额Decimal、时区aware、全员估算，最多24行程项/6路段查询。
- 首次校验+3轮修复，工具结果有具体问题与剩余次数；实际SDK本地脚本验证修正及上限，无真实费用。
- 定向18项通过，首轮全量300项通过31.44秒。初次静态类型检查发现输出流/结果Literal/测试JSON类型标注，已修后check132文件通过；没有跳过检查。
- 独立审查发现P2两项：未知路线未检查过晚出发、缺税费丢失已知预算下界。修复并新增复现回归，15项纯规则通过；check132文件通过，审查复核均关闭。
- 顺手修正providers README及架构文档的旧“SDK未接入”表述；文档检查直接运行也用UTF-8。模型授权账本保持21次/0.098450 CNY。
- 修复后完整dev test：302 passed /2 deselected，31.88秒；独立复核通过。下一步正常本地提交（仍运行钩子）后进入M1.7。
- M1.6已保存3dd92c0，正常dev check/test钩子通过；自动进入M1.7。

## M1.7 稳定行程项、草稿与独立确认

- 新增domain.plans、3张草稿/不可变版本表与0005迁移；共用会话锁、resolve_records/validate_proposal与revision规则，避免确认另开事务。
- 模型可stage/get/present，不能正式保存或设用户锁。确认检查归属/expiry/base/revision/Evidence/纯validator；重复并发返回第一次同版本。
- 最后已校验候选可stage且重新校验，不额外消耗修复；新增候选超限拒绝。历史view显示模拟hotel、需刷新引用；上下文注入本人正式plan_id/version。
- 7纯规则、PG竞争/整笔失败/ASGI身份、实际SDK只暂存专项通过。一次新ASGI测试创建演示用户返回503，单项及同组复跑未复现；未声称定位根因，后续全量继续观察。
- 初次静态检查发现重新导出/测试变量推断类型问题，修正后check139文件通过；20专项通过6.15秒、初轮完整319项通过36.21秒。
- 独立P2：24项/21未知路段合法patch展示超过8k，改为按完整ToolResult长度缩差异/卡片、保留ID/总数/警告；新增PG原场景通过，复核关闭。
- 修复后完整dev test：320 passed /2 deselected，36.66秒；check139文件/3契约/10地图通过。dev db-migrate退出0，项目库迁移至0005。模型账本保持21次/0.098450 CNY。
- 下一步正常本地提交后自动M1.8，补前端/持久presentation事件与完整默认离线演示。
- M1.7已保存e40c259，正常钩子通过；进入M1.8。读取Next官方安装/rewrites文档与registry，Node24.12.0/pnpm11.19.0，Next16.3.8/React19.3.0/openapi-typescript7.13.0。依赖先记ADR-007。

## M1.8与补充验收契约

- 新增前端ADR007/Next工作台、共享工具观察事件、持久presentation读取和固定免费离线脚本；SDK仍为唯一真实runtime。API契约本地生成，无密钥/DB访问。
- 修正pnpm11配置失效导致首次默认store问题，只重装项目node_modules至项目缓存；外部store未删。peer兼容固定ESLint9.39.5/TS5.9.3，unrs-resolver安装脚本明确拒绝；生成/peer检查通过。
- 桥接/live应用18专项通过，新前端lint通过。类型失败3处待修，完整测试/build/浏览器未跑，不套用上个提交的320项。
- 用户补充Goal/Acceptance Criteria，已更新执行计划v4及verification矩阵，保留既有成果，按原A/B范围继续，C档仅ADR。当前无后台命令，恢复从类型修复与新PG链路开始。

- 已修类型3处及离线route参数拼写；新增真实PG比较→stage→确认→patch/锁定失败与空结果。独立3P2/1P3全部实现修复并补回归，等待复核。
- 首次直接pytest碰到既有系统Temp权限；改用dev test独立项目临时目录，未删测试/放宽断言。直接.venv Python运行dev check缺PATH的lint-imports；按README的uv run入口后全部通过。
- 最终dev check145文件/3契约/10地图；dev test326 passed/2 live deselected，38.14秒。dev web-check类型/lint/6Node测试/build通过；增加前端CI配置，远端未执行。
- 浏览器真实API+PG完成比较、草稿、两次确认、局部修改、锁定拒绝、刷新、旧条件禁确认→重生成恢复；未启用live拒绝可见。390窄屏与桌面截图/evidence已保存。浏览器一次viewport reset后首个点击未生效，读取状态后重新点击成功；没有把点击尝试算保存成功。
- 模型用量仍21次/0.098450 CNY；当前本地离线API(session43772)与Next生产页面(session45684)运行；测试已结束。下一步审查复核/提交后M1.9，不等待用户。

- 独立复核补发现截断卡片隐藏第二天下午另一项：新增9项PG复现，固定样例在cards_truncated时拒绝；6项PG专项2.41秒通过，复核P2关闭。消息持久ID/confirmed恢复/empty问题也关闭。typecheck先用Next官方typegen生成路由定义，支持干净checkout；next-env.d.ts保持生成/忽略。准备正常提交，提交钩子将全量验证含新增用例。

- M1.8保存d239cc7，正常check/test钩子通过；自动进入M1.9。新自然语言业务评测与免费搜索fixture能力分开，保留真实失败，不降低规则期待。

### M1.9 验收补齐

- 继承d239cc7实现，用户Goal/9项Acceptance Criteria保持v4与verification矩阵；未重启工作。
- 新增9条自然语言评测规格，CLI默认全30；实际离线1通过/29规则失败/0运行错误，保留私有manifest与完整结果，公共摘要m19-regression。DB业务评测环境待M3.4，不使用预期输出驱动模型。
- 增加HTTP→离线Agent→实际工具→PG→SSE→确认→重启只读集成，输入/版本/身份/去重分支；初次输入遗漏city触发validation，补齐合法测试数据后专项18通过（3.42秒）。
- dev check通过145文件/3分层契约/10文档地图；独立复核与全量钩子结果稍后更新。无新增真实模型费用。

- M1.9完整329通过/2 live默认排除（38.54秒）；独立未发现P1/P2，P3澄清用例允许记录已知条件已修，专项11通过；dev check全部通过。

### M2.1 模拟供应商

- M1.9普通本地提交0b6fd8c正常钩子通过；沙箱Git写权限不足后按既有授权申请项目Git操作自动审批，不扩大系统权限。
- M2规格按plan补写/独立核对；P3暂时查无不是确定失败已修规格，并增加迟到请求实际HTTP实验。
- 新增独立FastAPI端口8001、15分钟hold、稳定client_ref订单、PG供应商表/0006、delay/429/500/提交后断传输四故障；价格复用既有HotelOffer/quote。默认故障禁用，无真实外部订单/模型费用。
- 专项4真实PG/ASGI/HTTP通过（1.15秒），静态首次遗漏测试函数返回类型，补齐后重检；全量与独立实现审查稍后追加。

- 完整333通过/2 live排除（39.02秒），check152通过；项目库0006成功，供应商实际8001启动。独立P2报价延期伪造已修为quote以原quoted_at重算、只忽略随机ID；原场景回归4专项通过（1.17秒），静态通过。

### M2.2/2.3 预订与对账

- M2.1保存c1262af正常钩子通过，独立P2复核关闭；继续Booking/API/hold工具/页面，不等用户review。ADR008复用httpx移入生产依赖，离线uv lock/sync通过，无新增包。
- 状态/历史/报价与来源保存在bookings/0007；同会话同Evidence一个稳定ID。模型只有hold_hotel；用户独立确认提交后才发送order，confirmed/unknown重复确认只对账。
- 重试只在服务层：429最多3尝试/5秒，非法/过长Retry-After拒绝继续等待；总deadline涵盖HTTP。未知写响应保留unknown，暂时查无保持unknown，只有过期hold证明缺席才failed。
- 专项10预订 +4供应商 +schema通过，真实HTTP断传输→unknown→服务重建→对账booked。前端类型/6测试/build通过，新增模拟预订确认/恢复读取页面。首次输出字段误入HoldInput和引用类型问题已修，schema重新生成，不编辑生成物。
- 尚待：API全链、更多依赖故障/输入/取消边界、真实浏览器、完整验证和独立关卡。累计模型21次/0.098450CNY不变。

- 后续已完成API所有者/非法输入/重复确认与服务重建读取、19供应商HTTP边界、实际SDK本地3请求search→hold且零订单。真实浏览器比较→暂留→确认booked→刷新原订单，m22-booking-workbench.jpg已保存。
- 前端共享useClock与确认可用性规则；web type/lint/7测试/build通过。完整364 passed/2 live deselected（44.26秒），check159通过；本轮未增加模型费用。
- 独立审查2P2：长合法偏好使已提交hold返回超过8k而blocked；UUID排序静默50截断隐藏新活动记录。修复Booking.card复用offer.card与全部本人预订按创建时间排序；新增真实PG长条件重复hold及51历史后held/booked恢复回归，修后34专项通过（3.48秒），check159通过。暂不加分页框架。
- 直接uv run pytest缺项目module PATH，改成uv run python -m pytest；静态发现parsed.port无用表达式，改为显式验证赋值。未跳过测试、放松断言或绕过检查。接下来正常提交，再做M2.4断点/进程恢复。

### M2.4 业务断点与SDK私有续接

- M2.2/2.3保存ffff284正常钩子通过，独立2P2复核关闭。新增0008同事务业务结果凭据，patch/stage业务键不依赖SDK tool ID；hold/confirm继续复用原稳定预订键。未引入新依赖/运行时。
- 查阅Anthropic官方sessions文档与已安装SDK公共get_session_info；私有指针绑定业务用户/会话/runtime身份/条件revision，校验完整成功轮次transcript指纹；执行前撤旧指针，丢失/损坏/条件/版本变化从当前业务快照新建，不手改transcript。SDK完整轮次实际6次分进程实验通过（12.74秒），均本地脚本模型，无真实费用。
- 启动单API只读业务核对，中断running→partial/cancelling→cancelled，事件与状态同事务；不自动模型/下单。实际子进程patch/stage提交后kill，新执行保留revision/draft/item ID；预订confirmed在供应商提交前/后kill，重启先查，订单保持0/1。专项8PG通过（3.92秒）。
- 实际API kill→重启读取条件rev2/partial→SSE补发/游标只读→原消息去重→新消息完成，专项1通过（2.75秒）。初次独立测试库未导入景点目录导致新消息failed，补上正常bootstrap快照导入后通过；不降低completed断言。
- 既有旧base回归发现缓存绕版本检查，修复；子进程patch数据序列化曾把未传条件变成null，改exclude_unset传输。新增过期Evidence测试一度造出valid_until早于retrieved_at的非法记录，修为合法已过期证据；恢复parametrize装饰器误移已修，未删测试。
- 独立3P2已修：规范等价默认字段/Decimal/时间与保留真实clear语义；缓存重放复用当前Evidence校验，快照只注入有效draft指针；快照和revision同次读取，轮次中条件变化则不写续接pointer。相应单位/PG/实际SDK并发条件实验均通过，等待独立复核。
- 前端生成契约更新、type/lint/7测试/build通过；check169文件/3契约/10地图通过。完整dev test session9187运行中。模型用量仍21次/0.098450 CNY，预算未变化。M2.5真实浏览器断线尚未做，不能标全部M2完成。

- 完整9187：381 passed/1 failed/2 live deselected（66.75秒）；原PG故障503回归发现initialize导致API启动退出。修为数据库暂不可用时保持待恢复状态，GET/submit/取消前先核对、并发只核对一次。原测试和恢复/API专项15通过（16.98秒），新增启动不可用→恢复→并发同消息回归。没有删除或降低原测试要求。
- 独立三P2复核关闭；非阻断建议已补：initial proposal省略酒店字段与完整null重放同一草稿。SDK轮中条件修改实验通过，全表将以最终代码再跑；本轮静态持续通过。未标任务全完成。

- 启动closed-port→恢复→并发同消息单项1通过（10.93秒），check169通过；005434f普通check/test钩子通过，未push。项目PG已迁移0008。

### M2.5 浏览器断线

- 停自有API9452/58595进行故障实验，浏览器真实POST失败500；刷新发现identity在GET成功后才设置，错误显示为新建会话。移动setIdentity到网络读取前，保留原身份/pending消息；前端type/lint/7测试/build通过，并重启生产Next6480使用最新构建。
- 断线刷新仍显示原会话6119c835与“重试未获响应的消息”，截图m25-network-outage.jpg。一次waitFor exact text未匹配，但DOM确认alert存在后截屏；不将等待尝试冒充断言成功。
- 恢复API后显式原ID重试，运行数3→4，新的3eb5ee5f… completed、事件序号7；固定离线室内查询返回空列表如实展示。模型费用不变。
- 再次停止自有API，保存条件请求未到达，页面出现复连按钮；只读SSE复连失败后重启42061，点击复连成功。PG核对运行数仍4、同一run ID/sequence7；页面2条tool完成项无重复、原模拟订单仍同一ID。恢复截图m25-network-recovered.jpg已保存。
- 此实验验证浏览器API断线/失败POST与只读重连；在运行中的API强制kill/补发由test_api_restart实际HTTP验证，不冒充浏览器中途断流实验。下一步Trace/归因、独立复核和正常提交。

### M2.6 Trace与复核

- API复用已有OTel exporter，从已提交PG事件导出私有Trace；补实际revision/Evidence ID、partial/awaiting_user状态。写盘失败与取消清理不覆盖业务终态。13专项通过（1.64秒），check170/前端7+build通过；全表387 passed/2 live deselected（82.48秒）。
- 重读M0.6/M0.7真实hakone-onsen Trace及原规则，保存m26脱敏前后元数据：4次无必要工具→范围规则修复→一次真实回归无工具通过。只读旧证据，无新增模型费用；小样本与Trace不能单独证明根因的限制已写明。
- 独立2P2：未知字段名可泄密、401后无登录入口。修为共用schema已知字段名与受控工具名、共用401错误处理；19专项通过（1.67秒），check170与前端7+build通过。
- 两次pnpm exec prettier因Windows入口PATH失败，正式dev web-check的Prettier检查通过；未跳过格式检查。第一次从apps/web启动Python不能import scripts，改从根目录启动并给子进程cwd。生产Next现81812，API仍42061。
- 临时过期仅自建demo6119c835所对应用户令牌；浏览器刷新真实401后显示“身份已失效”及显式创建按钮，m25-expired-identity.jpg。复原原期限/保留旧订单行程，再点击创建成功进入新会话6d990e19。不是更改用户真实账号/密钥，无外部费用。
- 等待独立复核关闭和普通提交钩子全表；不标整个开发完成，继续M3。

- 401修复复核又发现迟到SSE与普通API成功回写竞态，包括Promise检查后的微任务窗口。统一generation、旧流abort、异步每次写回前同步active检查；共用readWhile拒绝已过期响应，调用方再次守门。新增迟到成功、原401状态保留、微任务顺序三回归，前端10/type/lint/build通过。不是声称浏览器验证过所有微任务排列。
- M3规格已按既有plan补写，独立规格审查无产品冲突/重大缺口；外部MCP只四个明确工具、偏好用户API+持久墓碑版本、压缩/脚本/模型证据分开。核对官方hooks及已安装SDK0.2.163公共类型，PostCompact与CLI新版专用能力不能直接套用。M3仍未实施。

- 4a12656正常dev check/test钩子通过，24文件保存，不push。M2最终独立复核未发现其他P1/P2，自动进入M3。

### M3.2 用户偏好

- 新增用户行preferences/preference_revision及0009迁移；GET/PATCH/DELETE仅认证本人，expected_revision锁内裁决、部分修改、清空保留墓碑版本。复用旅行Text/Transport字段类型，不注册偏好模型写工具，不自动改本次条件。
- 业务上下文加入低优先级偏好；SDKcheckpoint同时绑定条件/偏好版本，轮中改变任一版本不保存旧上下文指针。删除后不续接旧偏好历史。移除无调用的旧单revision读取，用同快照revisions核对。
- 第一专项8通过/1失败，测试误把load_snapshot的类型化list当dict；按真实接口构造Article.model_copy后重跑9通过（1.50秒），保留删除/注入断言。check174/3契约/10地图通过。实际SDK删除测试已写尚未运行；网页待实施，当前不能标M3.2完成。

- 后续实现网页及实际CLI删除实验；初次完整397通过（87.60秒）。独立两P2发现初始空删除未阻止旧编辑、旧TaskRun回答仍注入；新增0010墓碑标志及回顾时间边界，保留用户原历史，SDK版本核对不变。
- 新专项先失败3项：FakeRuntime成功缺sdk_session_id被原守卫判provider_error；补完整假会话ID，不改产品守卫。mypy拒绝SQL条件中的普通bool，改SQLAlchemy true()。重跑PG/实际CLI/版本13通过（9.83秒）、check176通过；实际CLI覆盖原空偏好和已保存偏好且旧回答已持久化。独立复核两P2关闭，无新增P1/P2。
- 真实浏览器鼠标保存无效，键盘提交成功；截图证明旧conditions吸顶覆盖偏好表单，移除吸顶后鼠标保存/刷新/清除/重复清空通过，旅行条件仍rev0。网页版本0→1→2→3→4；最终空偏好rev4，截图m32-preferences-saved/deleted.jpg。不是把键盘成功冒充鼠标成功。
- 最终dev test 400 passed/2 live deselected（91.94秒），dev web-check类型/lint/10测试/生产build通过；项目PG迁移0010。API70996、Next60844、供应商12178仍为本地测试进程。付费计数/金额无变化。普通提交后自动继续M3，不等用户验收。

- 3590b2c保存M3.2；普通check/test钩子通过，31文件，无push，自动继续。

### M3.3 对外只读MCP

- 读官方MCP最新README与安装2.3公共Server回调/StreamableHTTPSessionManager/客户端API；旧装饰器接口不存在，不照抄v1。仅四个既定read工具，schema/TravelToolExecutor复用，逐HTTP Bearer与owned session URL，stateless/JSON；每call新执行器保持原run绑定不变量。
- 首轮类型检查发现MCP2.3使用snake_case公共参数、ServiceError无message属性，按实际类型修。首次HTTP两失败因httpx2 base_url无末尾斜线，改URL.join；随后事实比较误把两次新Evidence UUID当同值，改为逐字段事实/来源比较并单独验证各自UUID绑定及PG可解析，不降低Evidence检查。
- 专项5通过（6.87秒）：官方Client legacy/auto、真实PG、真实TCP正常→工具故障、401/404归属、非法/未知工具、空结果、缺实体、DB503、64KiB上限。结构化/文本结果及is_error一致。
- SDK :*只按前缀匹配；额外urlsplit严格本机host、有效port、无userinfo/path/query/fragment/空白，伪端口后缀回归通过。保留SDK安全设置，未关闭保护。独立复核无可复现P1/P2，无复制协议/新增依赖或模型费用。
- check178/3契约/10地图通过；完整405 passed/2 live deselected（99.65秒）。普通本地提交后继续M3.1，不等用户review。MCP独立服务入口已写包README，未对公网发布。

- f9eb345保存M3.3，普通check/test钩子通过，无push。

### M3.1 上下文与原生压缩

- 核对锁定SDK/CLI公共事件、hooks和文档中的CLAUDE_AUTOCOMPACT_PCT_OVERRIDE；临时离线探针实际收到auto触发和compact_boundary，SDK两轮均成功。只在测试环境使用5%阈值/人工40000 input usage，不改生产配置或原生历史。
- worker每用户轮重读PG快照、版本变化新SDK会话、重建run工具作用域；SystemMessage转换context_compacted事件；PG快照失败收敛安全错误、零HTTP。
- 专项原16通过（19.08秒）；第一次全表410通过/1契约失败（115.63秒），新增事件未同步OpenAPI。执行dev web-generate生成后端契约与TS，未删除失败断言。
- 扩展压缩后继续规划测试：复用已入库destinations再次插入同Evidence违反唯一键，移除重复seed；验证状态应为领域verified而非complete，按契约修正。人工5%再次压缩产生Read子集被守卫拒绝，调查后保持保护，续接使用默认阈值；不放开文件工具。
- 当前专项17通过（19.58秒），包含实际CLI压缩→保存→续接validate_itinerary、工具配对、过期排除、长历史、摘要503、DB不可用、轮间条件变化。check179/3契约/10地图通过；web-check类型/lint/10测试/build通过，无模型费用。独立审查与完整重跑仍待结果。

- 独立只读复核无P1/P2、无必须处理P3；完整重跑411 passed/2 live deselected（116.85秒），契约失败关闭。M3.1工程机制验收通过，真实模型压缩质量保持未验；普通提交后自动继续M3.4。

- 普通提交钩子静态通过、完整410通过/1旧SDK非法参数测试失败（115.77秒），worker_exit而非预期tool_roundtrip_missing。单独重跑原2用例均通过（3.11秒），目前未复现根因；补失败断言的安全结构化report诊断（不含stderr/密钥），保留原期望。重跑正常钩子，不能把第一次失败当从未发生。

- 第二次普通钩子check/test均通过，0861da7保存16文件；未跳过、放宽测试。偶发工作进程退出根因尚未复现，保留风险和诊断。

### M3.4 业务评测与固定编排

- 新DatabaseEvaluation复用SessionService/TravelService/TravelToolExecutor，逐案例创建独立PG用户/session，可初始化明确request；实际身份先fsync再允许live。限制本地URL及无query覆盖，不输出DSN。导入既定目录快照，manifest记录实际混合数据版本/schema/Skill及源文件hash，保留历史Case标签。
- OrderedTools仅限制既定search/hotel/itinerary阶段，不实现SDK循环或替换参数；同阶段可重试，失败/空不推进，setup条件写仅在开始前，不能跨run复用。SDK两组仍暴露完全相同14工具schema，固定提示只含阶段，不含grader期待。
- token仅所有HTTP尝试都有完整usage才求和；离线/部分/未知保持null。按模型原CNY记账，单案例最大实际请求1–12，默认4；累计5元/100次与每日限制不变。暂未产生新费用。
- 初次专项22通过/1失败，测试假设室内脚本有结果，但真实快照名称/文本无“室内”匹配。原Case应有结果期待不变、评测仍failed；补广义京都正常对照。固定脚本继续下一阶段会被空结果守门拒绝，诚实记录error；不作为真实模型固定流程效果。类型发现结果object不可下标，改共享RunResult TypeAdapter解析。

- 独立审查指出非DB自定义请求数被入口丢弃、完整固定行程缺酒店、目录upsert不能排除额外行。入口无DB自定义上限提前拒绝；固定序列补酒店；目录空才导入，非空与版本化完整payload核对，漂移conflict保留原数据并记录实际hash。专项27通过（11.72秒），check183/3契约/10地图通过，独立复核问题关闭。
- 即将按既有授权做hotel-complete-control自主/固定hotel各n=1，最多6实际HTTP/组，失败不自动重试；由既有预算/attempt fsync守卫执行。完整427预期测试正在运行，不能提前填通过。原累计21次/0.098450 CNY；调用后重新读取账本，不按预期次数记已发生。

- 两次实际命令uv run --env-file .env python -m eval.run --database --live --case-id hotel-complete-control --max-attempts 6（第二组加--workflow hotel）均1/1原规则通过，无重试。自主5HTTP/5工具/14.316秒/0.091532 CNY；固定6HTTP/8工具/14.646秒/0.111926 CNY，额外3报价刷新。两组实际代码/schema/目录/Case hash一致。私有运行20261003T094904Z-f7172629和20261003T094950Z-ca7c40cb，脱敏导出m34-hotel-comparison-2026-10-03.json；不导出回答/DSN/SDK会话。
- 账本重新核对32次/0.301908 CNY，剩68次，无未结预占。该小样本不能证明整体质量或固定编排改善；完整行程/重复统计开放。真实DB离线同酒店用例0/1、tool_selection失败，保留原标准，不靠脚本刷分。
- 第一次完整424通过/3旧live测试失败（126.55秒）：测试Guard替身不接受新增max_attempts实参。将替身明确同真实签名、转发原Guard；不改终态/取消/重复付费断言。专项40通过（13.30秒），新增非法上限0/-1/13/bool在凭据前拒绝，单文件17通过（2.31秒）。完整重跑待结果。

- 完整重跑431 passed/2 live deselected（127.36秒）；check183/3契约/10地图通过。正常提交保存M3.4设施与酒店小样本，完整行程多案例统计仍待验；独立目录/流程/请求上限问题均已关闭，无新增依赖或推送。

- 正常提交钩子静态/完整通过，da68f86保存21文件；工作区干净后继续M3.5，不要求用户审阅放行。

### M3.5 供应商与原币种共用

- 读取已锁定SDK配置/环境/预算与最新版Anthropic官方模型/价格。Haiku固定快照与disabled thinking匹配；Sonnet5.5已有协议变化，拒绝未核定模型，不照搬模型名。无新增依赖/第二runtime。添加LLM_PROVIDER与ANTHROPIC_MODEL到example，实际.env未改/未输出。
- 复用Settings/Price、Budget reserve/settle、固定HTTP进程、Guard/worker/应用identity与eval报告；CNY旧格式只在读边界归一化，继续写原格式。USD独立LIMITS0/0、每日金额不是授权；先授权检查再启动CLI。
- 初次静态185通过；专项89通过/4失败，公共计价错误提示丢旧DEEPSEEK_MODEL字段。恢复字段提示，不改原断言；93通过（3.83秒）。实际旧账本核对32/.301908、SHA256 5ee4cf6a0ba40dde7971c77c248c205849f949e2dedf8e0fe6b17ff197eb87f9，字节未变。
- 真实SDK/CLI本地脚本复用测试扩展到Haiku：两供应商共享两查询工具、完整回填/续接，3本地HTTP；合成USD额度仅pytest monkeypatch生命周期，不修改实际授权或调用外部API。18专项通过（5.80秒）。
- 独立审查无P1/P2，但USD Trace残留CNY硬字段是缺口；已通用化原币种属性/旧CNY兼容，混币种失败回归。45专项通过（6.82秒）；严格类型指出TypeAdapter结果需明确Currency标注，已修后待重跑。第一次完整测试进行中，最终源变更后重跑，不提前记通过。

- 首次完整447通过/2 live默认排除（126.78秒），后续新增CLI/Trace回归后第二次447通过/3失败（128.20秒）：旧压缩/轮间快照脚本使用仅含空messages的内部阶段控制，响应构造新增model索引触发KeyError，并非SDK随机失效。共享脚本保持默认DeepSeek模型兼容旧内部控制，实际出站仍被Guard严格核对；原压缩/快照断言不变。对应8实际CLI/PG回归通过（23.65秒）。
- 第二轮独立P3发现USD报告旧CNY字段可能被重贴币种；集中_amount复用于report/write_trace/逐请求，跨币种、双字段不一致/NaN/负值均拒绝。3原例回归加入，Trace+providers33通过（1.50秒），静态185/3契约/10地图再次通过；独立复核关闭，无剩余P1/P2。未产生任何真实请求，费用保持32/.301908。最终完整由正常提交钩子重跑，提交结果待记录。

- 正常静态/完整钩子通过，f792c85保存27文件，未推送。M3.5工程线路通过，真实Claude调用/跨模型对照仍未授权/未验。

### M3.6 实际规划失败与归因

- 执行原dev plan-complete-control，uv run --env-file .env python -m eval.run --database --live --case-id plan-complete-control --max-attempts 4；既有5元/100次授权内，失败不自动重试。私有20261003T101205Z-4c84bf1a保存manifest/attempts/results/Trace；4HTTP、0.080594 CNY，原规则error，未完成facts/路线/校验/暂存。累计重新核对36次/.382502，无未结预占。
- 观察update条件成功，后续多次search、含一次blocked工具反馈；父HTTP4次守门blocked，SDK转为invalid_assistant_message。现有证据证明执行被上限截断，不能把它猜成工具/供应商根因，更不能声称提高上限等于模型修复；原基线保留，后续是不同配置实验。
- 独立规格审查同意最小eval纯函数/事实附件，要求按业务验收而非completed判成功、附件绑定同run与tool_call_id/事件位置/当时版本、恢复后成功不误归因、矛盾/错配/证据不足unknown、固定公共依据白名单不泄私密。五注入不能替代三真实dev坏例及实际无效优化回退。

- 实际blocked搜索定位为8条目录完整payload超过既有8000字符限制，重复逐字段来源占大头。搜索列表仅保留ID/短摘要/来源与Evidence引用；完整PG证据及详情不裁剪，不提高返回上限。原查询与最大8条攻略/详情回归通过。
- 新增eval纯诊断函数及五类实际工具/PG/本机HTTP注入，公共结果仅固定cause/basis/位置/Trace ID；未捕获事实的实际失败仍unknown。API只转发原生压缩事件，业务入口显式最多12HTTP/SDK12轮，探针与评测默认4不变，工具16次、费用全程/每日边界不变；这不是模型效果改善证据。
- 专项首次失效证据字段假设及类型已修，保留业务原行为。混合显式测试文件路径出现fixture不存在：已检查pytest9.1.1 _matchfactories的node对象匹配，同目录后续collector与首次fixture父节点不同；统一tests根目录按-k选择40 passed/433 deselected（11.66秒），没有删测试/跳过PG。尝试包标记未解决，撤回无效组织变更。六HTTP实际CLI测试最初临时根误当源码PYTHONPATH；仅测试worker环境指向真实源码，账本/会话继续隔离临时目录。
- 静态189文件、3分层契约、10文档入口通过；前端type/lint/10测试/build通过。完整Python回归在运行，独立变更审查已发起；尚未提交或新付费实验。

- 完整471 passed/2 live deselected（133.17秒）；随后独立P2发现无关过期证据可误归因，已仅接受hold_hotel实际报价引用/当时版本，追加原误归因/错报价/错版本反例unknown。P3搜索摘要补coordinate_kind估算标记。静态与40专项再次通过（11.54秒），独立复核两项关闭；最终完整由正常提交钩子再验证。
- 接下来执行一次不同配置实验：同原plan-complete-control、修复后的搜索摘要、max-attempts12。保留4HTTP原基线，不自动重试失败；最多12真实HTTP，仍由5 CNY/100次/每日三边界约束。仅检验新配置是否完成原规则，不把提高上限当模型质量改善。

- 新配置实际20261003T102859Z-aad86cc3，6HTTP/.211342 CNY，SDK success但原规则tool_selection/tool_success失败，未完成validate/stage/present。guard无失败；同轮19次工具开始，其中16后被执行器拒绝。累计42/.593844，无未结预占。第一次解读详情blocked怀疑结果过大，检查私有实际调用与PG目录后否定：模型传的是两个Evidence UUID，服务端按目录ID查无。公开说明已纠正，不按猜测改详情裁剪。
- 提高SDK max_turns到12的尝试未显示改善：实际6HTTP已结束/16工具先耗完，不继续扩大工具/HTTP保护。SDK轮数回退原6；APIHTTP12仍用于已证明旧4不足的六HTTP酒店流程，与模型质量优化分开。增加参数schema/工具说明区分目录ID与Evidence UUID，业务快照从共享executor.max_calls告知16次总限额及避免重复搜索。原查无/上限断言保留，PG反例验证错UUID拒绝后正确ID可读取。46实际CLI/PG专项通过；不将同一个dev输入的两次失败计成两个独立坏例。
- M4规格已按既定plan写入tasks/M4.md并发起独立审查，当前尚无M4实现。核对Langfuse当前v4官方栈仍需Redis等，沿用ADR000/005既定Cloud替代，不引入第二runtime或自托管栈；UI缺凭据不伪造通过。

- 正常提交静态/完整钩子通过，4af55d3保存16文件M3.6工程增量，不标三真实坏例全验收。即将同原dev规划做一次ID说明修复后回归，最多12真实HTTP；此次是有代码修复依据的新实验，失败不自动重试。独立M4规格指出历史30条不能改名未见test、应构造业务初始状态/禁止副作用检查，已补规格；120案例运行必然超过100真实HTTP授权，完整统计仍未验。

- ID修复原例20261003T103737Z-8a0dc661实际9HTTP/.340634 CNY；所有14工具反馈无错误，但11次搜索、路线/校验后尚未暂存，4响应max_tokens，SDK最终incomplete_output。不能把schema语义说明修复当整例通过；不自动重试。累计51/.934478，无未结预占，余49次；下一步继续可隔离M4离线交付。
- ADR009先记录独立离线容器方案，首次生成.cache/demo.env专用随机密码（值未输出），默认离线且不复制.env。Docker读取初次沙箱pipe拒绝后按授权升级只读核对：28.5.1/约16GB；启动独立travel-agent-demo，未操作其他容器/开发PG。构建官方Python/Node/uv与既有lock，镜像只在本地。初次测试运行处于升级环境旧pytest临时目录ACL，2fixture错误尚待新项目临时目录重跑，不填通过；Compose提示共享后端镜像pull失败后转入本地构建，后续将修正构建顺序。

### M4.1 独立容器交付

- 新项目临时目录重跑stack专项2通过；共享镜像先build再up修复pull顺序。首次专用PG卷/运行卷启动bootstrap0、四服务健康；实际HTTPsmoke比较/生成/局部修改/确认幂等/模拟订单/用户隔离/非法版本与live拒绝通过。down不删卷，再up重建、--verify只读GET/SSE恢复同计划V2与订单通过。未删除旧开发数据或产生模型请求。
- 初次stdout中文受CP936，smoke入口复用configure_environment修复；初次ruff未用Path导入已修。最终check193/3分层/10地图、web type/lint/10测试/build通过；完整473 passed/2 live deselected（132.44秒）。新补4项daemon/build失败及down保护回归，正常钩子待重跑。
- browser-act命令不可用，未安装新的全局工具；使用现有内置浏览器进行3100端到端生成/确认/刷新正式V1，截图m41-container-restored.jpg。无模型调用/真实订单。
- 独立审查唯一P2嵌套dotenv未排除，补递归规则；六个合成文件实际Docker COPY/RUN断言排除且source保留。首次沙箱临时目录ACL导致Docker拒读，项目内新升级测试上下文通过，不读取真实env/修改系统ACL。CI补固定CLI及容器重建烟测，仅配置、未远端运行。

- e427808正常check/test钩子通过保存M4.1；stack六项专项通过。M4.2沿用现有服务构造初始业务状态，新增专用评测库与共享临时PG/本机HTTP启动设施；故障只在本次拥有的供应商/holds接口注入，setup unknown订单仅/orders丢响应。当前模型仅hold工具，无reconcile工具，已纠正方案为unknown安全解释/独立用户API对账，不能宣称模型自动对账。静态197文件通过；新增源码尚未完成测试/审查，旧eval专项运行中。未产生模型请求。

- M4.2旧eval/预算/配置专项60项通过后扩展冻结候选、重复3次/分母/原币种/token/时延及最低授权预检。静态202文件通过；下一批69专项通过20.85秒。没有模型请求，51/.934478不变。
- 初始新增PG测试输入误用了预算对象/非现有字段，以及过期报价quoted_at不早于expires_at；按既有TravelConditions/HotelOffer契约修正setup，未改产品断言，10PG专项通过。
- 独立两P2已修：setup既有held不能计本轮成功，无关timeout不能计实际供应商故障；按本轮配对事件/Evidence+real client_ref/fault绑定，并补零调用/幂等缓存/错run/重复end反例。P3补mock_supplier源hash。
- 候选60例独立审查另外三P2：解释允许读却期待无结果、室内快照全未知却强求查询有结果、单项patch未定位第二天下午/+1h。改候选明确只读与空结果任务，新增精准结构断言，历史期待不动；复核关闭，尚未冻结。新增错误目标反例首先误选第一天上午延后，原路线11点离开而结束迟于11导致合法validator冲突，不能作为“有效单项”的反例；改为第三天下午+1h，仍保留有效单项应通过/精准目标必须失败的原断言，不跳过/降低检查。

- 三P2复核关闭后72专项通过（21.50秒）、check202/3契约/10地图通过。20/40冻结travel-eval-v1，hash 5a433b621c43f62d17f98c6902d8e889b31c451fe02aa67145b5c142aa97558b；旧19Case完整相等/40无历史ID。
- 实际离线评测20261003T112436Z-6dc4c45b：40×3=120、0errors/0not_run/0HTTP，每轮3/40规则通过共9/120。替身只搜索，失败规则原样保存，不当模型质量；专用库正常退出已查询确认移除，父库保留。全量真实最低120授权预检blocked，账本hash不变。公共证据m42-offline-repeat-2026-10-03.json无回答/密钥/DSN。

- 完整Python506 passed/2 live deselected（140.03秒），专项和独立复核通过。准备正常本地提交，不push；下一步真实SDK本机离线复现轮数/截断语义，未发起新付费请求。

- e86ad6e正常静态/完整提交钩子通过保存M4.2共32文件，未push。随后本机终止probe实际2HTTP error_max_turns/tool_use误判provider_error/incomplete_output；四max_tokens内续最终is_error，所有HTTP被Guard计数。新回归先1failed/1passed（5.20秒），修已知终止原因优先后20专项通过（7.96秒）。没有真实模型费用。
- 完整三日新真实SDK/PG链路在DB6轮实际blocked/max_turns/6HTTP，只到validate。仅DB设SDK12轮（普通搜索保持6，HTTP12/工具16/三修复/预算不变），后21专项通过（10.65秒），9HTTP/8工具/6项草稿正式V0。测试存储payload改用既有PlanDraft验证修复mypy object索引，不改产品检查。check202/3契约/10地图通过，独立复核无P1/P2；完整回归64070运行中。旧真实终止原字段未留，不倒推已确认原因；待全回归后仅原dev一次最多12HTTP新代码实测，无自动重试。

- 完整511 passed/2 live deselected（145.88秒）后，既有授权内仅原dev一次修复回归23028：20261003T113648Z-a696428b，8HTTP/.322942 CNY、SDK invalid_assistant_message、guard无失败，原规则error。15工具13次搜索（含多次空）、酒店一次、条件更新一次；无facts/路线/validate/stage/present，最后4HTTP max_tokens。不自动重试、不认为12轮修好模型质量；累计59/1.257420，无未结预占。继续先离线检查提示路径与检索能力，冻结test未用于模型调优。

- 原dev重复搜索归因仅依据实际事件不猜事实错误；提示补明确完整规划路径，无兴趣时用京都宽查询、当前已一致字段不重复update、少量候选及时getfacts/路线/validate/stage/present与最小参数。不改查询算法/工具/冻结test，保留自主选参数。本次临时PG实际京都宽查询4条/无错误；check202通过，相关91359回归。

### 原dev展示契约失败与修复

20261003T114222Z-6424d8e2新提示实测10HTTP/0.452110CNY，SDK完成、guard无失败，但最后itinerary携带hotel专属expected_revision，ValidationInput拒绝；无卡片，原tool_success失败保留。本轮工具14：已读取5个facts/估算路线/校验/暂存，不能因SDK成功宣称规划成功。累计69/1.709530、0未结预占。复用PresentationInput docstring向schema/description/validation suggestion给出互斥参数提示，原验证与评分不动；26专项14.67秒/check202通过，补混填拒绝后正确展示的真实PG反例，独立复核进行中。

独立小范围复核无P1/P2；P3建议的同草稿混填反例已加入现有plans PG测试，拒绝/空data后正确展示，1专项通过2.20秒。现准备一次原legacy dev契约修复实测，最多12HTTP，累计69/100、1.709530/5CNY和每日限制均保持；新代码实验失败不自动重试。

20261003T114932Z-4e630873完成：10HTTP/0.365238CNY，SDKsuccess、guard无失败、原规则passed。实际presentation6项，validation partial/7 verified/13 unknown/0 conflict，住宿未选，无正式用户确认；不夸大质量。累计79/2.074768，0未结预占。公开证据仅摘要/Trace/hash，不含原模型回答/SDK私有上下文；将同一输入多次实验明确标作一例。学习索引/三段演示沿用业务与测试入口，修正README历史30条和过时前端状态。准备正常提交，提交钩子完整check/test，不在钩子期间编辑跟踪文件。

正常提交钩子首次失败：510通过/1失败/2live排除（145.50秒）；已有workbench截断歧义测试遇到RunService持久化失败，未删/跳过断言，提交未成功。单项重现1通过2.31秒、workbench/runs组15通过5.16秒；原异常正文被安全边界隐藏，新增仅异常类型/标准SQLSTATE诊断以便复现，无完整SQL/参数/连接字符串。完整复跑与独立复核进行中，不把偶发失败隐去。

M0.7自动评审补齐：ADR011/共享rubric/唯一SDK私有开关/零工具/Guard固定temp0，新增eval.judge持久证据与严格解析/停止边界。初次专项2失败：attempts UUID未序列化、CLI省略thinking且发temp1；定位后编码default=str/评审实际补thinking disabled，不放宽输出评分或工具规则。43专项4.01秒/check204过，独立复核中。原全量重跑511 passed/2 excluded145.96秒；容器近期无PG ERROR，未知原偶发原因继续明示。真实PG故障诊断反例/角色29专项通过4.07秒，无原始SQL/密钥输出。

评审独立复核无P1/P2；P3启动前混入DB/supplier/workflow/provider反例已补；本机SDK正常JSON/非法JSON/未授权Bash响应三分支均验，56专项7.64秒/check204通过。web-check本轮type/lint/10测试/build通过；首次check新增故障测试FakeRuntime缺outcome类型错误已修并复核。现用已有原dev实际回答准备1条语气评审，原文只存.cache，不用冻结test/不生成真人分。授权累计79/2.074768，最多4HTTP，失败不自动重试，原daily与5元/100限制不变。

真实语气评审结束：1HTTP/0.002122CNY、temperature0/零工具/合法分数、真人0配对/pending，原candidate/理由未公开。累计80/2.076890，无未结预占。56专项/check204与web-check通过。新故障测试FakeRuntime缺outcome类型问题已修后check过，独立复核无P1/P2；新增多prompt拒绝与actualSDK两错误分支。准备正常本地提交，不绕过失败检查。

第二次提交钩子149.73秒：3旧工厂签名失败+1PG初始化error/540pass/2excluded。恢复普通Guard工厂调用兼容，temperature仅评审分支在serve前赋值，原parent断言未改；共同事务边界新增共享安全异常类型/标准SQLSTATE日志，不打印SQL/参数。44相关9.62秒与11相关6.53秒过，未知PG根因仍开放。独立Goal审计指出3离线实现缺口：逐调用指标/首进度延迟/B0B3单因素控制；当前保存后继续，不标只剩外部验收。

后续正常钩子通过，99da71b保存M0.7/M3.6及学习材料。继续评测指标：复用bind_call/schema，合法但错误日期真实PG反例；首次进度/工具准确率与未知分母独立报告。独立审查复现两P2（跨run配对、旧报告缺指标显示零）后补同context/有序时间约束、全量null与已测小计。未分类文本ACK不计首次进度，单独validation错误码不证明参数错误；新增eval.assess私有参数评审入口及脱敏/不改附件反例。38专项通过2.80秒，check209通过；新增字符串行过长静态失败已缩短修复，无改断言/冻结期待，无真实模型新调用。正常全量钩子待运行，继续单因素控制。

指标独立复核关闭两P2。ADR012先记录同SDK对照/压缩关闭未证实边界，随后实现共享variant工具集合、B0无事实/工具、Skill/偏好/修复分别关闭；不暴露给用户API、不加runtime或依赖。初次patch因format后上下文匹配失败，无修改，读取实际源码后完成；静态导入/长行/构造Literal类型与kwargs错误修复，无忽略类型。实际CLI五组测试与相关65专项首跑64过/1新测试误断言草稿conflict必须拒绝；按原stage允许展示/confirm拒绝合同修正新测试并加强正式V0核对，生产规则/旧测试未改。第二次65通过28.65秒/check212通过。独立无P1/P2并建议补首次后新候选stage blocked/无draft，已补真实PG断言与实际CLI no_repairs第一次conflict/第二次blocked反馈（本机3HTTP）。无模型API新费用，累计仍80/2.076890。

补充19专项14.71秒/check212通过；离线实际eval.run --database --case-id kyoto-matcha保存20261003T123554Z-1041d8be，规则1/1但两工具语义unknown/accuracy null，0模型HTTP。首次进度0.0秒是本机时间同tick，fixture结果不当模型效果。核对持久预算累计80/2.076890不变；manifest fixture标不适用压缩/无SDK持久resume。准备正常完整钩子保存，不在钩子期间编辑跟踪文件。
