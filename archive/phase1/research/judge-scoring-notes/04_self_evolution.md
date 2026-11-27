# 04 自进化：Agent 如何用历史 trace 与分数改进 skill / prompt / playbook（截至 2026-11-26）

阅读说明（不是独立章节）：

- 标签含义：**【2026 顶会·已核验】** = 本次在会议官方页面（proceedings / virtual 站点 / ACL Anthology）看到该论文条目；**【2026 workshop】** = 只在 workshop 列表出现，不算主会；**【背景·2025 及更早】**；**【预印本·未核验】** = 只有 arXiv，未找到会议录用证据；**【产品官方文档】**；**【工程博客·非同行评议】**。
- 每条 finding 后面是来源 URL。带“（检索摘要）”的条目表示数字来自搜索结果摘要而不是我直接抓取的原页面，可信度低一档。
- “推断”只出现在各节的 Inferences 里，不是来源原话。
- NeurIPS 2026 的 poster 页面显示会期在 2026-12-08 至 12-11，即“已录用、尚未开会”。

---

## 1. 方法谱系：各方法进化什么、用什么信号、怎么搜索、怎么防过拟合与回归、收益与成本

### Takeaway

2026 顶会里“用 trace + 分数改进文本制品”的两条主线是 GEPA（ICLR 2026 oral：文本反馈驱动的反思式变异 + Pareto 前沿 + 独立验证集选择）和 ACE（ICLR 2026：把 context 当成条目式 playbook，只做增量 delta 更新以避免整体重写导致的 context collapse）；两者都明确依赖可靠的反馈信号，ACE 自己报告了无标签时退化到负收益。针对“自动写/自动改 skill”的独立基准结论偏保守：人工整理的 skill 明显有用，模型自写 skill 的收益不稳定，且多轮自反馈会漂移。

### Cited Findings

**GEPA — 【2026 顶会·已核验：ICLR 2026 oral】**

- 核验方式：检索返回 ICLR 2026 proceedings 条目与 ICLR virtual 的 oral 页面，标题一致（我没有再单独抓取这两个页面的正文） — [ICLR 2026 proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/0e9e708b6f48e14fd0ac29e167413f76-Abstract-Conference.html)；[ICLR virtual oral](https://iclr.cc/virtual/2026/oral/10009494)
- 进化对象：只改 compound AI system 里各模块的 prompt，模型权重冻结（原文：“GEPA evolves only the set of prompts … whereas the underlying LLM weights … remains fixed”） — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)
- 信号：标量分数 + 文本反馈。feedback function μ_f 返回“a numeric score and text feedback including details about the evaluation”，可以按模块给反馈，也可以附人工解释 — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)
- 搜索过程：（a）按训练样本记录各候选的最高分，保留“至少在一个样本上最优”的候选，剔除被严格支配的，再按领先样本数加权采样；（b）选中的候选在 minibatch 上跑，reflection LM 读 prompt、trace、分数、反馈后，只为**一个**模块（round-robin）提出改写；（c）minibatch 分数提升才保留，然后在 D_pareto 上完整打分；（d）可选 Merge，把不同谱系的模块交叉 — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)
- 防过拟合：训练集拆成 D_feedback 和 D_pareto，使用 train/validation/test 划分；论文称反思得到的指令“demonstrate a lower generalization gap”。各集合的具体样本数我没能从抓取内容中拿到 — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)
- 收益：Qwen3 8B 六个任务聚合 45.23 → 54.85（+9.62），同表 MIPROv2 47.84、GRPO 48.91；GPT-4.1 mini 聚合 53.03 → 65.22（+12.19），MIPROv2 58.67、TextGrad 59.14。摘要口径是“比 GRPO 平均高 6%、最多 20%，rollout 最多少 35 倍，比 MIPROv2 高 10% 以上” — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)；[arXiv abs](https://arxiv.org/abs/2507.19457)
- 注意：抓取时发现论文内部口径不完全一致（Table 1 写 +9.62，Table 3 写 +12.44，引言写 “+13%”），引用时应注明取自哪张表 — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)
- 成本：每个 benchmark 总 rollout 1,839 至 7,051 次（GRPO 固定 24,000 次）；追平 GRPO 最佳验证分只需 243 至 1,179 次；只算训练集 rollout 是 79 至 737 次；作者说明大部分预算花在验证集上，验证集只用于选择 — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)

**GEPA 用于 skill 文件（gskill）— 【工程博客·非同行评议】2026-02-18**

- 进化对象是 coding agent 的 skill 文件（`.claude/skills/{repo}/SKILL.md`），信号是 SWE-smith 生成的带可验证测试的任务是否解决；每个仓库约 300 个任务，划分为 train 约 200 / validation 约 50 / test 约 60 — [GEPA blog](https://gepa.dev/blog/2026/02/18/automatically-learning-skills-for-coding-agents)
- 测试集结果（Mini-SWE-Agent + gpt-5-mini）：Jinja 55% → 82%，Bleve 24% → 93%，“under 300 rollouts”；迁移到 Claude Code：Bleve/Haiku 4.5 79.3% → 98.3%，Jinja/Sonnet 4.5 100.0% → 98.5%（作者解释为饱和） — [GEPA blog](https://gepa.dev/blog/2026/02/18/automatically-learning-skills-for-coding-agents)
- 作者自述的局限：proof-of-concept、只测了两个仓库、任务“on the simpler side”、部分 skill 更偏向 SWE-smith 式修 bug 任务；页面引言与图表的数字有出入 — [GEPA blog](https://gepa.dev/blog/2026/02/18/automatically-learning-skills-for-coding-agents)

**ACE (Agentic Context Engineering) — 【2026 顶会·已核验：ICLR 2026】**

- 核验方式：arXiv HTML 标注 “Accepted at International Conference on Learning Representations (ICLR 2026)”，检索同时返回 ICLR virtual poster 页面 — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)；[ICLR virtual poster](https://iclr.cc/virtual/2026/poster/10008343)
- 进化对象：条目式 playbook。每条 bullet 带唯一 ID、helpful/harmful 计数，内容是可复用策略、领域概念或常见失败模式 — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- 三个角色：Generator 产出轨迹，Reflector 从轨迹提炼教训，Curator 把教训写成 delta 条目，再由**非 LLM 逻辑**合并进 context — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- 它要解决的两个失败模式：brevity bias（优化趋向短而泛的 prompt，丢掉领域细节）；context collapse（LLM 每步整体重写累积 context，压成很短的摘要）。实例：AppWorld 上第 60 步 context 为 18,282 tokens、准确率 66.7，下一步被重写成 122 tokens、准确率 57.1，低于不做适配的基线 63.7 — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- 防退化手段：增量 delta（局部编辑，不整体重写）、grow-and-refine（追加 + 原地更新计数）、按语义 embedding 去重 — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- 信号：可以用 ground-truth 标签，也可以只用执行反馈（如代码执行成功或失败）；分 offline（在训练集上优化 system prompt，测试集报告）和 online（测试时每个样本后更新） — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- 收益：AppWorld（offline，有标签）ReAct 基线平均 42.4 → 59.4（+17.0）；FiNER 70.7 → 78.3；Formula 67.5 → 85.5；摘要口径是 agent 任务 +10.6%、金融任务 +8.6% — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- 成本：AppWorld offline 相对 GEPA，延迟 53,898 s → 9,517 s（−82.3%），rollout 1,434 → 357（−75.1%）；FiNER online 相对 Dynamic Cheatsheet，延迟 −91.5%，token 成本 $17.7 → $2.9 — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- 作者自述的局限：依赖“a reasonably strong Reflector”，否则 context “may become noisy or even harmful”；没有可靠反馈时 context “can be polluted by spurious or misleading signals”。数据：FiNER 无标签 offline 71.1（+0.4），online 67.3（−3.4，低于基线） — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)

**Dynamic Cheatsheet — 【2026 会议·已核验：EACL 2026 long paper；属 ACL 系会议，不是 ACL/EMNLP 主会】**

- 核验方式：ACL Anthology 条目 2026.eacl-long.333（检索摘要称页码 7080–7106） — [ACL Anthology](https://aclanthology.org/2026.eacl-long.333)
- 进化对象是推理时不断演化的外部 memory（cheatsheet），不改权重；检索摘要称 Claude 3.5 Sonnet 的 AIME 准确率翻倍以上、GPQA-Diamond 提升 9%（检索摘要，未抓原文核对） — [arXiv 2504.07952](https://arxiv.org/abs/2504.07952v1)
- ACE 论文把它作为 online 基线，并指出两者在缺乏可靠反馈时都可能退化 — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)

**ReasoningBank — 【2026 顶会·已核验：ICLR 2026】**

- 核验方式：ICLR 2026 proceedings 页面的 venue 字段；arXiv comments 写 “Accepted to ICLR 2026” — [ICLR 2026 proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/980ea04d23d1f6908964eba2a74afe45-Abstract-Conference.html)；[arXiv 2509.25140](https://arxiv.org/abs/2509.25140)
- 进化对象：memory item（title / description / content 三个字段），从成功**和失败**轨迹里提炼推理策略；成功与否由 LLM-as-a-judge 自评，不需要 ground truth，作者称自评“does not need to be perfectly accurate” — [Google Research blog](https://research.google/blog/reasoningbank-enabling-agents-to-learn-from-experience/)
- 循环：检索 memory → 执行 → judge → 提炼 → 合并；合并只是直接追加，更复杂的 consolidation 留作 future work — [Google Research blog](https://research.google/blog/reasoningbank-enabling-agents-to-learn-from-experience/)
- 收益（Gemini-2.5-Flash，相对无 memory）：WebArena +8.3%，SWE-Bench-Verified +4.6%，后者每个任务少约 3 步；MaTTS（k=5）在 WebArena 上再 +3% — [Google Research blog](https://research.google/blog/reasoningbank-enabling-agents-to-learn-from-experience/)

**Darwin Gödel Machine (DGM) — 【2026 顶会·已核验：ICLR 2026 poster】**

- 核验方式：检索返回 ICLR 2026 virtual poster 页面；arXiv v3 正文含 ICLR 伦理声明 — [ICLR virtual poster](https://iclr.cc/virtual/2026/poster/10007327)；[arXiv 2505.22954v3](https://arxiv.org/html/2505.22954v3)
- 进化对象：coding agent 自己的 Python 代码（工具、工作流），foundation model 冻结；探索过程本身“fixed and not modifiable by the DGM” — [arXiv 2505.22954v3](https://arxiv.org/html/2505.22954v3)
- 搜索：保留所有历史 agent 的 archive，父代选择大致正比于得分、反比于子代数；跑 80 轮；分级评测（Polyglot 先 10 题再 50 题；SWE-bench 先 60 题，过 40% 再扩到 200 题） — [arXiv 2505.22954v3](https://arxiv.org/html/2505.22954v3)
- 收益与成本：SWE-bench 20.0% → 50.0%，Polyglot 14.2% → 30.7%；“A single run of the DGM on SWE-bench … takes about 2 weeks and incurs significant API costs” — [arXiv 2505.22954v3](https://arxiv.org/html/2505.22954v3)
- 安全措施：沙箱、human oversight、archive 提供“traceable lineage of modifications for review”；作者同时警告只为 benchmark 优化的修改可能引入与人意图不一致的行为 — [arXiv 2505.22954v3](https://arxiv.org/html/2505.22954v3)

**2026 新出现的 skill 相关工作**

- SkillsBench —【2026 顶会·已核验：NeurIPS 2026 poster，页面未注明 track】：87 个任务、8 个领域、18 种 model-harness 配置；人工整理的 Skills 把平均通过率从 33.9% 提到 50.5%（+16.6 pp），各配置 +4.1 至 +25.7 pp；“Focused Skills with at most three modules outperform larger or exhaustive bundles” — [NeurIPS 2026 poster](https://neurips.cc/virtual/2026/poster/139353)；[arXiv 2602.12670](https://arxiv.org/abs/2602.12670)
- SkillsBench 的早期 arXiv 版本（86 个任务、11 个领域）摘要写明：84 个任务里 16 个出现负增量，且 “Self-generated Skills provide no benefit on average”（检索摘要）。最新版 v4 摘要不再出现这句话；另有一条检索摘要说 NeurIPS 版给出自生成 skill −1.3 pp，但我直接抓取 NeurIPS 页面时没有看到这个数字，**此处来源互相不一致，引用前需读正文** — [arXiv 2602.12670v1](https://arxiv.org/html/2602.12670v1)；[arXiv 2602.12670](https://arxiv.org/abs/2602.12670)
- SkillOS —【2026 顶会·已核验：NeurIPS 2026 poster】：执行 agent 冻结，用 RL 训练一个 skill curator 来更新外部 SkillRepo；训练信号是“前面的轨迹更新仓库、后面的相关任务检验更新”；摘要没有给具体数字 — [NeurIPS 2026 poster](https://neurips.cc/virtual/2026/loc/sydney/poster/151446)
- SkillX —【2026 workshop】：检索显示它是 ICML 2026 一个 workshop 的 poster，不是主会论文 — [ICML virtual](https://icml.cc/virtual/2026/82632)
- SkillLearnBench —【预印本·未核验】：20 个任务；所有持续学习方法都优于无 skill 基线，但没有方法在所有任务和模型上稳定领先，更强的模型不稳定地产出更好的 skill；有外部反馈时多轮迭代带来真实改进，只用自反馈会出现 “recursive drift” — [arXiv 2604.20087](https://arxiv.org/abs/2604.20087)
- SkillEvolBench —【预印本·未核验】：180 个任务；skill 条件能改善习得阶段，但在冻结部署阶段收益不稳定；直接复用原始轨迹经常优于提炼后的 skill；更多更新会带来 “episode-specific drift and procedural clutter” — [arXiv 2605.24117](https://arxiv.org/abs/2605.24117)
- “Do Agent Optimizers Compound?” —【预印本·未核验；作者单位 RELAI 是被比较方法之一的开发者，有利益相关】：在 Terminal-Bench 2.0 的两阶段设定下，GEPA 优化后的 agent 迁移到新任务时低于未优化基线；作者结论是只有把 regression control 放进优化循环，收益才会累积 — [arXiv 2607.14004](https://arxiv.org/abs/2607.14004)

**背景与未核验条目**

- Reflexion【背景·NeurIPS 2023】、ExpeL【背景·AAAI 2024】、ADAS【背景·ICLR 2025】：会议信息出自既有知识，本次没有重新抓取页面核验，只作谱系背景 — [Reflexion arXiv 2303.11366](https://arxiv.org/abs/2303.11366)；[ExpeL arXiv 2308.10144](https://arxiv.org/abs/2308.10144)；[ADAS arXiv 2408.08435](https://arxiv.org/abs/2408.08435)
- SkillWeaver【未核验】：只找到 2025-04 的 arXiv 版本，项目页 BibTeX 是 `@inproceedings` 但会议名没拿到。方法是 web agent 探索网站、把练习过程提炼成 Python API 并用环境反馈 honing；检索摘要称 WebArena 相对提升 31.8%（检索摘要） — [arXiv 2504.07079](https://arxiv.org/abs/2504.07079v1)；[项目页](https://osu-nlp-group.github.io/SkillWeaver)
- 自进化 agent 综述 “A Survey of Self-Evolving Agents: What, When, How, and Where to Evolve …”：arXiv 列表称 2026-01 发表于 TMLR，我没有在 TMLR 站点核验。它把进化对象分为 model / context / tools / architecture，把时机分为 intra-test-time 与 inter-test-time — [arXiv 2507.21046](https://arxiv.org/abs/2507.21046)

### Inferences

- 按“进化对象”排一条从轻到重的谱：memory 条目（ReasoningBank、Dynamic Cheatsheet）→ playbook 条目（ACE）→ prompt 或 skill 文件（GEPA、gskill）→ skill 仓库的管理策略（SkillOS）→ agent 自身代码（DGM）。本项目要改的是 markdown skill 文件，落在 GEPA/gskill 与 ACE 之间，不需要碰 DGM 那一档（两周一次运行，成本与安全面都不适合单人 demo）。
- 对本项目最可迁移的三个设计点：GEPA 的“带文本细节的反馈函数 + 每次只改一个模块 + 独立验证集做选择”；ACE 的“增量 delta、不整体重写”；gskill 的 train/validation/test 三段划分。项目已有的规则违规码和分数分量天然就是 GEPA 所说的 μ_f。
- rollout 量级参照：GEPA 全量搜索是 10^3 级（1,839 至 7,051），ACE offline 与 gskill 是 10^2 级（357、<300）。单人 demo 做“一次只验一个候选 patch”的闭环，预算应落在 10^2 级。
- 2026 年的独立证据（SkillsBench 早期版、SkillLearnBench、SkillEvolBench）共同指向：自动写 skill 的收益不能默认成立，必须有外部可验证信号和冻结的检验集。这支持“LLM 只提 patch，接受与否由 held-out + 人决定”的保守设计。
- ACE 报告的 context collapse 和 SkillEvolBench 报告的 procedural clutter 是两个相反方向的失败：一个是越改越短越泛，一个是越加越多越乱。闭环里两头都要设限（patch 只能局部改；skill 文件有体积上限）。

### Gaps

- GEPA 各 benchmark 的 train / validation / test 具体样本数没有从抓取内容拿到，需读论文附录。
- ReasoningBank 的论文正文数字没有直接核对，只拿到 Google Research 博客口径。
- SkillsBench 关于“自生成 skill 无收益 / −1.3 pp”的最终版口径不一致，需读 NeurIPS 版正文。
- SkillOS 的具体收益数字、SkillX 与 Q-Evolve（[ICML 2026 poster 列表页](https://icml.cc/virtual/2026/poster/62030)，只看到标题）的方法细节没有读。
- 没有系统扫 ICML 2026、ACL 2026、EMNLP 2026、KDD 2026、AAAI 2026、IJCAI 2026 的完整录用列表，可能漏掉相关主会论文。
- DGM 的美元成本在附录 E.1，没读到；网上流传的具体金额未核实，不要引用。

---

## 2. 2026 年流行个人 agent 产品里的 skill 自进化机制

### Takeaway

Hermes Agent 和 OpenClaw 都默认让 agent 在会话中直接写入和修改自己的 skill（不经人审），靠事后手段兜底：版本快照与撤销、闲置归档、体积上限、内容扫描；“先提案后批准”在两家都是可选配置而不是默认。Anthropic 的 skill-creator 走的是另一条路：离线、带基线对照的 eval 循环，人看结果给反馈，并用 held-out 分数选最终版本。

### Cited Findings

**Hermes Agent (Nous Research) — 【产品官方文档】**

- 工具：`skill_manage`，动作有 `create`、`patch`（“preferred for updates”）、整文件重写、`delete`、`write_file`、`remove_file`；文档把 skill 称为 agent 的 “procedural memory” — [Hermes docs: Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- 创建时机（system prompt 引导）：做出了值得重复的多步工作流；遇到错误或死路后找到可行路径；用户纠正了它的做法。二手文章常说的“5 次以上工具调用后创建”在我抓取的官方页面上没有看到，**未核实** — [Hermes docs: Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- 校验：只有一个 advisory linter，三条规则（`incident-log-shape`、`references-sprawl` 超过 60 个引用文件、`oversized-body` SKILL.md 正文超过约 24k 字符），“They warn; they never block a write”；文档要求 skill 记录 “lessons, not logs” — [Hermes docs: Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- 人审：`skills.write_approval` 默认 `false`（“write freely”）；设为 `true` 后每次写入先暂存到 `~/.hermes/pending/skills/`，用 `/skills diff`、`/skills approve`、`/skills reject` 处理；它不覆盖通用文件工具或终端的直接编辑 — [Hermes docs: Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- 安全扫描：`skills.guard_agent_created` 默认 `false`，扫描凭据窃取、明显的 prompt injection、外传指令；默认关闭的理由是真实工作流经常误触发；后台自改进 review 产生的写入则**始终**扫描 — [Hermes docs: Configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)
- Curator（后台维护）：默认每 168 小时且空闲至少 2 小时触发；14 天未用标记 stale，30 天未用归档到 `.archive/`；“never auto-deletes”；LLM 合并（consolidation）默认关闭，因为它“makes broad structural changes to your library”；只管 agent 自己创建的 skill，hub 安装的 skill “always off-limits”，手写的也不动 — [Hermes docs: Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator)
- 回滚：合并前打 tar.gz 快照（默认保留 2 份），`hermes curator rollback`；每次改动追加到 `.curator_ledger.jsonl`，可按条撤销；`pin` 防归档与删除，`lock` 禁止 agent 的一切写入 — [Hermes docs: Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator)
- 文档内部不一致：同一页另一处写“30 天 stale、90 天归档”，与 14/30 的默认值冲突 — [Hermes docs: Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator)
- 离线进化仓库 `hermes-agent-self-evolution`：用 DSPy + GEPA 进化 skill、工具描述、system prompt、代码，但只有 Phase 1（skill 文件）已实现；eval 数据来自 `synthetic` 或 `sessiondb`（真实会话历史）；护栏是测试必须 100% 通过、skill 不超过 15KB、不得偏离原用途、“All changes go through human review, never direct commit”；每次优化约 $2–10 — [GitHub: hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution)

**OpenClaw — 【产品官方文档】**

- skill 是带 YAML frontmatter 的 `SKILL.md` 目录，遵循 AgentSkills 规范；合格的 skill 以紧凑 XML 块注入 system prompt，每个约 97 字符加字段长度；超过上限时描述会被截短或丢弃 — [OpenClaw docs: Skills](https://docs.openclaw.ai/tools/skills)
- Skill Workshop 作为内置插件 “enabled by default”，让 agent 保存和更新自己的 skill。触发：会话中发现已学 skill 有错就 patch、把可能重复的多步工作存成流程；对话累计 10 次模型迭代后做后台 review；用户 `/learn`；每日清理把闲置 30 天的 skill 归档，并让 “skill diet” 每个 agent 每天压缩一个过大的 skill — [OpenClaw docs: Skill Workshop](https://docs.openclaw.ai/tools/skill-workshop)
- 审批模式 `autonomous.mode`：默认 `auto`（“Every change applies immediately, saves the previous version first, and can be undone”）；`propose` 只存草稿等人应用；`off` 关闭后台 review — [OpenClaw docs: Skill Workshop](https://docs.openclaw.ai/tools/skill-workshop)
- 校验与限制：名称与 frontmatter 格式校验；安全扫描器的 critical 发现（含明文 secret）会拒绝写入；`maxSkillBytes` 默认 40000；每个 skill 保留最近 10 个版本，可撤销；改动只在新会话生效 — [OpenClaw docs: Skill Workshop](https://docs.openclaw.ai/tools/skill-workshop)
- 文档自述的注意点：学到的 skill 会绕过 agent 的 skills allowlist，只能靠归档隐藏；skill diet 会把 skill 文本发给主模型供应商 — [OpenClaw docs: Skill Workshop](https://docs.openclaw.ai/tools/skill-workshop)
- 第三方 skill：文档要求 “Treat third-party skills as untrusted code. Read them before enabling.”；ClawHub 审计由 SkillSpector、A.I.G、ClawScan 组成，状态分 Pass / Review / Warn / Malicious 等，并声明 “Audits are strong safety signals, but they are not a guarantee that a release is risk-free.” — [OpenClaw docs: Skills](https://docs.openclaw.ai/tools/skills)；[OpenClaw docs: ClawHub security audits](https://docs.openclaw.ai/clawhub/security-audits)
- 生态安全事件的学术证据【2026 workshop，不是主会】：ClawdPwned 审计 2,556 个公开 OpenClaw skill，认定 49 个可能恶意，其中 92.4% 涉及敏感信息泄露 — [ICLR 2026 workshop poster](https://iclr.cc/virtual/2026/10016269)
- 二手报道（未用一手来源核实）：Koi Security 2026-02 审计 2,857 个 skill 标记 341 个恶意；OpenClaw 同月接入 VirusTotal 扫描 — [The Hacker News](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html)

**Claude Agent Skills 与 skill-creator — 【产品官方文档 / 官方仓库 / 官方博客】**

- 官方最佳实践：“Create evaluations BEFORE writing extensive documentation”；流程是先找无 skill 时的失败、建三个场景、测基线、写最少的指令、迭代；检查清单要求 “At least three evaluations created”；`SKILL.md` 正文保持 500 行以内；文档同时说明 “There is not currently a built-in way to run these evaluations” — [Claude docs: Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- 迭代方式：Claude A 帮忙改 skill，Claude B（装载 skill 的新实例）做真实任务，人观察 B 的行为再回到 A；要观察 skill 是否被读、哪些内容被忽略 — [Claude docs: Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- 2026-03-03 的 skill-creator 更新：eval（测试 prompt + 期望）、benchmark 模式（跟踪通过率、耗时、token）、多个独立 agent 在干净 context 里并行跑、comparator agent 盲评两个版本（“They judge outputs without knowing which is which”）、description 触发优化（“improved triggering on 5 out of 6 public skills”） — [Claude blog](https://claude.com/blog/improving-skill-creator-test-measure-and-refine-agent-skills)
- 同一篇把 skill 分成 capability uplift（模型变强后可能不再需要）和 encoded preference（编码团队流程，更持久）；eval 用于发现 “quality regressions” — [Claude blog](https://claude.com/blog/improving-skill-creator-test-measure-and-refine-agent-skills)
- skill-creator 源码里的循环：先写 2–3 个真实测试 prompt；每轮同时跑 with-skill 与基线（新 skill 的基线是无 skill，已有 skill 的基线是改动前的快照 `old_skill`）；grader 写 `grading.json`；`aggregate_benchmark` 输出 mean ± stddev 和 delta；人在 viewer 里逐例给反馈写入 `feedback.json`；结果按 `iteration-N/` 目录保存 — [anthropics/skills: skill-creator SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)
- 改 skill 的原则：避免 “fiddly overfitty changes”；解释原因，全大写的 ALWAYS / NEVER “that's a yellow flag”；读 transcript 删掉造成浪费的部分 — [anthropics/skills: skill-creator SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)
- description 优化循环的防过拟合设计：20 条触发查询（应触发与不应触发各 8–10 条，优先 near-miss 反例），60% train / 40% held-out test，每条跑 3 次，最多 5 轮，最终版本 “selected by test score rather than train score to avoid overfitting” — [anthropics/skills: skill-creator SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)

**Letta — 【产品官方文档 / 官方博客】**

- 当前文档页把后台机制叫 “dreaming”：后台 subagent 回顾近期对话并把更新提交到 MemFS（git 支持的 memory 文件系统）；在完成一定步数或 context 压缩时触发；可选 “Agent reviews before applying”，它会多开一个后台对话、多耗 token，且 “does not ask you for approval”；页面没有描述对这些编辑的校验或回滚 — [Letta docs: sleeptime](https://docs.letta.com/guides/agents/architectures/sleeptime)
- 检索摘要里旧版文档的说法是 sleep-time agent 与主 agent 共享 memory blocks 并异步改写；该旧页面我抓取时返回 404，**与现页面术语不一致，以现页面为准** — [Letta docs: sleeptime](https://docs.letta.com/guides/agents/architectures/sleeptime)
- Skill Learning（【背景·2025-12-02 博客】）：两阶段，先反思轨迹，再用 Anthropic 的 skill-creator 生成 skill；Terminal-Bench 2.0 全部 89 个任务上，只用轨迹学到的 skill 带来 21.1% 相对提升（9% 绝对），加上 verifier 反馈后总计 36.8% 相对提升（15.7% 绝对）；skill 是 `.md` 文件、可用 git 管理 — [Letta blog: Skill Learning](https://www.letta.com/blog/skill-learning/)

### Inferences

- 产品的默认值偏向“先写后补救”（Hermes `write_approval: false`，OpenClaw `autonomous.mode: auto`），因为个人助手的 skill 多是用户自己的操作习惯，写错的代价低且可撤销。本项目的 skill 承载的是业务规则，写错会直接变成规则违规或收入损失，应取两家的**可选保守档**：提案、diff、人批准。
- 四家产品都没有在文档里描述“用独立 held-out 集验证 agent 自写的 skill 是否真的更好”这一步；只有 skill-creator 的 description 优化和 Hermes 的离线进化仓库有明确的评测门。这是研究方法（GEPA、gskill）和产品实践之间目前最大的差距，也是本项目可以讲清楚的差异点。
- 已知失败模式与对应的产品对策可以直接对照搬用：
  - bloat：Hermes linter 的 24k 字符与 60 个引用文件阈值、OpenClaw 的 40000 字节上限与 skill diet、Anthropic 的 500 行建议。
  - 闲置堆积：两家都用“N 天未用归档、不自动删除”。
  - drift：Hermes 把 LLM 合并默认关闭；skill-creator 用改动前快照做基线。
  - 冲突与来源混杂：OpenClaw 用来源优先级解决同名；Hermes Curator 只动 agent 自己创建的 skill。
  - 自写 skill 的安全：两家都有内容扫描，但 Hermes 的默认关闭，OpenClaw 只拦 critical。
- Letta 博客的评测是在全部 89 个任务上学习并报告聚合分，页面没有说明学习与测试任务是否分离；这个数字只能说明“verifier 反馈比纯轨迹更有用”，不能当作泛化收益引用。
- Anthropic 把 skill 分成 capability uplift 与 encoded preference 的框架对本项目有直接用处：低频业务规则属于 encoded preference，评测重点是“是否忠实执行规则”，正好对应规则校验码。

### Gaps

- Hermes “5+ 工具调用后创建 skill”的阈值只见于二手文章，官方页面未见，未核实。
- 没有读 Hermes、OpenClaw 的源码，机制描述全部来自官方文档；文档与实际行为是否一致未验证。
- Koi Security、Snyk 的恶意 skill 统计只有二手报道，没有找到并核对一手报告。
- 没有找到任何一家产品公开的“自写 skill 使任务成功率提升多少”的受控数据（Letta 博客除外，且其设置有上面说的问题）。
- Letta 现行文档里 dreaming 的默认触发步数、可用工具没有写明。
- “其他被广泛使用的个人 agent”没有逐一排查（例如各 coding agent 的 memory 或 rules 自动更新功能），本节只覆盖题目点名的四家。

---

## 3. 从 trace 做失败归因：2026 年的准确率，以及结构化信号的作用

### Takeaway

让 LLM 直接读原始 transcript 做归因仍然不可靠：ICLR 2026 的 AgenTracer 在 Who&When 上把 agent 级准确率做到约 64–70%，step 级只有约 21–43%，而通用大模型更低。能明显提高归因质量的都是结构化或可验证的信号：ground truth、taxonomy 加 few-shot、verifier 日志、以及 counterfactual replay；“规则违规码对比原始 transcript”这一具体对照我没有找到直接实验。

### Cited Findings

**谱系起点（背景）**

- “Which Agent Causes Task Failures and When?” —【背景·ICML 2025 spotlight，已在 icml.cc 与 PMLR 核验】：Who&When 数据集覆盖 127 个 LLM multi-agent 系统、184 条失败标注（算法生成 126，手工构造 58）；最好的方法在“找出责任 agent”上 53.5%，在“定位决定性失败步”上只有 14.2%，部分方法低于随机 — [ICML 2025 poster](https://icml.cc/virtual/2025/poster/45823)；[PMLR v267](https://proceedings.mlr.press/v267/zhang25cq.html)；[arXiv 2505.00212v3](https://arxiv.org/html/2505.00212v3)
- 同一论文的细项（GPT-4o）：给 ground truth 时三种方法的准确率都更高，例如 binary search 的 agent 级准确率在算法生成子集上从 30.11 升到 44.13；日志越长准确率越低，最长一档三种方法都 “converge to near 0%”；o1 与 DeepSeek R1 并不稳定优于 GPT-4o（“stronger reasoning models do not necessarily outperform standard models”） — [arXiv 2505.00212v3](https://arxiv.org/html/2505.00212v3)
- 容忍度的影响：手工子集上 all-at-once 的 step 级准确率在 ±1 步内是 12.07，放宽到 ±5 步是 43.10 — [arXiv 2505.00212v3](https://arxiv.org/html/2505.00212v3)
- MAST（“Why Do Multi-Agent LLM Systems Fail?”）—【背景·NeurIPS 2025，已在 neurips.cc 核验】：1,642 条标注 trace、7 个框架、14 种失败模式分 3 类；人工标注一致性 Cohen's κ = 0.88 — [NeurIPS 2025 poster](https://neurips.cc/virtual/2025/poster/121528)；[arXiv 2503.13657v3](https://arxiv.org/html/2503.13657v3)
- MAST 的 LLM 标注器（o1）：不给 few-shot 时准确率 0.89、κ 0.58；给 few-shot 后准确率 0.94、κ 0.77。按 taxonomy 指导的两次修复让 ChatDev 任务成功率分别 +9.4% 和 +15.6% — [arXiv 2503.13657v3](https://arxiv.org/html/2503.13657v3)

**2026 年的工作**

- AgenTracer —【2026 顶会·已核验：ICLR 2026 poster】：摘要称现有推理模型做这件事 “accuracy generally below 10%”；用 counterfactual replay 和 programmed fault injection 自动标注失败轨迹，训练 AgenTracer-8B；在 Who&When 上比 Gemini-2.5-Pro、Claude-4-Sonnet 最多高 18.18%；把归因结果反馈给 MetaGPT、MaAS 带来 4.8–14.2% 提升 — [ICLR 2026 poster](https://iclr.cc/virtual/2026/poster/10007726)
- AgenTracer 的绝对数字（有 / 无 ground truth）：手工子集 agent 级 69.10 / 63.82，step 级 20.68 / 20.68；自动子集 agent 级 69.62 / 63.73，step 级 42.86 / 37.30。同表 Claude-Sonnet-4 手工子集 agent 级 56.90 / 50.00，step 级 17.24 / 18.97 — [arXiv 2509.03312v1](https://arxiv.org/html/2509.03312v1)
- 标注是怎么来的：counterfactual replay 在失败轨迹的每一步提出修正动作并重放，最早让结果转为成功的那一步记为决定性错误；fault injection 在成功轨迹上故意破坏某一步，若因此失败则该步即为标签 — [arXiv 2509.03312v1](https://arxiv.org/html/2509.03312v1)
- AgenTracer-v2 —【2026 顶会·已核验：NeurIPS 2026 poster】：把归因做成带工具的多跳诊断 agent，用确定性的系统回滚合成 8K 标注数据；称比 GPT-5.2、Gemini-3-Pro 及此前专用 tracer 的归因准确率最多高 21.83%，并在超过 300K token 的轨迹上保持稳健；页面只有这一个准确率数字 — [NeurIPS 2026 poster](https://neurips.cc/virtual/2026/poster/153890)
- AgentDebug —【2026 workshop：ICML 2026 的 “Failure Modes in Agentic AI” workshop poster，不是主会】：五模块失败 taxonomy（memory、reflection、planning、action、system）；称 all-correct 准确率比最强基线高 24%、step 准确率高 17%，任务成功率相对提升 26% — [ICML 2026 workshop poster](https://icml.cc/virtual/2026/77923)
- “Structural Baselines Matter for Agent Failure Detection and Attribution” —【预印本·未核验，2026-10】：一条“永远指认最后一步”的规则不读内容就有 67% 至 96% 的命中率，作者认为这反映的是标注方式而不是 agent 的失败方式；在可用 replay 确认决定性步骤的失败上，该规则跌到接近随机；失败稀少时精度低，建议把这类监控用于“给人工复查排序”而不是替代人工 — [arXiv 2610.16661](https://arxiv.org/abs/2610.16661)
- 其他 2026 预印本（只看到检索摘要，会议未核验）：Who&When Pro（12,326 条通过注入错误得到的失败轨迹）、LongRCA Bench、把归因当作搜索问题的工作 — [arXiv 2608.15242](https://arxiv.org/pdf/2608.15242)；[arXiv 2609.13463](https://arxiv.org/html/2609.13463v2)

**结构化或可验证信号帮助有多大（跨来源的间接证据）**

- 文本反馈对比纯标量：GEPA 的核心主张是利用包含评测细节的文本反馈，比只用稀疏标量奖励的 RL 样本效率高（rollout 最多少 35 倍） — [arXiv 2507.19457](https://arxiv.org/abs/2507.19457)
- verifier 日志对比只读轨迹：Letta 的 skill learning 里，加入 verifier 日志后在纯轨迹学习的基础上再提升 6.7%，并称 feedback-informed skills “better encode common failure modes” — [Letta blog](https://www.letta.com/blog/skill-learning/)
- 有标签对比无标签：ACE 在 FiNER 上有 ground truth 时 78.3，无标签 offline 71.1，无标签 online 67.3（低于 70.7 的基线） — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- 外部反馈对比自反馈：SkillLearnBench（预印本）称外部反馈下多轮迭代有真实改进，只用自反馈会 recursive drift — [arXiv 2604.20087](https://arxiv.org/abs/2604.20087)
- Anthropic 对 grader 的建议：code-based grader 快、便宜、客观、可复现，但对合法变体脆弱；并强调“You won't know if your graders are working well unless you read the transcripts and grades from many trials” — [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

### Inferences

- 本项目的规则校验是确定性的，违规码本身已经回答了“哪条规则、在方案的哪个字段上失败”。这等于拿到了 Who&When 实验里的 ground truth 加上 MAST 式的 taxonomy，所以不需要、也不应该让 LLM 从原始 transcript 里“猜哪里错了”。LLM 只需回答更窄的问题：skill 为什么没挡住这次违规。
- 这个更窄的问题可以先用确定性信号分三类，再交给 LLM：（a）对应 skill 没被加载（看工具调用日志）；（b）加载了但没遵循；（c）skill 里没有这条规则或写错了。这与 skill-creator 把“触发是否正确”（description 优化）和“内容是否有效”（eval）分成两个循环的做法一致。三类对应的修法不同：改 description、改正文措辞、补规则。
- AgenTracer 的方法论说明归因的金标准是干预（重放、注入），不是阅读。本项目的评测本来就能重跑，所以“打上 patch 后在同一批失败用例上重跑”就是最便宜的 counterfactual 验证；LLM 的归因只是提出假设，重跑才是证据。
- 汇报归因结果时用“按违规码与分数分量聚类后的计数表”，不要报“LLM 归因准确率”。在 2026 年最好的专用模型 step 级也只有约 21–43% 的背景下，声称 LLM 读 transcript 就能定位根因是站不住的。
- Structural Baselines 那篇预印本提醒：任何自动归因的结论都要先和一个不读内容的朴素基线比（例如“总是归因到最后一步”或“总是归因到最常见的违规码”），否则高命中率可能只是数据分布造成的。

### Gaps

- 没有找到直接比较“给归因模型规则违规码或分量分数差”与“只给原始 transcript”的实验；上面的支持证据全部是间接类比。
- 现有归因基准几乎都是 multi-agent 系统（Who&When、TracerTraj、MAST），单 agent 加工具加 skill 的场景是否可以直接套用这些数字，没有证据。
- AgenTracer-v2 的绝对准确率、ICML 2026 与 ACL 2026 主会是否有失败归因论文，没有核实到。
- AgentDebug 只在 workshop 列表里核验到；它是否另有主会版本没有查到。
- 没有找到“skill 未触发 / 触发未遵循 / 内容缺失”三分法的公开准确率数据；这是推断出的工程分法。

---

## 4. 方案特征与分数的关系分析：几百条 trial 下可辩护的做法与陷阱

### Takeaway

几百条 trial 只够支持少量预先定义的特征做分组对比和一个小的正则化回归；树模型加 SHAP 只能当探索工具，不能当结论。两个最容易被问倒的点是：同一场景的多次 trial 不独立（要按场景聚类），以及相关性不等于因果（SHAP 作者自己明确警告）。好在评测可以重跑，所以每个“高分特征”的发现都应该用一次干预实验来确认。

### Cited Findings

- 聚类：评测题成组出现时应使用 clustered standard error；在真实评测上，聚类标准误可达朴素标准误的 3 倍以上（DROP 约 3.05 倍） — [Miller, Adding Error Bars to Evals, arXiv 2411.00640](https://arxiv.org/html/2411.00640v1)
- 重复采样：同一题重复 K 次的答案不是独立样本，不能把 K×N 个结果合在一起算标准误 — [arXiv 2411.00640](https://arxiv.org/html/2411.00640v1)
- 配对：比较两个版本时应在题目级配对差上做推断；只要两者的题目得分相关，配对就能降低方差 — [arXiv 2411.00640](https://arxiv.org/html/2411.00640v1)
- 回归样本量：传统经验法则是每个预测参数至少 10 个事件（events per variable）；Riley 等（BMJ 2020）主张改用以“预期 shrinkage 不超过 10%”等准则计算最小样本量，并指出二分类结局的有效样本量约等于事件数与非事件数中较小的一个（检索摘要；BMJ 页面抓取返回 403，未直接核对原文） — [BMJ 2020;368:m441](https://www.bmj.com/content/368/bmj.m441)
- 解释方法的通用陷阱（Molnar 等）：在错误的语境使用解释方法、解释泛化不好的模型、忽略特征依赖、忽略特征交互、忽略不确定性估计、高维问题、做没有依据的因果解释 — [arXiv 2007.04131](https://arxiv.org/abs/2007.04131)
- SHAP 与因果：SHAP 文档中由 Lundberg 等撰写的文章指出 “making correlations transparent does not make them causal!”；XGBoost 之类的模型 “are not inherently causal models, so interpreting them with SHAP will fail to accurately answer causal questions”；只有特征既独立于模型内其他特征、又独立于未观测混杂因素时，SHAP 模式才近似因果效应，否则建议用因果方法或做实验 — [SHAP docs](https://shap.readthedocs.io/en/latest/example_notebooks/overviews/Be%20careful%20when%20interpreting%20predictive%20models%20in%20search%20of%20causal%20insights.html)
- 评测集构成：应同时测试“某行为应该出现”和“不应该出现”的情形，“One-sided evals create one-sided optimization” — [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- 零事件上界（rule of three）：n 次里一次都没发生时，发生率的 95% 置信上界约为 3/n，n 大于 30 时近似较好 — [Wikipedia: Rule of three](https://en.wikipedia.org/wiki/Rule_of_three_(statistics))

### Inferences

- 推荐的分析顺序（每一步都能在面试里讲清楚为什么）：
  1. 先由人写下 10–20 个特征，全部用代码从方案结构里确定性地抽取（例如是否含早餐、酒店到主要景点的距离分档、总价占预算的比例分档、每日景点数、是否满足用户明确提到的偏好）。预先定义是为了避免事后挑特征。
  2. 以**场景**为单位聚合（同一场景的 K 次 trial 先取均值），再做分组对比：有该特征与无该特征的平均分之差，配按场景重采样的 bootstrap 置信区间。报告效应量和区间，不报单独的 p 值。
  3. 同时看 10–20 个特征时，做多重比较校正，或明确把结果称为“探索性、待验证”。
  4. 回归只放少量特征。若有效样本量约 100（例如 300 条 trial 来自 100 个场景），按 10 EPV 的老规则最多放约 5–10 个参数，按 Riley 的更严准则会更少；用正则化 logistic（以“是否高分”为目标）或线性回归，并加入场景类型做分层或固定效应。
  5. 树模型加 SHAP 只用来找可能的交互与非线性，先报告交叉验证表现；表现不比线性模型好就不解读。
  6. 对排在前面的 1–3 个特征做干预：改 skill 让 agent 更多或更少地产出该特征，在同一批场景上重跑，看分数是否按预期方向变化。这一步是本项目相对风控建模的优势，因为风控通常无法对客户做实验，而这里可以。
- 必须分开分析“成交概率”和“收入”两个分量，再看乘积。便宜的方案可能提高成交概率但降低收入，只看乘积会把两个方向相反的效应抵消掉，或者让一个极端高价样本主导结论。
- 最需要主动说明的局限：分数是评判模型算出来的，不是真实用户行为。如果特征本身就是评分函数的输入，这个分析在很大程度上是在反推评分函数。它的正当用途有两个：检查评分函数是否在奖励业务期望的东西（给评判模型做体检）；发现 agent 的哪些行为习惯系统性地拿不到分。不能把它说成“发现了用户喜欢什么”。
- 与风控特征工程的类比能成立的部分：分箱、单变量筛选、看单调性、控制共线性、留出验证。不成立的部分：风控通常有数万到数百万样本和真实标签，这里只有几百条模拟分数，所以结论的强度只能到“值得做干预验证的假设”。
- 场景类型（预算档、城市、同行人）很可能同时影响方案特征和分数，是典型的混杂因素；不分层会出现 Simpson 悖论式的反向结论。

### Gaps

- 没有找到专门针对“LLM agent 输出特征与评判分数”做小样本特征归因的 2026 顶会论文；本节的方法依据来自通用统计与可解释性文献。
- Riley 等的 BMJ 原文未能直接抓取核对，数字出自检索摘要。
- “小样本下正则化（LASSO、ridge）的收缩参数本身估计不稳”这一说法在检索摘要中出现，但我没有核实到对应的原文 URL，因此没有列入 Cited Findings。
- 风控里常用的 WoE / IV 在小样本下的偏差，没有检索到可引用的来源。
- 多重比较校正方法（如 Benjamini–Hochberg）的引用没有在本次检索中核验。
- 本项目的实际场景数、每场景 trial 数、分数分布未知，上面的“有效样本量约 100”只是举例。

---

## 5. 单人 demo 的最小安全闭环：逐步证据，以及 held-out 需要多少条

### Takeaway

题目设想的闭环（离线批处理 → 按规则码与分数分量聚类 → LLM 只给一个 skill 文件提 patch → dev 与 held-out 重跑 → held-out 不回归才接受 → 人批准 → 带 changelog 的版本）每一步都能在 2026 年的论文或官方实践里找到对应做法，没有发现反对其中某一步的证据。主要的诚实性问题在接受门：30–50 条 held-out 只能排除大幅回归（约 20 个百分点量级），不能证明“没有回归”，所以门的表述和设计都要相应收紧。

### Cited Findings

**离线批处理，而不是会话中在线自改**

- ACE 的 online 无标签设置在 FiNER 上低于基线（67.3 对 70.7），作者指出没有可靠反馈时 context 会被误导性信号污染 — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- Hermes 的离线进化仓库把所有改动限定为 “go through human review, never direct commit”，并规定 “No mid-conversation changes” — [GitHub: hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution)
- OpenClaw 的 skill 改动只在新会话生效，运行中的会话保持启动时的快照 — [OpenClaw docs: Skill Workshop](https://docs.openclaw.ai/tools/skill-workshop)

**按失败类别聚类后再改**

- MAST 用 14 类 taxonomy 指导的定向修复带来 +9.4% 与 +15.6% 的任务成功率 — [arXiv 2503.13657v3](https://arxiv.org/html/2503.13657v3)
- Anthropic 建议评测任务从真实失败中来：“20-50 simple tasks drawn from real failures is a great start” — [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- GEPA 的反思步骤读的是带评测细节的文本反馈，而不只是分数 — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)

**一次只改一个文件，做局部 patch**

- GEPA 每次变异只改一个模块（round-robin） — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)
- ACE 用局部 delta 替代整体重写，直接动机是 context collapse（18,282 tokens → 122 tokens，准确率 66.7 → 57.1） — [arXiv 2510.04618v2](https://arxiv.org/html/2510.04618v2)
- Hermes 文档称定向 `patch` 是更新的首选方式 — [Hermes docs: Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- skill-creator 要求避免 “fiddly overfitty changes”，并把全大写 ALWAYS / NEVER 视为警示信号 — [anthropics/skills: skill-creator SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)

**dev 与 held-out 分开，用 held-out 做选择**

- GEPA 把数据分为 D_feedback 与 D_pareto，并另有测试集；大部分 rollout 预算花在只用于选择的验证集上 — [arXiv 2507.19457v2](https://arxiv.org/html/2507.19457v2)
- gskill 的划分是 train 约 200 / validation 约 50 / test 约 60 — [GEPA blog](https://gepa.dev/blog/2026/02/18/automatically-learning-skills-for-coding-agents)
- skill-creator 的 description 优化用 60% / 40% 划分，每条跑 3 次，最终按 test 分数而不是 train 分数选，理由是 “to avoid overfitting” — [anthropics/skills: skill-creator SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)
- 预印本“Do Agent Optimizers Compound?”报告 GEPA 优化后的 agent 在新任务上低于未优化基线，并主张把 regression control 放进循环（有利益相关，未经同行评议） — [arXiv 2607.14004](https://arxiv.org/abs/2607.14004)
- SkillEvolBench（预印本）报告 skill 带来的收益在冻结部署任务上不稳定 — [arXiv 2605.24117](https://arxiv.org/abs/2605.24117)

**回归门与多次试验**

- Anthropic 区分 capability eval（起点通过率低，用来爬坡）与 regression eval（“should have a nearly 100% pass rate”）；因为输出有随机性要跑多次 trial；pass^k 衡量 k 次全部成功的概率，对面向客户的 agent 尤其重要 — [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- skill-creator 的基线是改动前的 skill 快照，汇总报告 mean ± stddev 与 delta，并专门检查高方差（可能 flaky）的用例 — [anthropics/skills: skill-creator SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)

**人批准**

- Hermes 提供 `skills.write_approval` 的暂存、diff、approve / reject 流程；OpenClaw 提供 `propose` 模式 — [Hermes docs: Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)；[OpenClaw docs: Skill Workshop](https://docs.openclaw.ai/tools/skill-workshop)
- skill-creator 的循环以人在 viewer 里逐例反馈为中心 — [anthropics/skills: skill-creator SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)
- DGM 的全部实验在沙箱与 human oversight 下进行 — [arXiv 2505.22954v3](https://arxiv.org/html/2505.22954v3)

**版本、changelog、回滚、体积上限**

- Hermes：合并前快照、可按条撤销的 ledger、`rollback`；OpenClaw：每次改动前存版本，保留最近 10 个，可撤销 — [Hermes docs: Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator)；[OpenClaw docs: Skill Workshop](https://docs.openclaw.ai/tools/skill-workshop)
- skill-creator 按 `iteration-N/` 保存每轮结果 — [anthropics/skills: skill-creator SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)
- 体积：Anthropic 建议 SKILL.md 正文 500 行以内；Hermes 离线进化限制 skill 不超过 15KB；SkillsBench 发现不超过三个模块的聚焦 skill 优于更大的打包 — [Claude docs: best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)；[GitHub: hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution)；[NeurIPS 2026 poster](https://neurips.cc/virtual/2026/poster/139353)

**held-out 要多少条：可引用的公式**

- 配对比较所需题数：n = (z_{α/2} + z_β)² × (ω² + σ_A²/K_A + σ_B²/K_B) / δ²，其中 ω² 是配对差的题间方差，σ² 是同一题重复作答的方差，K 是每题重复次数，δ 是要检出的最小差异 — [arXiv 2411.00640](https://arxiv.org/html/2411.00640v1)
- 论文算例：要在 α = 0.05、power 80% 下检出 3 个百分点的差异（ω² = 1/9，条件方差为 0），需要约 969 题；论文据此建议新评测至少约 1,000 题 — [arXiv 2411.00640](https://arxiv.org/html/2411.00640v1)
- 每题重复 K 次可以降低方差；论文不建议靠降低采样温度来降方差 — [arXiv 2411.00640](https://arxiv.org/html/2411.00640v1)
- 零违规时的上界：n 次里 0 次发生，95% 上界约 3/n — [Wikipedia: Rule of three](https://en.wikipedia.org/wiki/Rule_of_three_(statistics))

### Inferences

**接受门能说明什么（用上面的公式自己算的，不是来源原话）**

设通过与否为二值、新旧版本在同一批 held-out 场景上配对、两版结果不一致的场景占 20%（即 ω² 约 0.2）、条件方差已被重复试验压低，双侧 α = 0.05、power 80%：

| held-out 场景数 | 能可靠检出的通过率变化 |
|---|---|
| 20 | 约 28 个百分点 |
| 30 | 约 23 个百分点 |
| 50 | 约 18 个百分点 |
| 100 | 约 12.5 个百分点 |
| 200 | 约 9 个百分点 |

- 结论：单人 demo 现实能维护的 30–50 条 held-out，只能回答“有没有大幅回归”。小于约 10 个百分点的回归在这个规模下看不见。因此对外的表述应是“在 N 条 held-out 上未观察到大于 X 的回归”，而不是“不回归”。
- 确定性规则违规可以用 rule of three 给出更直观的说法：30 条 held-out 上新增违规为 0，只能说新增违规率的 95% 上界约 10%；60 条约 5%；100 条约 3%。注意同一场景的多次 trial 不独立，n 应按场景数算。

**在这个约束下让门更有意义的做法**

- 把门拆成两层，分别对应 Anthropic 的 regression eval 与 capability eval：
  - 硬门（确定性）：held-out 上每个违规码的违规数都不得增加。这层不靠统计显著性，靠零容忍。
  - 软门（统计）：held-out 上分数的配对差均值，其 95% 置信区间下界要高于事先写下的容忍线（例如 −5%）。用连续分数而不是二值通过率，每条样本的信息量更大。
- 每个场景跑 K = 3 次并先在场景内取均值（skill-creator 也是每条跑 3 次），新旧版本用相同的场景与用户模拟设置，保证是配对比较。
- dev 上的要求应该更强：被针对的那个违规码的违规率必须明显下降，否则说明 patch 没有命中归因假设，直接丢弃，不进入 held-out，以减少对 held-out 的反复查看。
- held-out 被反复用来做接受决定后，会逐渐被“间接拟合”。缓解办法：记录每次查看 held-out 的次数；定期从新失败里补充场景并轮换；另留一小份只在阶段性总结时才跑的最终测试集。这一条是统计常识层面的推断，本次没有检索文献支撑。

**成本估算（推断）**

- dev 40 场景 × 3 次 + held-out 40 场景 × 3 次 = 每个候选 patch 240 次 rollout，旧版本结果可缓存复用。这与 gskill 的“under 300 rollouts”、ACE offline 的 357 次同量级，比 GEPA 全量搜索（1,839 至 7,051 次）低约一个数量级。代价是只评估一个候选，没有搜索；对于“规则没写清楚”这类失败，一个有针对性的候选通常就够了。

**一条可以直接落地的最小流程（综合各节）**

1. 离线取最近一批评测结果，按违规码与分数分量做计数表，取排名第一的一类失败。
2. 用确定性信号把这类失败分成“skill 未加载 / 加载未遵循 / 内容缺失”。
3. LLM 读该类的若干失败样本、对应 skill 全文、违规码说明，只对**一个** skill 文件输出 unified diff 和一句话的归因假设。限制：只能局部改；文件体积有上限；不得删除已有规则条目。
4. 在 dev 上重跑：目标违规码必须下降。
5. 在 held-out 上重跑：过硬门与软门。
6. 人看 diff、两张对比表、若干条 transcript，批准或拒绝。
7. 批准后 skill 版本号加一，changelog 记录归因假设、diff、dev 与 held-out 的前后数字、查看 held-out 的累计次数；保留上一版本以便回滚。被拒绝的 patch 也记录，作为负例。

**这套设计在面试里的辩护点**

- 相对 Hermes、OpenClaw 的默认行为更保守，理由是业务规则写错的代价高于个人习惯写错。
- 相对 GEPA 更省，理由是项目已有确定性的失败标签，不需要靠搜索去发现问题在哪。
- 主动承认门的统计功效有限并给出数字，比声称“自动进化且不回归”更可信。

### Gaps

- 没有找到专门研究“skill 或 prompt patch 的接受门需要多少 held-out 样本”的论文；上表是把通用评测统计公式套到本场景得到的，20% 的不一致率是假设值，需用项目的真实新旧版本对比数据替换。
- “反复使用 held-out 会导致间接过拟合”的文献依据（adaptive data analysis 方向）没有在本次检索中核验，未引用。
- 没有找到“单文件 patch 对比多文件同时改”的直接对照实验；支持证据来自 GEPA 的单模块变异与 ACE 的局部更新这两个相邻设计。
- 没有找到“人批准这一步能拦住多少坏 patch”的量化数据；各产品只是提供了这个开关。
- 反方证据的检索不充分：没有找到主张“无需 held-out、在线自改更好”的 2026 顶会论文，但也没有系统地去找。
- 本次调研没有对照项目约定的两篇首要方法参考（Anthropic 的 Commerce Agents 架构文章与工具设计文章），写报告时需要补上这层对应关系。
- 评判分数本身的噪声（同一方案重复打分的方差）未知；如果评判含 LLM 成分且方差大，上面的样本量估计会偏乐观。
