# 08 Skill 该不该预先设计 22 个，以及“经验沉淀成 Skill”的增长故事站不站得住 —— 研究笔记

调研日期：2026-11-26。与 04（自进化）、05（规模与路由）不重复的部分才写在这里；已有结论只引用不展开。

来源标注：
- 【原文】= 本次直接抓取了该页面。其中三页拿到了全文（Skill 最佳实践、企业治理指南、Claude Code 功能对比页）；其余页面经抓取工具的摘要模型转述，引号内文字可能有个别出入，引用前建议再对一次。
- 【二手】= 只看到转述、报道或搜索摘要。
- 【未核实】= 没找到或没读到正文。

---

## 0. 两个问题的直接回答

### (A) 预先设计约 22 个 Skill 是否必要

**结论：证据不支持“预先设计 22 个”。支持的做法是：保留现有 6 个，之后每新增一个都由一类已观察到的失败和对应的评测用例来驱动。** 22 这个数量本身对强模型不算危险（≤20 基本无损，见 05 第 4 节），问题出在“预先”二字。

依据：
1. Anthropic 的作者指南明确要求先有失败再写 Skill：先在无 Skill 时跑代表性任务、记录具体失败、建三个场景、测基线、只写够用的最少指令；理由是 “solving actual problems rather than anticipating requirements that might never materialize”。【原文·全文】
2. Anthropic 自己的电商参考架构里，购物 agent 和商家 agent 各只用 5 个 Skill，按业务域一个一个分；并给了放置规则：与约三分之一及以上流量相关的放 system prompt，其余进 Skill。【原文】
3. Anthropic 企业治理指南：边加 Skill 边用评测集量召回，“stop adding when performance degrades”；API 每次请求最多带 20 个 Skill，超过就应合并窄 Skill 或按任务类型分流。22 个已经超过这个平台上限（本项目用自建的 load_skill，不受此限，但它说明官方设计的量级）。【原文·全文】
4. Intercom 对同类制品（Procedure）的建议：从流量最高的一个开始；“Fewer, broader procedures reduce collision risk”；只有当你想单独看某项工作的指标时才拆成独立的一个。【原文】
5. 数量之外，“每个任务配多少、写多长”也有数据：SkillsBench 中每任务配 1 个 Skill +18.0 点、2–3 个 +19.0 点、≥4 个只有 +10.1 点；精简与标准长度 +19.0 / +21.5，详尽 +14.5，“面面俱到”的文档 +0.7。【原文】
6. 让模型自己从候选里选时，收益会缩水：Claude Opus 4.6 在 SkillsBench 上，强制加载 55.4% → 自行决定 51.2% → 混入干扰项 43.5%（无 Skill 35.4%）；“把该加载的都加载了”的比例从 49% 掉到 31%。【原文】

### (B) “经验存成 Skill，system prompt 保持小，Skill 库持续增长”是否站得住

**结论：方向与行业做法一致（按需加载、模块化、每个模块有负责人和用例），但原样讲有四处会被追问，需要加治理条件才成立。**

1. **“system prompt 保持小”不完全成立。** 每个 Skill 的名称和描述是常驻的；库增长等于常驻索引增长。官方文档：元数据 “competes for attention in the system prompt”。【原文·全文】
2. **存成 Skill 的经验可能根本不生效。** 触发不保证：野外检索设置下 Claude 的 Skill 加载率 62.2% → 44.4% → 16.3%；另一基准发现 agent 加载 Skill 的比率与“是否真的需要”几乎无关。【原文 / 原文·仅摘要】所以“必须每次成立”的教训不能放 Skill，应进代码或 system prompt。
3. **自动生成的经验质量不可默认。** SkillsBench 最终版：模型自写 Skill 在全部三个配置上都低于无 Skill 基线（−8.1 / −11.3 / −11.5 点），而人工整理的是 +18.2 至 +24.8 点。【原文】这直接推出：反思环只能提案，必须过评测门和人审。
4. **库只增不减是实证规律。** 对 GitHub 上 84,200 个 Skill、750,898 次提交的研究：变更以增量补充为主，结构性重组极少（知识重构 1.74%，流程合并 0.07%），精简类合计 13.13%。【原文】不设合并与下线机制，库会单向膨胀。

公司层面的治理做法见第 4 节；共同点是：版本化、评测门、人审、灰度、可回滚、每条有负责人。**没有一家公开过“触发率或胜率低于多少就下线”的数字阈值**，这一点只能自己定并如实说明。

---

## 1. Anthropic 官方口径

### 1.1 什么时候建 Skill、从哪里开始
- 作者指南：“Create evaluations BEFORE writing extensive documentation. This ensures your Skill solves real problems rather than documenting imagined ones.”；五步：找差距 → 建三个场景 → 测基线 → 写最少指令 → 迭代。检查清单要求至少三个评测。【原文·全文】https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- 工程博客（2025-10-16）：先评测，“Identify specific gaps in your agents' capabilities … Then build skills incrementally to address these shortcomings.”；也建议让 Claude 把成功做法和常见错误沉淀进 Skill；“Looking further ahead, we hope to enable agents to create, edit, and evaluate Skills on their own” 是愿景表述而非现状。【原文】https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- Claude Code 功能对比页给了按触发事件添加的顺序：同一个惯例错两次 → 写进常驻说明；同一份多步流程第三次被粘贴进对话 → 存成 Skill；必须每次发生 → 写 hook。【原文·全文】https://code.claude.com/docs/en/features-overview
- 上下文工程一文（2025-09-29）：先用最小 prompt 测，再 “add clear instructions and examples to improve performance based on failure modes found during initial testing”；团队常把一长串边缘情况塞进 prompt，“We do not recommend this.”【原文】https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

### 1.2 数量、描述、拆分与合并
- 描述上限 1,024 字符、第三人称、同时写“做什么”和“何时用”；正文 500 行以内；参考文件只嵌套一层。【原文·全文】同上最佳实践页
- 企业治理指南的三条：（1）限制同时加载的 Skill 数量，用评测集量召回，掉了就停；（2）API 每请求最多 20 个；（3）“Start specific, consolidate later”——先窄后并，且 “Merge narrow Skills into a broader one only when the consolidated Skill's evaluations confirm equivalent performance”。【原文·全文】https://platform.claude.com/docs/en/agents-and-tools/agent-skills/enterprise ；20 个上限另见 https://platform.claude.com/docs/en/build-with-claude/skills-guide 【原文】
- 上线前要评的五个维度：触发准确、单独可用、共存（新 Skill 的描述太宽会“抢走”已有 Skill 的触发）、指令遵循、输出质量；每个 Skill 交 3–5 条查询（应触发、不应触发、模糊边界）。【原文·全文】同上企业指南
- 评测结果对应的处置：触发准确下降 → 改描述；共存冲突 → 合并或收窄描述；输出质量持续低 → 重写；多次更新仍失败 → 下线。【原文·全文】同上

### 1.3 什么不该是 Skill
- 电商架构一文（2026-09-02）：“Loading a skill costs a model turn, so anything the agent needs on most turns generally goes in the system prompt.”；安全、法律、品牌类指令放 system prompt；“The prompt is where safe behavior starts, but in commerce it can't be where safety is enforced.” 代码侧强制的例子：后端接口根本没有扣款方法；购物车只接受本会话服务端返回过的商品 ID；价格变动、折扣深度等有上限；合规文案由服务端逐字提供。【原文】https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents
- 同文：单 agent 加 Skill 的组合 “consistently has outperformed” 多 agent 方案；Skill 应以 tool result 形式加载以便随对话前缀缓存；设计目标缓存命中率 90–99%。【原文】
- Claude Code 对比页：“An instruction like ‘never edit .env’ in CLAUDE.md or a skill is a request, not a guarantee … If a rule must hold every time, make it a hook rather than a prompt instruction.”【原文·全文】
- 工具设计一文（2025-09-11）：工具描述本身进上下文、应当像 prompt 一样打磨；“More tools don't always lead to better outcomes”；错误返回要写成可执行的改进提示；用留出集防止对评测过拟合。【原文】https://www.anthropic.com/engineering/writing-tools-for-agents
- Shopify Sidekick（2025-08-26）走的是另一条路：把与某个工具相关的条件性指令随工具返回一起下发，而不是放 system prompt 或单独的 Skill；自述 system prompt 曾变成 “an unwieldy collection of special cases, conflicting guidance, and edge case handling”；工具数 0–20 边界清晰、20–50 边界变模糊、50+ 难以推理。文中没有给量化收益。【原文】https://shopify.engineering/building-production-ready-agentic-systems

### 1.4 归纳成一张放置表（推断，依据即上面各条）

| 内容特征 | 放哪里 | 依据 |
|---|---|---|
| 必须每次成立、可机器判定、涉及钱或不可逆动作 | 服务端代码 / 工具边界校验 | 电商一文；Claude Code hook 规则 |
| 某个工具怎么用、参数格式、出错后怎么办 | 工具描述、工具返回、错误信息 | 工具设计一文；Shopify |
| 多数轮次都要用（约三分之一以上流量）、身份与底线 | system prompt | 电商一文 |
| 偶尔才用、需要判断的多步流程或领域知识，体量够大 | Skill | 最佳实践；对比页 |
| 一两句话的教训 | 改已有 Skill 或 system prompt 的一行，不新建 | 企业指南“合并”；Intercom“少而宽” |

---

## 2. 数量增长时选择 / 触发准确率的定量证据（05 未收录的部分）

- **How Well Do Agentic Skills Work in the Wild**（arXiv 2604.04323，2026-04-06，预印本，未见 venue）：34k 真实 Skill 的检索池。SkillsBench 通过率（%）：

  | 设置 | Claude Opus 4.6 | Kimi K2.5 | Qwen3.5-397B |
  |---|---|---|---|
  | 无 Skill | 35.4 | 21.8 | 20.5 |
  | 人工 Skill，强制加载 | 55.4 | 38.5 | 41.2 |
  | 人工 Skill，模型自行决定 | 51.2 | 38.9 | 31.6 |
  | 人工 Skill + 干扰项 | 43.5 | — | 33.7 |
  | 检索（池中含人工 Skill） | 40.1 | 33.5 | 26.7 |
  | 检索（池中不含） | 38.4 | 19.8 | 19.7 |

  加载过任意 Skill 的轨迹占比（Claude）：62.2 → 44.4 → 16.3；Claude 把人工 Skill 全部加载的比例从 49% 掉到 31%。作者归因：“agents struggle to recognize relevant skills from their names and descriptions alone”，无关 Skill 还会把弱模型拉到基线以下。【原文】https://arxiv.org/html/2604.04323v1
- **SRA-Bench**（arXiv 2604.24594，预印本）：5,400 条测试、636 个标准 Skill 混入共 26,262 个的语料；结论是 agent 加载 Skill 的比率与“是否检索到了正确 Skill、任务是否需要”相近，瓶颈同时在检索和“决定加载什么、何时加载”。【原文·仅摘要，正文数字未读】https://arxiv.org/abs/2604.24594
- **Workday 的渐进加载报告**（arXiv 2609.35692，2026-09-28，预印本）：库规模 N ∈ {5, 20, 50, 100}，三个 7B–14B 的 Qwen 小模型。全部正文塞进 prompt 时，检索成功率在 N=20 就掉到 0.17–0.68，N=50 为 0.13–0.40，N=100 因 prompt 超长全部崩溃；按需加载多数格子在 0.64–1.00（有一格更差：Qwen3-8B 在 N=20 为 0.38 对 0.68）。按需加载的 token 节省：N=5 时 0.5%–41.1%，N=50 时 71.3%–81.7%；延迟一例 +15%（1.75 s → 2.01 s）。局限：合成任务、小模型、未讨论缓存。【原文】https://arxiv.org/html/2609.35692v1
- **SkillsBench 的每任务数量与长度效应**：见第 0 节第 5 点。【原文】https://arxiv.org/html/2602.12670v4
- **AgentSkillOS**（arXiv 2603.02176，预印本）：200 到 20 万个 Skill 的生态规模，树状组织的检索接近理想选择；摘要没有给平铺目录随规模退化的数字。二手文章转述的“平铺 80+ 个后检索不可靠”我没有在摘要里看到。【原文·仅摘要 / 二手】https://arxiv.org/abs/2603.02176 ；https://www.oreilly.com/radar/agent-skills-work-but-the-research-shows-most-teams-are-building-them-wrong/
- 已在 05 的：合成 Skill 库 ≤20 时选择准确率 >95%、超过 50 陡降（GPT-4o 系，预印本 2601.04748）；语义相近的竞争项比数量更致命；Anthropic 文档的 30–50 个工具经验阈值。

小结（推断）：对 2026 年的强模型，6 → 22 个在“数量”上大概率不会出现可测的选择退化；真正的风险是相邻 Skill 描述重叠造成的抢触发，以及库再大也解决不了的“该加载而未加载”。

---

## 3. 人工整理 vs 自动生成；长 prompt 是否伤害行为

### 3.1 自动生成
- **SkillsBench 最终版（v4，2026-06-14；NeurIPS 2026）**：自生成 Skill 的做法是 “the agent first authors skill packs with Anthropic's skill-creator, then solves each task with only those packs”。三个配置全部低于无 Skill 基线：Claude Code + Opus 4.7 −8.1 点，Codex + GPT-5.5 −11.3 点，Gemini CLI + Gemini 3.1 Pro −11.5 点；同配置下人工 Skill 为 +18.2 / +19.7 / +24.8 点。轨迹审计的归因：生成的包求解时没被发现、写 Skill 占用了本该用于解题的工作、用上时内容自信地错。作者自述局限：这个差距 “mixes content quality with skill-discovery and creator/solver interference effects”。87 个任务中 13 个出现人工 Skill 的负增量。【原文；−8.1 等三个数字来自正文而非摘要】https://arxiv.org/html/2602.12670v4
  - 这解决了 04 里留的口径不一致：早期版（84 任务）说“平均无收益”，最终版是“三个配置都更差”。二手文章（O'Reilly，2026-05-18）引用的仍是早期版口径。
  - 需要如实带上的限定：这是“任务前凭空写”，不是“从失败轨迹加外部反馈提炼”。后者有正向证据（04 中 Letta 的 +9% / +15.7% 绝对提升、SkillLearnBench 的外部反馈结论），所以结论是“无外部信号的自写不可信”，不是“自动生成一概无用”。
- **ACE（ICLR 2026）补充 04 未记的细节**：增量条目由 “lightweight, non-LLM logic” 确定性合并；每条带 “counters tracking how often it was marked helpful or harmful”；用语义向量去重；精简可以每次增量后做，也可以只在超出上下文窗口时做。论文没有给 playbook 的体积上限或实际 token 数。作者自述：依赖足够强的反思器；没有可靠信号时上下文会被 “spurious or misleading signals” 污染；“not all applications require rich or detailed contexts”。【原文】https://arxiv.org/html/2510.04618v2
- **GitHub 上 Skill 的演化**（arXiv 2611.04456，2026-11-03，预印本）：84,200 个 Skill、750,898 次提交。58.5% 的 Skill 演化事件少于 5 次；83.1% 的相邻演化发生在一周内；变更动机中“完善性维护”占 50.37%；精简类合计 13.13%（其中去重 3.44%）；结构性变更很少（知识重构 1.74%、流程合并 0.07%）；28.9% 的 Skill 没写触发条件。论文建议在改动前后做回归测试。【原文】https://arxiv.org/html/2611.04456v1
- 没有找到 ACE 的独立复现或 2026 年针对 playbook 膨胀的后续工作。【未核实】

### 3.2 长 system prompt 与上下文退化
- Chroma 技术报告（2025-07-14）：18 个模型，输入越长表现越不稳定，“even on simple tasks”；“Even a single distractor reduces performance relative to the baseline”；同一问题集聚焦版约 300 tokens、完整版约 113k tokens，前者明显更好。【原文】https://www.trychroma.com/research/context-rot
- IFScale（arXiv 2507.11538，2025-07）：同时给 500 条指令时，最好的前沿模型准确率 68%，且偏向靠前的指令。【原文·仅摘要】https://arxiv.org/abs/2507.11538
- Arize 在 2026-05 用同一基准重跑新模型：一年前模型在 200–300 条同时约束处开始丢指令，2026 年的模型推到约 2,000 条量级；Claude Opus 4.7 到 5,000 条时只遵循约一半，DeepSeek V4 Pro 从 750 条左右开始丢。测的是关键词包含，不等同于业务规则遵循；非正式论文。【原文】https://arize.com/blog/llm-instruction-following-benchmark-2026/
- Prompt Design at Scale（arXiv 2607.19257，预印本）：用“全部规则都满足”的严格口径，到 80 条规则时所有模型、格式、位置的满分率都归零。只读到摘要页。【原文·仅摘要】https://www.alphaxiv.org/abs/2607.19257
- 反向证据：对 Claude Code 配置文件的析因研究（arXiv 2605.10039，1,650 个会话）没有发现文件大小、指令位置、文件结构对遵循率的可测影响（大小与冲突两项的贝叶斯因子 0.05–0.10，支持“无效应”）；最大的效应是会话内衰减，每多生成一个函数遵循几率约降 5.6%。【原文·仅摘要】https://arxiv.org/abs/2605.10039
- Claude Code 官方的经验线：常驻说明文件保持在 200 行以内，再长就把参考内容移到 Skill。【原文·全文】https://code.claude.com/docs/en/features-overview

### 3.3 推出的两条
- **人审必须有**：自写 Skill 的三个负数（3.1）加上 ACE 无标签时退化到基线以下（04），说明“反思环直接写入生产”没有证据支持；Anthropic 企业指南也要求 “Skill authors should not be their own reviewers”。
- **库规模要设上限，但公开资料没有给出一个数**：官方只说“量着加、掉了就停”；可引用的参照点是 API 的 20 个、电商参考架构的 5 个、Intercom 的同时生效 100 条（二手）、Atlassian 的“每个 agent 少于 5 个”（二手）。
- **9,000 字符的 system prompt 本身不算长**：按 3.2 的证据，没有理由认为这个体量的 prompt 已经在伤害行为。把内容迁出的理由应当是模块化、改动的回归范围变小，而不是“prompt 太长”。

---

## 4. 公司怎么治理一个会增长的指令 / 流程库

| 公司 | 制品 | 准入与评测 | 审核与发布 | 度量与清理 | 标注 |
|---|---|---|---|---|---|
| Anthropic（企业指南） | Skill | 作者交 3–5 条查询的评测集；单独测 + 与现有 Skill 共存测 | 作者不能自审；生产环境钉死版本；保留上一版用于回滚；内部登记表记用途、负责人、版本、依赖、最近评测 | 定期重跑评测；多次失败即下线；重叠则合并 | 原文·全文 |
| Anthropic（电商一文） | prompt / Skill / 工具 | “A team contributing a skill also contributes its cases”；共享 prompt 改动跑全量；门禁含多次试验的通过率、缓存命中率、每轮成本 | 每个 Skill 和工具单一负责团队；先灰度一个用户群；保留不发版就能关掉单个 Skill 的开关 | — | 原文 |
| Sierra（2026-08-20） | journey | 构建时自动检查（引用了未提供的工具、指令互相冲突等）；可要求模拟对话通过后才能前进 | 指定审核人角色，逐行 diff 评审；分流量发布；每次发布是不可变快照，可即时回滚 | 标注过的线上对话变成回归测试（2024 年文章） | 原文 |
| Decagon（2025-11-05） | AOP / 工具 / 准则 | 发布前用单元测试或模拟对话验证 | 每次编辑是一次带版本的提交，可接 GitHub；审计日志与分支保护；可设为需审批 | 两个生产版本同时间窗对比 CSAT、分流率等 | 原文（产品博客，无数字） |
| Intercom Fin | Guidance / Procedure | 发布前在预览面板试问；模拟对话不走意图匹配，路由要用“受众只限自己”的线上测试 | 版本历史、可回滚、可加备注；“优化”功能检查矛盾、冗余、含糊 | 每条 Guidance 可看被应用次数及其中由 Fin 解决的比例；每条 2,500 字符；每个工作区上限 1,000 条 | 原文 |
| Intercom Fin（补充） | Guidance | — | — | 同时生效上限 100 条（社区里员工答复）；“Guidance 不保证触发，必须稳定生效的行为用受众规则” | 二手 / 原文 |
| Cognition Devin | Knowledge | 系统根据对话反馈自动建议新条目或对已有条目的修改 | 人工编辑后保存或驳回 | 可按用户禁用而不删除；该功能已标记弃用，改用 Skill | 原文 |
| Airbnb | 评测流程 | 黄金集 50–100 条，由产品经理或领域专家标注 | 指定最终决策人 | 每天抽 5% 脱敏线上流量，每周评审，新失败模式变成新评测 | 原文（未见日期） |
| 美团（2026-09-10） | 评测集 | “变更后用评测集回测，确认没有引入退化，再上线 AB” | 门禁要接入流程；安全与数据准确性一票否决 | 错题集；“不要过早拆得太细”“让拆解被真实问题驱动，而不是被完备性焦虑驱动” | 原文 |
| Booking.com（2025-12-08） | — | — | 偏好可逆决策 | 回顾时认为起步的技术栈过于复杂，“probably could have started something much simpler” | 二手（VentureBeat 采访） |

来源：
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/enterprise
- https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents
- https://sierra.ai/blog/release-governance-guardrails-for-agents-at-scale ；https://sierra.ai/blog/agent-development-life-cycle
- https://decagon.ai/blog/decagon-agent-versioning
- https://fin.ai/help/en/articles/13975768-provide-fin-ai-agent-with-specific-guidance ；https://www.intercom.com/help/en/articles/15304795-how-to-build-a-fin-procedure-that-improves-over-time ；https://community.intercom.com/train-fin-94/guidance-limitation-14442
- https://docs.devin.ai/product-guides/knowledge
- https://airbnb.tech/ai-ml/eval-driven-development-lessons-from-evaluating-genai-at-scale/
- https://tech.meituan.com/2026/09/10/Agent-Evaluation-White-Paper-01.html
- https://venturebeat.com/ai/booking-coms-agent-strategy-disciplined-modular-and-already-delivering-2

对照 04 已记的两个开源产品（Hermes、OpenClaw）：它们默认让 agent 直接写 Skill，靠版本快照、闲置 30 天归档、体积上限兜底。面向终端用户的商业客服产品（上表）没有一家这样做，全部是“人或评测门在前”。

共同模式（归纳）：
1. **先改已有，再新建**：Devin 会建议修改已有条目；Intercom 建议相近工作放同一个 Procedure 的分支里；Anthropic 建议重叠就合并。
2. **新条目自带用例**：Anthropic 两篇都这样要求；Sierra 把标注对话转成回归测试。
3. **共存测试**：只有 Anthropic 企业指南把“新增是否让别的 Skill 变差”单列为准入维度；Sierra 用自动检查找冲突指令。
4. **逐条度量**：公开可见的只有 Intercom（应用次数与解决率）。Anthropic 明说 Skills API 目前不提供使用统计，要自己在应用层打日志。
5. **版本、灰度、回滚、单条开关**：各家都有。
6. **负责人**：Anthropic（单一负责团队、作者不自审）、Sierra（审核人角色）明确写了。

---

## 5. Token 账：把文字从 system prompt 挪进 Skill 何时划算

### 已发表的说法
- Anthropic：加载一次 Skill 花一次模型轮次；约三分之一及以上流量用到的留在 system prompt；以 tool result 加载可随前缀缓存。【原文】电商一文
- Skill 正文加载后留在对话里，是逐轮重复成本；元数据每个约 100 tokens 常驻。（05 已记）
- **Skill Blocks**（arXiv 2608.14943，2026-08-14，单作者预印本）是唯一按缓存折算做对比的工作。净节省近似为 Σ(1−pᵢ)sᵢ − [(r−1)(F+c+X) + rT]，即“没用上的可选内容”必须大于“多出来的往返和工具 schema 开销”；缓存读取按 0.1 倍计。结果：
  - 大而多轮、每次只用到一小部分的 Skill 收益最大：ScienceWorld −62.5%，约 1 万 tokens 的合成流程 −73.0%。
  - 短而反复要用的流程收益小甚至为负：ALFWorld 上按块加载 −12.55%，混合方式 −3.18%（置信区间跨 0），按引用文件加载 +24.17%。
  - 被提示得过于积极地加载时反而更贵：SearchQA 上原始输入 +48.4%。
  - 作者给了一个事后经验值：正文约 2K tokens 以下，单纯按需加载不划算；并说明没有扫出完整的盈亏曲线，也没有测延迟。
  - 质量上配对检验没检出差异，但作者强调这不等于证明等价。【原文】https://arxiv.org/html/2608.14943v1
- Workday 报告的 token 节省（第 2 节）比较对象是“把所有正文都塞进 prompt”，且未计缓存，不能直接当作省钱幅度。【原文】

### 自己推的盈亏点（推断，供核对）
设正文 B tokens，描述 m tokens，一次对话 T 次模型调用，加载发生在第 1 次调用后，需要它的对话占比 p，缓存读 0.1 倍、写 1.25 倍，system prompt 始终命中缓存：
- 放 system prompt：每次对话约 0.1·B·T。
- 放 Skill：0.1·m·T + p·[1.25·B + 0.1·B·(T−1) + 额外一次调用的开销 E]。
- 忽略 m 与 E 时，Skill 更省的条件是 p < 0.1T / (1.25 + 0.1(T−1))：T=5 时约 30%，T=10 时约 46%，T=20 时约 63%。计入 E（一次重读整段前缀加一小段输出，量级相当于数百 tokens）后阈值再降；以 B=1,500、E≈750 为例，T=10 时约 36%。
- 这与 Anthropic 的“三分之一流量”经验线同量级。
- 绝对金额很小：一段 1,500 tokens 的正文在命中缓存时每次调用只值 150 个基础输入 token。所以省钱不是迁移的主要理由；延迟（多一次往返）反而是确定的代价。05 第 7 节已有同样判断，这里补的是盈亏公式和外部论文的佐证。

---

## 6. 对本项目的含义（推断）

1. **6 → 22 改成“按失败准入”**：新增一个 Skill 要同时满足四条——有一类重复出现的失败记录；内容是需要判断的流程或知识，不是可用代码判定的规则；相关流量低于约三分之一；正文体量在约 1.5–2K tokens 以上。不满足的分别去代码、工具描述或返回、system prompt 的一行、或并入已有 Skill。
2. **反思环的产出默认是“修改已有 Skill 的补丁”**，新建是例外；每个补丁带至少 3 条用例（应触发、不应触发、边界），先过共存测试再过留出集，最后人审。
3. **给库设显式上限并写明依据**：建议以 20 为硬顶（官方 API 上限），实际按“每加一个就重跑触发评测，掉了就合并”执行。
4. **每个 Skill 记四个数**：加载率、加载后的任务通过率与未加载时的差、误加载率、最近一次评测日期；连续若干个评测周期无加载或无正增量就进入合并或下线评审。阈值是自定的，公开资料没有可抄的数字。
5. **讲增长故事时要主动说出的限制**：常驻索引会随库增长；Skill 不保证触发，所以硬约束不放这里；自动生成的内容没有评测门和人审时有负收益的实证；迁移主要换来模块化和更小的回归范围，不是省钱。

---

## 7. 未能核实的事项

- 阿里云两篇（AgentLoop 的经验自进化闭环 https://developer.aliyun.com/article/1751530 、Skill 评估与优化 https://developer.aliyun.com/article/1755376 ）和 SkillClaw × Nacos（https://developer.aliyun.com/article/1739442 ）：页面只返回了摘要，治理细节与数字未读到。
- 美团 DeepSkill 平台“收录超过 37 万个 Skill”：只见于 36kr 报道，未见官方技术文章。美团白皮书后三篇（冷启动、扩量、自进化）未找到。
- 字节、携程 / Trip.com、Klarna、Expedia：没有找到讲指令库治理的一手工程文章（Expedia 只有 VentureBeat 的会议报道）。
- Intercom Guidance 的数量上限在不同版本帮助文档里出现过 100、250、1,000 三个数；当前页面写 1,000 条 / 工作区，“同时生效 100 条”只有社区答复。
- Atlassian “每个 Rovo agent 少于 5 个 Skill”、AgentSkillOS “平铺 80+ 后检索不可靠”：只见于 O'Reilly 文章的转述。
- SRA-Bench、IFScale、Prompt Design at Scale、2605.10039、AgentSkillOS 只读了摘要页；Prompt Design at Scale 的 NeurIPS 2026 录用状态未确认。
- SkillsBench 自生成条件的三个通过率绝对值（约 34.9% / 35.5% / 24.5%）是用基线减去论文给的差值推出来的，论文可见部分只给了差值；附录 D.6 未读。
- 没有任何公司公开过“触发率或胜率低于多少即下线”的数字阈值，也没有找到“把 system prompt 规则迁入 Skill”前后的公开对照数据（05 已记同一缺口）。
- 没有找到 ACE 的独立复现或针对 playbook 膨胀的 2026 年后续研究。
