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
