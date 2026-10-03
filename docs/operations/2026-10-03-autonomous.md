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
