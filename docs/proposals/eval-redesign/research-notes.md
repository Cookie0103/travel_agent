# 测评方案调研笔记（2026-10-19 v0.1）

配合 [README.md](README.md) 阅读。本文记录读了什么、各篇文章说了什么、我们采用和不采用哪些做法。

**核实程度**：
- 调研环境里 WebSearch 不可用，论文全部通过 arXiv 检索。
- 标 **V** 的：至少读到了 arXiv 页面上的标题、作者、日期和摘要。其中 Sim2Real Gap、False Success、TravelBench 三篇，主会话又用 WebFetch 单独核对过一遍。
- venue 只有在 arXiv 备注里写明时才标 V；其余凭记忆写的标 **R**，需要再核对。
- 没有逐篇打开 OpenReview 或 ACL Anthology。数字取自摘要，不代表我们自己的表现。

## A. Anthropic 两篇文章（V，全文已读）

### Demystifying evals for AI agents（2026-01）
- **术语**：task（题）、trial（一次运行）、grader（评分器）、transcript（对话记录）、outcome（环境终态，和 agent 声称的结果不是一回事）。
- **三类评分器**：代码型（快、客观、但脆）、模型型（灵活、需要校准）、人工型（金标准、贵）。原则是能用代码就用代码。
- **"评判 agent 产出了什么，而不是它走了哪条路"**：不要要求固定步骤顺序；可以给部分分；judge 要有"Unknown"选项，每个维度单独一个 judge。
- **capability 评测和 regression 评测分开**：前者起步通过率低，后者应接近 100%。题目做到饱和后转入回归集。
- **pass^k 对面向客户的 agent 最重要**。例如单次通过率 0.75，三次全过只有 0.75³≈42%。
- **对话型客服 agent 的做法**：用第二个 LLM 模拟用户；成功是多维的，包括状态检查、轮数上限、LLM rubric。
- **路线图**：从 20–50 道来自真实失败的题开始；题意必须无歧义（两位专家判断一致）；正例反例平衡；每次运行环境隔离；一定要读对话记录（"失败应当看起来是公平的"）。

### Building effective agents（2024-12）
- **workflow 和 agent 的区别**：workflow 走预定义路径；agent 由 LLM 自己决定流程。我们的系统是 agent 外面包了一层很重的 workflow 外壳：服务端状态机、卡片、校验加修复。
- **原则**：选最简单可行的方案；工具文档要当 prompt 来写（poka-yoke，让参数不容易用错）；agent 要从环境获取真实反馈，要有停止条件。

## B. 论文（按主题分组）

| 主题 | 论文 | venue | 核心 | 我们的取舍 |
|---|---|---|---|---|
| 可靠性 | τ²-Bench, Barres et al., 2506.07982 | 未标（V 存在） | 用户也能操作环境（dual-control），仍沿用 pass^k；从"用户只说话"改为"用户也动手"后成绩下降 | **采用** pass^k；用户点卡片、选酒店就是一种"用户动作" |
| 可靠性 | τ-Rec, Narasimhan et al., 2606.10156 | RecSys 2026（V） | 对话推荐场景里，pass^1≈57%，pass^4≈35% | 佐证：规划和推荐类任务的 pass^k 也会下降很多 |
| 可靠性 | Beyond Pass@k (reliability@k), Jiang et al., 2608.14711 | 未标 | 指出 pass@k 估计器被滥用 | 报告里写清楚统计口径 |
| 工具鲁棒性 | Robustness … Inconsistent and Incomplete Tool Responses, Xu, 2608.22676 | 未标 | 研究工具返回不一致或不完整时 agent 的行为 | **采用**：故障题里加入"字段缺失" |
| 用户模拟 | **Mind the Sim2Real Gap in User Simulation**, Zhou et al., 2603.11245 | **COLM 2026（V，已二次核对）** | 451 名真人对比 31 个模拟器：模拟用户过度配合，形成"简单模式"，抬高 agent 成功率 | **采用（前沿点 2）**：使用不配合的模拟用户，并由真人做校验 |
| 用户模拟 | UserProxyBench, Jain et al., 2609.38043 | NeurIPS 2026 workshop（V） | 只换模拟用户，分数就差 15.2 分；最常见的问题是一开始就把信息全说完 | **采用**：信息分多轮透露 |
| 用户模拟 | CUEing User Simulators, Kantharuban et al., 2610.02460 | 未标 | 用校准过的用户嵌入生成人设 | 只借思路：用真人跑过的对话来调整脚本 |
| 用户模拟 | Persona Following Is Not Selective Control, Ren et al., 2609.35036 | 未标 | 改人设的一个属性，会连带改变其他属性 | **采用**：行为由脚本固定，不靠 prompt 控制 |
| 旅行 | ChinaTravel, Shao et al., 2412.13682 | ICLR 2026（V） | 用 DSL 对组合约束做程序化校验；需求来自 1154 名真人 | **采用（前沿点 1 的一部分）**：硬约束用代码逐条校验 |
| 旅行 | **TravelBench** (Beyond Itinerary Planning), Cheng et al., 2512.22673 | **ACL 2026 Main（V，已二次核对）** | 三类子任务：单轮、多轮、无解；用缓存了真实结果的 10 个工具做沙盒 | **采用**："无解或越界"单独设一类题 |
| 旅行 | TripTide, Karmakar et al., 2510.21329 | 未标 | 遇到取消、延误等扰动后修订行程 | 对应"用户中途改变"这类题 |
| 旅行 | Trip+ 2606.21169；GroupTravelBench 2605.25200 | 未标 | 行程可行但"累"；多人偏好冲突时有效率 <12% | 体验 rubric 加入"节奏是否合理"；带小孩题 |
| 旅行（背景） | TripTailor 2508.01432（ACL 2025 Findings）、TP-RAG 2504.08694（EMNLP 2025）、TravelEval 2606.01046（KDD 2026） | V | 大规模基准 | 不采用：地域不符，规模也不符 |
| Judge | Odysseys, Jang et al., 2604.24964 | 未标 | 分项 rubric 打分，比对整段轨迹打分更接近人类判断 | **采用**：每题 3–5 条 rubric，逐条判断 |
| Judge | Policy Invariance (LLM safety judges), Weng et al., 2605.06161 | 未标 | 语义不变的改写，最多会让 9.1% 的判决翻转 | **采用**：做一次 judge 改写自检 |
| Judge | **From Confident Closing to Silent Failure (False Success)**, Advani, 2606.09863 | **FAGEN@ICML 2026（V，已二次核对）** | 对"自称完成、实际没完成"的情况，LLM judge 的 AUROC ≤0.65，容易被自信的收尾措辞带偏；简单 TF-IDF 方法反而更好 | **采用**：虚假声明靠代码对账判定，judge 必须能看到工具返回 |
| Judge | Auditing Failure Attribution, Xu & Gao, 2610.17747 | 未标 | 简单预测器可以匹敌 GPT-4.1 | 佐证：不要盲信 judge |
| 失败归因 | MAST (Why Do Multi-Agent LLM Systems Fail?), Cemri et al., 2503.13657 | NeurIPS 2025 D&B（R，待核） | 14 种失败模式 | 只借分类思路，人工给失败对话打标签 |
| 失败归因 | Which Agent Causes Task Failures and When?, Zhang et al., 2505.00212 | ICML 2025（R，待核） | 定位到具体出错步骤的准确率只有 14.2% | **不采用**自动归因，改为人工读 |
| 工具恢复 | Bench2Robust, Chen et al., 2608.11977 | 未标 | 区分"可恢复"和"不可恢复"的故障回合 | **采用**：故障题标注是否可恢复 |
| 工具恢复 | PALADIN 2509.25238 | 未标 | 故障注入加微调（训练方法） | 只借故障注入的设计 |
| 低成本 | Efficient Benchmarking of AI Agents, Ndzomga, 2603.23749 | 未标 | 只评通过率在 30–70% 之间的题，可减少 44–70% 的题量，排名仍稳定 | **采用**：试跑后剔除全过或全挂的题 |
| 低成本 | Agent psychometrics 2604.00594；PTA-IRT 2609.01603 | 未标 | 用 IRT 选题 | **不采用**：需要大量历史数据 |
| 时延 | AI Agents That Matter, Kapoor et al., 2407.01502 | 2024（早于调研窗口） | 准确率和成本一起报告，画 Pareto 图 | **采用**：画质量 × 时延散点图 |
| 时延 | Realtime-Bench, Tang et al., 2610.22155 | 未标 | 按真实时钟计成功率，表现最好的模型只有 44% | **采用（前沿点 1）**：Success@T |
| 时延 | Timely Machine 2601.16486；Latency and Token-Aware Test-Time Compute 2509.09864 | 未标 | 把真实时钟耗时纳入评测 | 背景 |
| 时延 | 用户耐心或放弃的建模 | — | **没有找到近期论文**（只有 2022 年一篇对话搜索的工作） | 这是空白，由我们自己定义 |

## C. 明确不做
- IRT 或自适应选题：题少、没有历史数据，做不起来。
- 自动失败归因模型、完整的 MAST 分类：精度太低，题少时不如人工读。
- agent-as-a-judge（让 judge 自己调用工具去查）：成本高，而且我们的核对用代码就能完成。
- 训练模拟器、强化学习等训练类方法：属于训练，不属于测评。
- 直接复用大规模旅行基准：地域和对话形态都不符合，只借鉴它们的设计。

## D. 待核实
- MAST 是否收录于 NeurIPS 2025，Who&When 是否收录于 ICML 2025，τ²-Bench 是否被正式录用。
- 2026 年这批 arXiv 论文中，除上面三篇外，其余只读过摘要。
