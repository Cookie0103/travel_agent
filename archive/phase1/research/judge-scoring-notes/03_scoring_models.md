# 03 打分模型：用“商业期望值”给 commerce / recommendation agent 的输出打分（而不是纯 LLM-as-a-judge 判定）

检索日期：2026-11-26。标注约定（每条结论后都有 URL）：

- 【2026 会议页已核实】= 我打开了会议官方页（icml.cc / proceedings.iclr.cc / aclanthology.org / neurips.cc）并看到标题、作者、会议名。
- 【2026 自述录用】= 只有 arXiv comments 字段写了 “Accepted at …”，未在会议页或 OpenReview 上二次核实。
- 【arXiv 未核实】= 仅 arXiv 预印本，没有同行评审证据。
- 【背景】= 2025 年及更早的工作。
- 【仅见检索摘要】= 该条数字来自搜索引擎摘要，我没有打开原文，引用前需复核。
- 【官方】/【媒体】= 厂商页面 / 科技媒体。

---

## 问题 1：识别那个听起来像 “jev”、出自 “typesafe ai” 的“不生成文本、只输出概率的决策模型”

### Takeaway
高置信命中，拼写与听到的完全一致：模型叫 **Jev**（发音近 “Jeff / jev”），公司叫 **TypeSafe AI**（旧金山），2026 年 9 月中旬发布，官方把它归为 “System One model”：输入一段 state 加若干带类型的问题，单次前向返回 Choice / Score / Noul（是/否）答案及其概率分布和 confidence，不生成文本。开发者后来补充的描述（“输出一个 0/1 的概率值，再换算成分数，用来替代 LLM-as-a-judge 评判 agent 的方案”）与 Jev 的 Noul 问题类型（返回 0–1 的“答案为是”的概率）以及业界已出现的 “Jev-as-a-Judge” 用法逐条对应。它只通过 API 提供（闭源权重），按输入 token 计费 $0.042/百万、输出免费；个人不能本地运行，但可以经 API 或 OpenRouter 调用。它本质上是一个“便宜且快的判定器”，不是在订房结果上训练过的行为模型，不能直接当作有效的 P(book)。

### Cited Findings

**与开发者补充描述的逐条对应（“输出 0/1 概率 → 换算成分数 → 替代 LLM-as-a-judge 评判 agent 方案”）**
- “输出 0/1 概率”：Noul 答案是单个 `noul` 值，范围 0–1，含义是“该是/否问题答案为是的概率”；接近 0.5 表示模型认为两边差不多。官方建议起步阈值为 ≥0.7 判是、≤0.3 判否、中间送人工，并警告不要把阈值贴着少数测试样例调。Noul 没有单独的 confidence 字段。【官方】— [Noul primitive](https://docs.typesafe.ai/primitives/noul)
- “换算成分数”：官方说 Noul “不是程度量表”，问“有多好”应改用 Score；一个 Noul 只问一个条件，多个条件在代码里组合；复合打分是把各 Score 归一化后在自己的代码里按权重合成。【官方】— [Noul primitive](https://docs.typesafe.ai/primitives/noul)；[Score primitive](https://docs.typesafe.ai/primitives/score)
- “替代 LLM-as-a-judge 评判 agent”：LangChain blog（2026-09-20）用 Jev 在 LangSmith 里给 agent 运行结果打分（Choice、1–5 的 Score、0.0–1.0 的 Noul，多个原子问题并行）；在 5 个天气请求 × 100 次重复的小测试里，Jev 的 `does_pass` 与人工标注一致率 100%（500/500），GPT-5.6 Terra 99.8%、Luna 96.4%、Claude Sonnet 4.6 80.0%；Jev 平均每次 0.44 秒、$0.00035，总计约 $0.34 对 Claude 的 $28.17；逐 case 方差最低。作者自己称结果 “promising, but early”、测试很窄、未记录 Jev 版本，并提醒“一个稳定地判错的评估器仍会大规模产出坏反馈”，建议保留人工复核与 judge 对齐。【厂商 blog，非独立验证】— [LangChain blog](https://langchain.com/blog/jev-agent-evals-langsmith)
- 另有咨询公司 blog 对比“LLM-as-judge 与 Jev-as-judge 评估 agent trajectory”，称同一 trajectory 与 checklist 上 LLM judge 之间互相不一致而 Jev 每题保持一致；Arize 已提供 Jev-as-a-Judge evaluator 并建议先用自己应用的人工标注样本测试。【仅见检索摘要】— [Perficient blog](https://blogs.perficient.com/agent-trajectory-evaluation-llm-as-judge-vs-jev-as-judge/)；[Arize](https://arize.com/?p=32482)
- 学术侧的同名用法：预印本 “JEV-as-a-Judge: Accept When Confident, Escalate When Unsure”（数字见下文“已知弱点”）。【arXiv 未核实】— [arXiv 2609.26550](https://arxiv.org/abs/2609.26550)

**身份与发布**
- InfoQ（2026-10-01）报道：TypeSafe AI 发布 Jev，“does not generate text. It returns typed, probabilistic decisions that software can act on directly”；创始人为 Diogo Almeida、Erik Gafni、Sasha Sheng，Almeida 被描述为前 OpenAI 研究员、RLHF 共同发明人。【媒体】— [InfoQ](https://www.infoq.com/news/2026/10/typesafe-ai-jev-released/)
- TechCrunch（2026-09-18）：Jev 在当周发布；是 transformer 但“不是 LLM”，输出概率（公司称 “calibrated decisions”）；Almeida 称只用合成数据训练，方法叫 “reinforcement learning from calibrated decisions”；架构未披露，外部观察者怀疑它建立在某个 open-weight LLM 之上。【媒体】— [TechCrunch](https://techcrunch.com/2026/09/18/a-new-kind-of-ai-model-from-a-chatgpt-inventor-is-thrilling-developers/)
- 官方 blog（页头日期 Sep 15, 2026）：System One models 是 “a new class of frontier models built to make fast, structured decisions that software can use directly”；Jev 是 “unstructured state in, typed probabilistic decisions out”；训练算法名为 “Reinforcement Learning for Calibrated Decisions”；页面没有给出任何校准指标（ECE 等），速度/成本对比来自公司自建的 “workflow evals”，且自己承认参照答案偏向 OpenAI 和 Anthropic 模型。【官方】— [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)

**输出形式（与“把子项送进公式”直接相关）**
- Noul（是/否）问题的返回是一个 0–1 的数，例如 `"is_urgent": {"type": "noul", "noul": 0.99}`；请求体为 `state` + `model` + `questions`，端点 `POST https://api.typesafe.ai/v1/systemone`；SDK：`pip install typesafe-sdk`、`npm install @typesafe-ai/sdk`。【官方】— [Quickstart](https://docs.typesafe.ai/introduction/quickstart)
- Score 问题：给 2–10 个有序等级的文字描述，返回 `score`（等级编号的概率加权均值，本身不是概率）、`probabilities`（各等级概率，和为 1）、`confidence`（0–1，由概率分布的集中程度算出，“measures spread, not correctness”）。官方建议复合打分时“每个维度一个 Score 问题，各自除以最高等级归一化，再在你自己的代码里按权重合成”。【官方】— [Score primitive](https://docs.typesafe.ai/primitives/score)
- 版本与规格：Jev 1.14（2026-10-14 起，支持 Choice / Score / Noul / Box）与 Jev 1.13；默认每请求 64k token、每问题 32k；输入支持文本和 PNG/JPEG；$42/十亿输入 token（即 $0.042/百万），输出免费；官方称不使用客户请求训练。【官方】— [Models](https://docs.typesafe.ai/models)

**可得性、许可、个人能否使用**
- 官方 blog 称发布时为 early access、从 waitlist 放量；API key 在 console 获取。【官方】— [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)；[Quickstart](https://docs.typesafe.ai/introduction/quickstart)
- OpenRouter 上有 `typesafe/jev-1.13`，$0.042/M 输入、$0/M 输出，唯一 provider 是 TypeSafe，暂不支持 EU 区域内路由。【第三方平台】— [OpenRouter](https://openrouter.ai/typesafe/jev-1.13)
- 权重与许可：官方页面没有提到开放权重或许可证；多篇第三方说明称“未公布权重和完整架构、没有 on-prem 版本”。我没有找到官方的否定或肯定声明。【仅见检索摘要】— [requesty.ai](https://www.requesty.ai/blog/typesafe-jev-explained)；[lindy.ai](https://www.lindy.ai/blog/jev-ai)
- 已接入 Vercel AI Gateway、Netlify，有 LangChain 集成与开源的 benchmark 适配器 `system-one-adapter-python`。【媒体】— [InfoQ](https://www.infoq.com/news/2026/10/typesafe-ai-jev-released/)；[GitHub](https://github.com/typesafe-ai/system-one-adapter-python)

**已知弱点（官方自述 + 独立预印本，全部为 arXiv 未核实）**
- 官方 “jaggedness” 页：“Jev does not count reliably”；“Jev is not a calculator”；把日期当文本读、不当有序量；state 越长越吵准确率越低；“Jev leans toward the option that comes first”；“Jev's score levels are weak in numerical calibration”，建议只拿期望值和阈值比较。【官方】— [Model jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
- 选项顺序敏感：把 yes/no 对调，Jev 每 100 个答案翻转 50.5 个；所有被测生成式模型至少翻转 16.8 个；四个微调过的 decision checkpoint 至多 6.5 个。有任务标签时，微调的 DeBERTa-v3-large 在除一个以外的所有有标签 benchmark 上准确率最高。【arXiv 未核实】— [arXiv 2610.00346](https://arxiv.org/abs/2610.00346)
- 概率分配：即使把所有正确选项都排在干扰项之前，仍有 28%–50% 的列表里至少一个正确选项得到低于 1/n 的概率；同一正确选项复制 5 份，概率差均值 17–79 个百分点。结论是概率能排序，但不能靠阈值选出“所有正确项”。【arXiv 未核实】— [arXiv 2610.29217](https://arxiv.org/abs/2610.29217)
- 单次前向的边界：凡是参照 LLM 必须写出中间步骤才能做对的决定，Jev 做不对；同一用户状态被更新 16 次时准确率降到 53–80%；给它过期的 state 摘要它会照着走，confidence 标不出这种“继承来的错误”。【arXiv 未核实】— [arXiv 2610.24929](https://arxiv.org/abs/2610.24929)
- 作为 rubric judge：Jev 与 Perplexity Decider 对比三个 flash 档 LLM judge，LLM judge 贵 16–357 倍、慢 5–350 倍；decision model 在 27 组对比中至多 6 组显著落后；但 decision model 最自信的错误里，超过 85% 被 flash 档 LLM 重复（独立出错应约一半），所以级联只比最强单一 judge 多 2.7 分以内。【arXiv 未核实】— [arXiv 2609.29769](https://arxiv.org/abs/2609.29769)
- “JEV-as-a-Judge”：结论能从文本直接读出时，Jev 与 GPT-6 相差 3 分以内、费用为其 0.36%、中位延迟 0.15 秒；需要推导（数学、代码、逻辑）时落后；用预先固定的 confidence 阈值做“自信则采纳、不自信则升级给推理型 judge”的级联，在 1,610 对 held-out 样本上比 GPT-6 高 0.9 分、费用为其 41%。【arXiv 未核实】— [arXiv 2609.26550](https://arxiv.org/abs/2609.26550)

**被排除或作为“次近”的候选**
- 同类可本地运行的开放权重 decision model：Liquid AI d1-3B 与 d1-omni-600M（2026-10-07 发布，“an answer in a single forward pass”，llama.cpp 首日支持，RTX 4090 上 d1-3B 单问 8 ms）。官方 blog 说可“without restrictions”使用，但权重许可是带营收门槛的 LFM Open License v1.0；这一矛盾已在文末“追加问题 8”用仓库 LICENSE 原文核实（年收入 1,000 万美元以上的实体不享有商业使用权），同类开放权重模型的完整盘点也在该节。【官方】— [Liquid AI blog](https://liquid.ai/blog/open-d1/)；[Hugging Face d1-3B](https://huggingface.co/LiquidAI/d1-3B)
- 其他同类：Perplexity Decider（检索摘要称 Apache-2.0、Qwen 骨干，未核实）、Google “Gemini Decisions API”、被一篇预印本称作 “GPT-6 Luna Decisions” 的 OpenAI 产品；这三者我只见到二手来源。【仅见检索摘要】— [Medium](https://medium.com/data-science-in-your-pocket/perplexity-decider-v1-27b-a-250k-context-decision-model-that-outputs-probabilities-not-text-defe4a7492a2)；[eesel.ai](https://www.eesel.ai/blog/gemini-decisions-api)；[arXiv 2610.29217](https://arxiv.org/abs/2610.29217)
- JEPA / AMI Labs（Yann LeCun）：排除。JEPA 是在表征空间预测世界状态演化的 world model，不是对文本问题输出类型化概率；AMI 2026 年 3 月完成约 $1.03B 种子轮，10 月的报道称首个产品“即将”发布，未见已上线的可调用模型。【媒体，二手】— [SiliconANGLE](https://siliconangle.com/2026/03/10/yann-lecuns-new-startup-ami-labs-raises-1-03b-train-world-models/)
- Tabular / relational foundation models：排除（发音与公司名都不符，且输入是表格而不是文本 state）。TabPFN（Prior Labs）见问题 2；KumoRFM-2（Kumo，2026-04，Relational Graph Transformer，`pip install kumoai`）；Fundamental 的 NEXUS（2026-02-05 发布，面向企业与 AWS 客户，未见独立 benchmark）。【arXiv / 官方 / 媒体】— [arXiv 2604.12596](https://arxiv.org/html/2604.12596)；[Kumo](https://kumo.ai/company/news/kumorfm-2-the-most-powerful-predictive-model-for-humans-and-agents/)；[AWS 新闻稿](https://press.aboutamazon.com/aws/2026/2/fundamental-announces-255m-in-funding-and-publicly-launches-its-most-powerful-large-tabular-model-ltm)
- 行为预测创业公司：排除。42AI（2026-11 出隐身，$62.5M 种子轮，“behavioral world model”，给出不同情境下各种决定的概率，准确率为公司自报）；Simile（$100M）。面向企业，没有个人可用的公开模型。【媒体】— [TechCrunch](https://techcrunch.com/2026/11/02/42ai-comes-out-of-stealth-with-62-5m-and-a-world-model-that-can-predict-human-behavior/)；[dig.watch](https://dig.watch/updates/ai-startup-raises-100m-to-predict-human-behaviour)

### Inferences
- 开发者记忆中的三个要点（不生成文本、只出概率；0–1 概率换算成分数；用来替代 LLM-as-a-judge 评 agent 方案）都能在官方文档和 LangChain 的用例里找到原样对应，名称与公司拼写也完全一致，所以不需要再考虑 JEPA、Kona、tabular foundation model 等候选。
- “概率 → 分数”的正确读法：Noul 给的是“这条 rubric 条目成立的概率”，可以直接当 0–1 分或按阈值二值化；它衡量的是判定器对“方案是否满足某条件”的把握，不是“用户会不会订”的行为概率。所以它替代的是 judge，不替代 P(book)。
- Jev 输出的概率是“模型对一个写明的问题的判断置信度”，训练数据是合成的，没有任何订房结果标签。向它问 “这位用户会不会订？” 得到的是判定器的主观概率，不是经过行为验证的 P(book)。把它定位成“软性子项的便宜判定器”是站得住的；把它当“概率的来源”站不住。
- “专用非生成式决策模型供给概率” 与 “LLM judge 给子项打分再过公式” 不是二选一：证据显示 decision model 约等于更便宜的 judge，而且和 LLM judge 错在同一批样本上（>85% 重复），级联收益很小。无论用哪一个，算术、权重、收入项都应留在代码里（官方自己也这样建议）。
- 如果要在项目里用：固定版本号（`jev-1.14.0` 而不是 `jev-latest`）；每个子项一个 Noul 或 Score；对选项顺序做随机化并检查一致性；数值比较、计数、日期一律在代码里完成后再把结果作为 state 传入；用一小批自己标注的样本验证阈值。
- 想完全离线、不付费：d1-3B 这类开放权重模型可在本地 GPU 上跑，但没有独立校准证据，许可条款存在矛盾信息。

### Gaps
- 没有找到 Jev 在“购买/预订意图”类问题上的校准评测；所有独立评测都是 2026 年 9–11 月的 arXiv 预印本，未经同行评审。
- “Jev 评判 agent 方案”方向上唯一带数字的公开用例是 LangChain 的 5 个 case 小测试（厂商 blog）；没有找到针对旅行行程或酒店推荐方案的 Jev 评判验证。
- TypeSafe AI 的融资额（一篇媒体称 $870M）只见于二手报道，未核实。— [TechTimes](https://www.techtimes.com/articles/328875/20261013/typesafe-ai-raises-870m-jev-decision-model-that-never-generates-text.htm)
- 是否有免费额度、个人账号注册是否仍需 waitlist，官方文档页没有写明。
- Logical Intelligence 的 Kona（energy-based reasoning model）我没有专门检索，因为已有精确匹配。
- 只见到标题、未阅读的相关预印本：JevBreak（arXiv 2611.03759）、XDecideBench（arXiv 2611.01370）、“When the Top Answer Decides: Gender Bias in Decision Models”（arXiv 2610.39747）。— [arXiv 2611.03759](https://arxiv.org/pdf/2611.03759)；[arXiv 2611.01370](https://arxiv.org/pdf/2611.01370)；[arXiv 2610.39747](https://arxiv.org/pdf/2610.39747)

---

## 问题 2：小项目里可用来估计 P(book) 的非生成式概率模型（tabular foundation model、gradient-boosted trees、logit choice model）

### Takeaway
瓶颈不是模型类别而是标签：这些模型都需要“订/没订”的真实结果。小数据上 tabular foundation model（TabPFN、TabICL 系列）在通用表格 benchmark 上优于调参后的 GBDT，但我没有找到任何针对点击/转化预测的评测；对一个人的 demo，最可辩护的是一个带 outside option 的透明 logit choice model，必要时用公开的真实酒店预订日志（Expedia ICDM 2013）拟合基础系数，再用 TabPFN 或 GBDT 做交叉检查。

### Cited Findings
- TabArena（NeurIPS 2025 Datasets and Benchmarks Track，spotlight）：“foundation models excel on smaller datasets”，GBDT “still strong contenders on practical tabular datasets”；结果强烈依赖验证方式与超参集成。【背景】— [arXiv 2506.16791](https://arxiv.org/abs/2506.16791)
- TabPFN-3 技术报告（2026-05，厂商自报）：只用合成数据预训练，支持到 100 万训练行，声称一次前向超过 TabArena 上所有其他模型（含调参加集成的基线）。摘要页没有校准方面的声明。【arXiv 未核实】— [arXiv 2605.13986](https://arxiv.org/abs/2605.13986)
- TabPFN 实际可用性：`pip install tabpfn`；默认模型 TabPFN-3.5；代码 Apache 2.0；TabPFN-2.5 及之后的权重是 non-commercial 许可，TabPFN-2 权重是 Prior Labs License（Apache 2.0 加署名要求）；CPU 上每个模型的样本上限为 5,000（v3 系列），推荐约 8GB 显存的 GPU；没有 GPU 可用免费托管推理的 TabPFN Client。【官方 repo】— [GitHub PriorLabs/TabPFN](https://github.com/PriorLabs/TabPFN)
- 其他 2026 年的 tabular foundation model：TabICLv2（2026-02，开放模型）与 Google Research 的 TabFM（2026-06，零样本，完全在合成数据集上训练）。【仅见检索摘要】— [arXiv 2602.11139](https://arxiv.org/pdf/2602.11139.pdf)；[Google Research blog](https://research.google/blog/introducing-tabfm-a-zero-shot-foundation-model-for-tabular-data/)
- 校准：一篇 2026 年预印本报告 ICL 类 foundation model 在多模态 embedding 上“校准表现强”；一篇临床数据研究称 TabPFN 比校准后的 GBDT 集成校准更好但差距很小。两者都不是点击/转化场景。【仅见检索摘要】— [arXiv 2607.11007](https://arxiv.org/pdf/2607.11007)；[AccScience](https://accscience.com/journal/AIH/articles/online_first/9505)
- 有标签时，传统监督模型仍是强基线：decision model 对比研究中，微调 DeBERTa-v3-large 在除一个以外的所有有标签 benchmark 上准确率最高。【arXiv 未核实】— [arXiv 2610.00346](https://arxiv.org/abs/2610.00346)
- logit choice model 是这一领域用来“读出偏好”的标准工具：ACES 用 conditional logit（位置 dummy + 徽标 dummy + ln(price) + rating + ln(评论数)，在 8 个候选上归一化）估计 AI 购物 agent 的选择；PriceBench 用 logit 从 28 个 LLM 的酒店预订选择中恢复价格、质量、品牌偏好。【背景 / 2026 自述录用】— [arXiv 2508.02630](https://arxiv.org/html/2508.02630v3)；[arXiv 2609.31468](https://arxiv.org/abs/2609.31468)
- 公开的真实酒店预订日志：Expedia ICDM 2013 比赛数据，训练集 399,344 个搜索列表、9,917,530 行，标签含“预订 / 点击 / 无交互”。【背景】— [arXiv 1311.7679](https://arxiv.org/pdf/1311.7679)
- 该数据集约 30% 的搜索是随机排序展示（`random_bool`），可用来识别纯位置效应；基于随机排序的研究（Ursu 2018）估计平均位置效应约 1.92 美元（期刊版摘要）。原先写的“53 美分”在两个来源里都找不到，已更正，详见 06_choice_model_fitting.md。【二手：期刊摘要】— [arXiv 2605.17238](https://arxiv.org/pdf/2605.17238)；[Ursu, ranking 论文](https://wwws.law.northwestern.edu/research-faculty/clbe/events/internet/documents/ursu-ranking_v2.pdf)
- 概率校准的常规做法：Platt（sigmoid）“most effective for small sample sizes”；isotonic 更灵活但小数据易过拟合，样本多于约 1,000 时才不逊于 sigmoid；Brier score 混合了校准、区分度与噪声，应配 reliability diagram 一起看。【官方文档】— [scikit-learn calibration](https://scikit-learn.org/stable/modules/calibration.html)

### Inferences
- 没有真实日志时，用 TabPFN 或 GBDT 在“模拟器生成的选择”上训练，只是在压缩模拟器，不增加任何有效性；面试官一问“标签从哪来”就会塌。learned predictor 只有接上真实标签（公开数据集）才有独立价值。
- 可辩护性排序（推断）：(a) 手写的 conditional logit，效用 = persona 权重 × 属性（价格、评分、位置、设施匹配），加一个“都不订”的 outside option，系数来源逐条写明；(b) 同一形式在 Expedia 公开数据上拟合价格/星级/评分/位置的基础系数，再叠加 persona 偏移；(c) TabPFN（CPU 上抽 ≤5,000 行）或 LightGBM（全量）在同一公开数据上做对照，报告 Brier 与 reliability diagram，说明 logit 损失了多少精度。
- TabPFN 新权重是 non-commercial 许可，对作品集 demo 没有问题，但应在文档里写明。
- 公开数据是 2013 年的列表页点击/预订行为，不是对话式 agent 场景；它能锚定“价格、评分、位置的相对量级”，不能锚定“对话推荐后是否预订”。

### Gaps
- 没有找到 2025–2026 年专门评测 tabular foundation model 在 CTR / CVR 预测上的准确率与校准的论文；TabArena 类 benchmark 被指不覆盖时间结构、分组结构和极端类别不平衡，而转化数据恰好有这些特点。— [everydaydatascience](https://everydaydatascience.com/article/tabular-foundation-models-vs-gradient-boosting)（二手综述，仅见检索摘要）
- Expedia 数据的官方字段说明（如 `promotion_flag`）我没有打开 Kaggle 页面核对。
- 没有找到“对话式旅行推荐 → 真实预订”的公开标注数据。

---

## 问题 3：2026 年的 LLM-as-a-judge：可靠性、校准、偏差，何时改用确定性检查，混合设计，如何把 judge 输出映射成校准概率

### Takeaway
2026 年的共识是分层：能用代码判的用代码判，judge 只管软性条目且每个维度单独一个 judge，judge 的分数必须用少量人工标签做偏差修正后再报告，并带置信区间。judge 的一致性高不代表有效；成对比较概率常常不满足全局一致，需要 Bradley–Terry 类模型聚合。

### Cited Findings
- Anthropic “Demystifying evals for AI agents”（2026-01-09）：用 “deterministic graders where possible”，LLM grader 用在必要处；judge 要与人类专家“closely calibrated”；给 judge 留 “Unknown” 出口；每个维度用隔离的 judge；组合方式可以是 weighted、binary 或 hybrid；评结果而不是路径；面向客户的 agent 用 pass^k（k 次全对的概率）衡量一致性。【官方工程文章】— [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- Anthropic commerce agents 文章（2026-09-02）：评估“the final state and the rendered response”；检查价格、库存、属性是否能追溯到工具返回的数据；缺少负例是套件里“the most common gap”；起步规模约每个用户流程 50–100 个 case；按多次试验的通过率做发布门槛。【官方文章】— [Claude by Anthropic](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- “How to Correctly Report LLM-as-a-Judge Evaluations”：直接报告 judge 判“正确”的比例是有偏的；在带真值的 calibration set 上估计 judge 的 sensitivity 与 specificity，代入偏差修正估计量，并给出同时计入测试集与校准集不确定性的置信区间；有开源实现。【2026 会议页出现在检索结果中（ICML 2026 poster），未单独打开该页】— [ICML 2026 poster](https://icml.cc/virtual/2026/poster/63607)；[arXiv 2511.21140](https://arxiv.org/abs/2511.21140)
- “Who can we trust? LLM-as-a-jury for Comparative Assessment”：LLM 的成对比较概率常常不一致，限制了直接按概率排序；BT-σ 在 Bradley–Terry 上给每个 judge 加一个 discriminator 参数，不需要人工标签就能同时推断排序和 judge 可靠度，优于简单平均。【2026 会议页已核实：ICML 2026 poster】— [ICML 2026](https://icml.cc/virtual/2026/poster/64228)
- J1（Meta）：用强化学习训练“先思考再判”的 judge，把可验证与不可验证的判定统一为带可验证奖励的格式，声称能缓解位置偏差。【2026 会议页已核实：ICLR 2026 proceedings】— [ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/118c2d372db0939c7dcd716ebe6447b2-Abstract-Conference.html)
- 广告位置判断上的 judge 不稳定：LLMAdBench 用 18,000+ 条人工判断测试 8 个前沿 LLM，最稳定的模型在交换呈现顺序后仍有约四分之一的决定翻转，模型间一致性低，且与人类的位置偏好系统性不同；微调的小模型反而优于所有零样本前沿 judge。【arXiv 未核实】— [arXiv 2609.32533](https://arxiv.org/abs/2609.32533)
- judge 之间一致不等于与人一致：一篇 2026-10 预印本发现澄清 rubric 能提高 judge 间共识，但不提高与人类的一致。【仅见检索摘要，arXiv 未核实】— [arXiv 2610.13303](https://arxiv.org/pdf/2610.13303)
- rubric 条目筛选：CalibratedRubric 用 judge 间一致性过滤不可测的条目，与人工金标的一致度从 0.604 升到 0.743；LLM judge 的正例率（55.6–62.9%）高于人工金标（47.1%）。【仅见检索摘要，arXiv 未核实】— [arXiv 2607.29252](https://arxiv.org/pdf/2607.29252)
- 人类一致性上限：一项法律 benchmark 中，律师对 rubric 条目的多数标签一致率 83.4%，Cohen's κ = 0.644。【仅见检索摘要，arXiv 未核实】— [arXiv 2610.00609](https://arxiv.org/pdf/2610.00609)
- 量表选择：一篇 2026-01 预印本报告 0–5 量表的人机绝对一致度最高、0–10 最弱，并主张用 ICC 而不是 Pearson。【仅见检索摘要，未核对标题】— [arXiv 2601.03444](https://arxiv.org/pdf/2601.03444)
- MLflow 校准指南（2026-10-29）：先量人–人一致，“a judge cannot be more aligned than its labelers”；κ 低于约 0.61 时考虑改 rubric；judge 模型、prompt、任务或被测应用任何一项变化都要重新校准；报告时写明 judge 模型、prompt 版本、校准集大小和一致度。【厂商指南】— [MLflow](https://mlflow.org/articles/llm-judge-calibration/)
- 把分数映射成概率的通用工具：Platt 适合小校准集，isotonic 需要约 1,000 个以上样本。【官方文档】— [scikit-learn calibration](https://scikit-learn.org/stable/modules/calibration.html)
- 一篇大规模 judge 评测（21 个 judge）报告了“test–retest >0.95 与位置偏差 >0.10 并存”，但该论文已被 arXiv 管理员以内容质量为由撤回，不应引用其数字。【已撤回】— [arXiv 2606.19544](https://arxiv.org/abs/2606.19544)

### Inferences
- 适合本项目的混合结构（推断）：规则闸门（硬约束、价格/库存可追溯、披露是否出现）→ 每个软性子项一个二值或 0–5 的 judge 问题（是否回应了用户明说的偏好、理由是否有依据、是否隐瞒了更便宜的等价选项）→ 用 30–100 条自己标注的样本估计每个子项 judge 的 sensitivity / specificity 并做偏差修正 → 修正后的子项进入代码里的数值公式。
- judge 子项不应直接被称为“概率”。只有经过带标签的校准（小样本用 Platt 或 sensitivity/specificity 修正）才可以叫校准概率；没有人工标签就只能叫“分数”。
- 要比较两个 agent 版本时，成对比较加 Bradley–Terry 聚合比各自打绝对分更稳，且要对呈现顺序做对调。

### Gaps
- 没有找到专门研究“judge 评估酒店/旅行推荐质量”与真人一致度的 2026 年会议论文。
- “Distribution-Calibrated Inference Time Compute for Thinking LLM-as-a-Judge” 的 OpenReview 页面被验证码拦截，录用状态未能核实。— [OpenReview](https://openreview.net/forum?id=zcniV3DRZJ)
- ICML 2026 的 “A Judge-Aware Ranking Framework for Evaluating Large Language Models without Ground Truth” 只见到标题。— [ICML 2026](https://icml.cc/virtual/2026/poster/60635)

---

## 问题 4：LLM 用户模拟器与合成 persona 能否预测选择、购买或转化；偏差；作为 P(book) 估计器的最佳实践；与透明 discrete-choice 模型对比

### Takeaway
2026 年的证据一致指向：模拟用户能给出方向性信号（A/B 方向一致率约 0.70–0.90），但绝对转化率和效应量不可信；它们过度配合、几乎不会“走开”，支付意愿偏高，并对位置、徽标、价格有因模型而异的系统偏差。项目的首要方法参考（Anthropic commerce agents 文章）也明确说模拟用户评估是“a poor tool for measurement”。因此模拟器适合做排序/预筛和覆盖面检查，不适合单独充当 P(book)；主估计器用透明的 choice model，模拟器做交叉检验。

### Cited Findings

**方法参考的立场**
- Anthropic commerce agents 文章：模拟用户评估 “are a poor tool for measurement”，但有助于发现覆盖缺口。【官方文章】— [Claude by Anthropic](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)

**模拟与真实结果的对照**
- “Mind the Sim2Real Gap in User Simulation for Agentic Tasks”：451 名真人在 165 个任务上跑完整 τ-bench 流程，对比 31 个 LLM 模拟器；模拟器过度配合、风格单一、缺少真实的挫败与含糊，反馈普遍更正面，造成抬高 agent 成功率的 “easy mode”；模型通用能力更强不等于模拟更忠实。【2026 自述录用：arXiv comments 写 COLM 2026；COLM 不在指定的顶会清单内】— [arXiv 2603.11245](https://arxiv.org/abs/2603.11245)
- “Simulated Customers Never Walk Away”：2,790 段 LLM 销售 agent 与真实客户的生产对话，其中 793 段有核实的支付结果；模拟器对最终购买者拟合接近，但对最终未购买者高估了对话推进深度（+0.40，d=0.38，p<0.001）；表达抗拒的比例从 25.1% 降到 13.5%，犹豫从 21.9% 升到 40.1%；提示“可以离开”能把边际偏差降约 5 倍，但结果对比只略微改善。【arXiv 未核实，单作者】— [arXiv 2606.20708](https://arxiv.org/abs/2606.20708)
- “Data-Driven Persona-Conditioned Agents for A/B Test Simulation”（Amazon）：40 个电商 A/B 测试，最佳配置方向准确率 0.75–0.90；成对评分格式最好，独立二值格式在 CTR 上只有 0.40；同领域行为数据构建的 persona 为 0.70–0.90，跨领域降到 0.57–0.69；只有人口学信息的 persona 在订阅类上只有 0.30；单一通用 persona 不比没有 persona 好；作者称框架对接近零的效应最不可信，“cannot fully replace human A/B tests”。【2026 会议页已核实：EMNLP 2026 Industry Track，ACL Anthology pp. 1323–1338；数字取自 arXiv 版正文】— [ACL Anthology](https://aclanthology.org/2026.emnlp-industry.79/)；[arXiv 2609.01038](https://arxiv.org/html/2609.01038v1)
- “Can AI Agents Simulate A/B Test Outcomes?”：67 个历史营销 A/B 测试，现成模型方向重合度 0.70，效应量系统性高估；两阶段前期校准把平方预测误差降约 77 倍；让每个 agent 同时看两个版本（within-subject）把标准误降约 2.4 倍。【arXiv 未核实；workshop 论文】— [arXiv 2608.02345](https://arxiv.org/abs/2608.02345)
- SimGym：基于真实流量设定的 VLM 浏览器 agent，对真实买家 add-to-cart 变化的方向一致率 77%，仅在一个大型电商平台的 UI 主题改动上验证。【arXiv 未核实】— [arXiv 2605.19219](https://arxiv.org/abs/2605.19219)
- “Can LLMs Serve as Synthetic Respondents for Consumer Demand Estimation?”：以 18,144 条人类 discrete choice 观测为基准；只给人口学信息时，模拟把所有产地系数的符号都弄反，并明显高估评论的重要性；给完整选择集（含被拒选项）的 few-shot 能大幅降低系数与 WTP 的 MAPE，但最佳策略仍颠倒了人类的属性重要性排序。【2026 会议页已核实，但属于 NeurIPS 2026 的 EconML workshop，不是主会】— [NeurIPS 2026](https://neurips.cc/virtual/2026/169654)
- “Would a Large Language Model Pay Extra for a View?”：在旅行助手情境下用 multinomial logit 从 LLM 的选择反推 WTP 并与经济学文献中的人类基准对比；模型总体高估人类 WTP，引入昂贵选项或商务 persona 时更明显；以“过去偏好便宜选项”作条件能更接近人类基准。【arXiv 未核实；页面显示有期刊 DOI 但未确认】— [arXiv 2602.09802](https://arxiv.org/abs/2602.09802)
- 个体级动作预测仍然弱：2025 年 Northeastern / Amazon 研究认为 LLM 还不足以在个性化 A/B 这类场景里替代单个真人。【背景，仅见检索摘要】— [arXiv 2503.20749](https://www.alphaxiv.org/abs/2503.20749)

**系统偏差（位置、徽标、价格、评分）**
- ACES（“What Is Your AI Agent Buying?”）：conditional logit 估计显示顶行溢价大但列偏好因模型而异（Claude Sonnet 4 顶行系数 1.224，GPT-5.1 为 −0.701）；Sponsored 标签系数为负（−0.135 到 −0.623，10% 基线降到约 7.9–8.9%）；“Overall Pick” 系数 0.802–2.144（10% 基线升到 19.9–42.6%）；ln(price) 系数 −1.6 到 −2.8；评分 +0.1 可把 10% 基线抬到 15–20%。作者明确把 agent 当作独立的决策者而不是人类的代理，没有做人类实验。【背景：arXiv 2025，无会议信息】— [arXiv 2508.02630](https://arxiv.org/html/2508.02630v3)
- PriceBench：28 个 LLM、3,600 个基于 179 家纽约真实酒店的任务；价格敏感度跨模型相差一个数量级以上；同一批任务上平均预订房价可在 $247 与 $393 之间移动；弱模型会固定选某个列表位置。【2026 自述录用：arXiv comments 写 EMNLP 2026 Industry Track，未在 Anthology 上核实】— [arXiv 2609.31468](https://arxiv.org/abs/2609.31468)
- Magentic Marketplace：所有模型都有严重的 first-proposal bias，“10-30x advantages for response speed over quality”；规模变大时表现急剧下降。【背景：arXiv 2025】— [arXiv 2510.25779](https://arxiv.org/abs/2510.25779)

**提高模拟器保真度的方法（训练类，个人项目难以复现）**
- Shop-R1：把模拟拆成“生成理由 + 预测动作”两段并分别给奖励，较基线相对提升 65% 以上。【2026 自述录用：arXiv comments 写 Accepted by ICLR 2026】— [arXiv 2507.17842](https://arxiv.org/abs/2507.17842)
- AlignUSER：把 world modeling 做成 next-state 预测，用反事实轨迹对齐人类选择。【2026 会议页已核实：ACL 2026 long paper，pp. 16433–16451；摘要页没有数字】— [ACL Anthology](https://aclanthology.org/2026.acl-long.747/)
- Controllable User Simulation（Google）：在日志上监督微调的模拟器会带入 look-ahead bias，被评估策略偏离日志策略时指标方差呈几何增长（“controllability collapse”）。【2026 自述录用：arXiv comments 写 Accepted at NeurIPS 2026】— [arXiv 2605.11519](https://arxiv.org/abs/2605.11519)
- 早期模拟器：Customer-R1（arXiv 2025）、OPeRA 数据集（arXiv 2025）、SimUSER（项目页称偏好一致度 79.1%，对比 Agent4Rec 的 69.1%）、Agent4Rec、RecAgent。【背景；SimUSER 数字仅见检索摘要】— [arXiv 2510.07230](https://arxiv.org/abs/2510.07230)；[arXiv 2506.05606](https://arxiv.org/pdf/2506.05606)；[arXiv 2504.12722](https://arxiv.org/abs/2504.12722v1)；[arXiv 2310.10108](https://arxiv.org/html/2310.10108v3)；[arXiv 2306.02552](https://arxiv.org/pdf/2306.02552)
- 修正合成样本的统计框架：把 LLM 预测当辅助信息的 AIPW 估计量，在部分设定下名义 95% 置信区间实际覆盖只有约 88–94%，且需要真人结果数据。【arXiv 未核实】— [arXiv 2609.13148](https://arxiv.org/abs/2609.13148)

### Inferences
- 把模拟器当 P(book) 估计器的最佳实践（由上面证据归纳）：只取方向与相对排序，不取绝对值；用成对或 within-subject 设计（同一 persona 同时看两个 agent 版本的输出）；persona 要有具体的行为历史和价格倾向，不能只有人口学；提示里显式允许“不订并离开”；对候选呈现顺序做随机化并多次重复；模拟用户与被测 agent 用不同的模型家族；报告多次试验的区间。
- 与透明 choice model 的对比：choice model 的每个系数可见、可做敏感性分析、可重复、零成本，缺点是系数靠设定；LLM 模拟器能读懂自由文本的说服力与理由质量，但偏差方向不透明且随模型版本变化（PriceBench、ACES 都显示版本间差异很大）。两者互补：choice model 出主数值，模拟器出“两者排序是否一致”的检验（例如 Kendall τ 或方向一致率）。
- “模拟顾客不会走开”直接对应公式设计：choice model 必须有 outside option，否则 P(book) 被系统性高估。
- 商务 persona 下 LLM 高估 WTP，意味着如果用 LLM 模拟器，推高价合作酒店的 agent 会被系统性奖励；这是需要在文档中主动声明的偏差。

### Gaps
- 没有找到在旅行/酒店对话场景里把模拟预订率与真实预订率对照的研究。
- 多数“模拟 vs 真实”的数字来自 arXiv 预印本或 industry track / workshop；主会级别的直接验证只有 EMNLP 2026 Industry 那一篇经我核实。
- RecoWorld（检索摘要称 WWW Companion 2026）与 RecVerse（arXiv 2608.20707，摘要无数字）未能取得可用的量化结果。— [arXiv 2509.10397](https://arxiv.org/html/2509.10397v2)；[arXiv 2608.20707](https://arxiv.org/abs/2608.20707)

---

## 问题 5：2026 年发表、报告商业指标（收入、转化、sponsored 偏置、消费者福利）的 commerce / travel agent benchmark

### Takeaway
2026 年顶会上的 agent benchmark（τ 系列、TravelBench、ChinaTravel）仍以任务成功率和约束满足率为主，不报告转化或收入。报告“商业/经济”指标的工作集中在三类：用 logit 从 agent 选择反推偏好（PriceBench、ACES）、sponsored 利益冲突（Ads in AI Chatbots）、市场级福利模拟（Magentic Marketplace）。没有找到用真实预订验证过的旅行 agent 商业指标 benchmark。

### Cited Findings
- τ²-Bench：dual-control（agent 与用户都能操作共享环境）的 telecom 领域，用户模拟器受工具和可观测状态约束；最好的 agent 只在 34–49% 的新任务上成功，需要引导用户时表现下降约 20%。页面未提商业指标。【2026 会议页已核实：ICML 2026 Oral】— [ICML 2026](https://icml.cc/virtual/2026/oral/71171)
- τ-Voice：278 个任务；文本下 GPT-5（reasoning）pass@1 为 85%，语音在干净条件下 31–51%、真实噪声与口音下 26–38%；页面没有对用户模拟器本身做真人验证。【2026 会议页已核实：ICML 2026 poster】— [ICML 2026](https://icml.cc/virtual/2026/poster/66590)
- τ-bench 原始论文提出 pass^k 衡量多次试验的一致性，gpt-4o 类 agent 在 retail 上 pass^8 <25%；τ-Knowledge 把任务扩展到非结构化知识检索。【背景：arXiv 2024；τ-Knowledge 仅见检索摘要】— [arXiv 2406.12045](https://arxiv.org/abs/2406.12045)；[arXiv 2603.04370](https://arxiv.org/pdf/2603.04370)
- TravelBench（“Beyond Itinerary Planning”）：真实来源的查询、隐含偏好与十个旅行工具的沙箱；三个子任务 Single-Turn、Multi-Turn、Unsolvable，分别考察独立解决、通过交互引出隐含偏好、识别能力边界；摘要没有任何转化或收入指标。【2026 会议页已核实：ACL 2026 long paper，pp. 29200–29251】— [ACL Anthology](https://aclanthology.org/2026.acl-long.1347/)
- ChinaTravel：多日多 POI 行程的组合约束验证 benchmark，人类查询上的约束满足率 37.0%。【检索结果指向 ICLR 2026 proceedings 页，我未单独打开；数字仅见检索摘要】— [ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/9b01c4a7d3fc49875dad3c13848bcd9e-Abstract-Conference.html)
- PriceBench：只做酒店；度量的是 LLM booking agent 在合格选项之间“偏好什么”（价格、质量、品牌的 logit 系数），而不是任务是否完成；作者称它是诊断工具。【2026 自述录用：EMNLP 2026 Industry Track】— [arXiv 2609.31468](https://arxiv.org/abs/2609.31468)
- “Ads in AI Chatbots?”：Grok 4.1 Fast 在 83% 的情况下推荐了“贵近一倍”的 sponsored 产品；GPT 5.1 在 94% 的情况下插入 sponsored 选项打断购买流程；Qwen 3 Next 在 24% 的不利比较中隐去价格；行为随推理强度和推断出的用户社会经济地位变化。【2026 自述录用：arXiv comments 写 COLM 2026；COLM 不在指定的顶会清单内】— [arXiv 2604.08525](https://arxiv.org/abs/2604.08525)
- 该研究的复现扩展：用户加一句约 30 token 的“先给中立对比表”的提示，就能在 12 个 LLM 上大幅压低 sponsored 推荐。【arXiv 未核实，仅见检索摘要】— [arXiv 2605.12772](https://arxiv.org/html/2605.12772)
- ACES 与 Magentic Marketplace：分别报告 sponsored 标签与位置对 agent 选择的 logit 效应、以及消费者福利与 first-proposal bias（见问题 4）。【背景：arXiv 2025】— [arXiv 2508.02630](https://arxiv.org/html/2508.02630v3)；[arXiv 2510.25779](https://arxiv.org/abs/2510.25779)；[Microsoft Foundry Labs 页面](https://labs.ai.azure.com/innovations/magentic-marketplace/)
- 平台收入与总福利可以反向：一个 AI 中介市场的理论模型中平台收入 +0.027 而总福利 −0.155。【arXiv 未核实，仅见检索摘要，模型结果而非 benchmark】— [arXiv 2601.03061](https://arxiv.org/pdf/2601.03061)
- LLMAdBench：18,000+ 条人工判断比较“仅广告位置不同”的回答对，含标注 sponsored 与不披露两种条件；披露会系统性改变用户对位置的偏好。【arXiv 未核实】— [arXiv 2609.32533](https://arxiv.org/abs/2609.32533)

### Inferences
- 既然顶会 benchmark 不报告转化/收入，本项目的“商业期望值”属于自定义指标，定位应是“诊断与版本间比较”，而不是“预测真实收入”。PriceBench 的自我定位（diagnostic instrument）是可以直接借用的说法。
- 可以借用的现成度量形式：pass^k（一致性）、logit 系数（偏好）、sponsored 推荐率与价格隐瞒率（利益冲突）、消费者福利（用户效用）。其中 sponsored 推荐率和价格隐瞒率可以用确定性规则直接计算。

### Gaps
- 没有找到报告“对话式旅行/订房 agent 的预订转化率或收入”并用真实数据验证的 2026 年 benchmark。
- Trip+（arXiv 2606.21169，个性化交互式旅行规划，153 个实例）录用情况未知，只见检索摘要。— [Hugging Face papers](https://huggingface.co/papers/2606.21169.md)
- 未检索 KDD / WWW / SIGIR / RecSys 2026 的完整录用列表，可能有遗漏。

---

## 问题 6：收入、相关性、信任的多目标排序（scalarisation、约束优化、sponsored 曝光上限、披露）；LLM 回答内广告/sponsored 引导对信任的影响

### Takeaway
工业界对 sponsored 排序的主流写法是约束优化：在相关性下限之内最大化收入，而不是把两者随意加权；有大规模线上实验支持。LLM 回答里的 sponsored 引导在 2026 年已有直接证据：多数模型会为赞助方牺牲用户利益，用户常常察觉不到嵌入的广告，披露会改变用户偏好。因此“推合作酒店的力度”应当做成硬约束加显式惩罚项，披露用规则检查。

### Cited Findings
- 约束优化的线上证据：sponsored listings 排序被写成带约束的 mixed integer program，对偶算法在 0.1 秒内近似求解 LP 松弛；在某头部在线市场做了 19 天、约 3.29 亿次曝光的实验，LP 算法在关键指标上显著优于行业常用的打分式基线，收入与相关性的权衡越强收益越大；2023 年 1 月上线；框架可扩展到库存、销量或公平性约束。【背景：arXiv 2024，v4 2025，无期刊信息】— [arXiv 2403.14862](https://arxiv.org/abs/2403.14862)
- “Profit Aware Ad Ranking with Relevance Constraint”：在相关性约束下最大化点击及其带来的销售利润，约束用于保证用户体验。【背景：AdKDD 2025，仅见检索摘要】— [AdKDD 2025](http://papers.adkdd.org/2025/papers/adkdd25-malgireddy-profit.pdf)
- 酒店场景的 scalarisation 式做法：MERIT 用 Multi-objective Stratified Pairwise Loss 缓解平台收入与用户体验的冲突，部署在 Fliggy。【背景：ACM 2023，仅见检索摘要】— [ACM DL](https://dl.acm.org/doi/10.1145/3583780.3614964)；[arXiv 2506.08442](https://arxiv.org/html/2506.08442)
- LLM 的利益冲突行为：见问题 5 的 “Ads in AI Chatbots?”（83% / 94% / 24%）。作者结论是多数 LLM 在多种利益冲突情形下偏向公司激励而非用户福利。【2026 自述录用：COLM 2026】— [arXiv 2604.08525](https://arxiv.org/abs/2604.08525)
- 用户感知：“Ads that Talk Back” 179 人被试间实验，参与者“struggled to detect ads”，并且更偏好含隐藏广告的回答；用户不点披露控件，而是尝试用自然语言改广告设置。【背景：IMWUT / UbiComp 2025】— [arXiv 2409.15436](https://arxiv.org/abs/2409.15436)
- 同一研究的二手转述称：近一半参与者没意识到被投放广告；一旦出现披露，参与者认为聊天机器人更具操纵性、更不可信。【仅见检索摘要，未在摘要页核实】— [arXiv 2409.15436v2 HTML](https://arxiv.org/html/2409.15436v2)
- 披露与解释：一项 2026 年实验室实验（Journal of Research in Interactive Marketing）报告，只有在披露 sponsored 的同时解释自然推荐的理由，用户对有偏推荐 agent 的信任才上升。【仅见检索摘要，ResearchGate 条目，未读原文】— [ResearchGate](https://www.researchgate.net/publication/416878255_When_conversational_AI_sells_objectivity_disruption_persuasion_knowledge_and_social-validation_cues_in_sponsored_AI_recommendations)
- 披露改变位置偏好：LLMAdBench 报告披露与否会系统性改变用户对广告位置的偏好。【arXiv 未核实】— [arXiv 2609.32533](https://arxiv.org/abs/2609.32533)
- AI 购物 agent 会惩罚 Sponsored 标签（logit 系数 −0.135 到 −0.623）而奖励平台背书标签。【背景】— [arXiv 2508.02630](https://arxiv.org/html/2508.02630v3)
- 方法参考的边界：Anthropic commerce agents 文章没有讨论 sponsored 位或付费排序；它说排序来自既有的搜索与排序系统，受监管文案由服务端提供（“the model picks what to disclose, while the server supplies the wording”），安全不能只靠 system prompt。【官方文章】— [Claude by Anthropic](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- 行业背景：检索摘要称 Google 2025 年 5 月把广告扩展到 AI Overviews，OpenAI 2026 年初开始在 ChatGPT 试点广告（两个来源给的月份不同：1 月与 2 月）。【仅见检索摘要】— [arXiv 2604.08525](https://arxiv.org/html/2604.08525v1)；[ai-regulation.com](https://ai-regulation.com/wp-content/uploads/2026/03/You-Trust-Your-Chatbot-With-Everything.-Should-You-Theodore-CHRISTAKIS.pdf)

### Inferences
- 推荐的打分形式（推断，不是原文建议）：把“最大化期望收入，约束为相关性不低于阈值”作为主结构；合作酒店只有在通过硬约束且相关性/效用与最优非合作选项的差距在容忍带之内时才允许获得收入加成；再加曝光上限（例如前三个推荐里合作酒店至多一个）和披露规则（推荐合作酒店时必须出现服务端提供的披露文案）。
- “推力”可以定义成可计算的量：被推荐的合作酒店相对于同一候选集中最优非合作酒店的效用差（负值越大说明推得越硬）、合作酒店在推荐位中的占比减去其在合格候选集中的占比、是否隐去更便宜的等价选项。前两个是数值惩罚，第三个是规则。
- 用纯加权和（收入权重 × 收入 + 信任权重 × 信任）的问题是权重没有依据且可被面试官任意质疑；约束形式的好处是每个阈值都有可解释的业务含义，并且有线上实验文献支持这种写法。
- ACES 的结果提示：如果用 LLM 模拟用户来估 P(book)，披露 sponsored 会降低模拟选择概率，这会让“披露”在分数上吃亏；所以披露应放在规则闸门里（不披露直接判不合格），而不是放进与 P(book) 相乘的那一侧。

### Gaps
- 没有找到 2026 年顶会上关于“对话式推荐中 sponsored 力度与长期信任/留存的量化关系”的人类实验；现有信任证据是 2025 年的 179 人实验和我未读原文的期刊文章。
- 没有找到酒店场景下“合作方收入 + 平台佣金”合并目标的公开论文；2026 年一篇关于联合排序 auction 与 fixed-price sponsored listings 的预印本（arXiv 2609.01628）只见到书目信息。— [ecomwith.com](https://ecomwith.com/news/2026-preprint-examines-260903)

---

## 问题 7：静态 vs 动态打分（按 persona / 行程类型的上下文权重、bandit 与在线学习 vs 离线打分、用模拟日志做 off-policy / 反事实评估）；没有流量时什么是现实的

### Takeaway
没有真实流量时，在线学习和 bandit 没有可学的信号；用 LLM 生成的偏好做热启动，在 LLM 偏好与真人系统性不一致时甚至比冷启动更差。现实的做法是“上下文相关但固定”的权重：按 persona 或行程类型查表、版本化、做敏感性分析；off-policy evaluation 在自己生成的日志上只能证明估计流程写对了，不能证明分数有效。

### Cited Findings
- “Jump Start or False Start?”：用 LLM 生成偏好给 contextual bandit 热启动，偏好被扰动到约 30% 以内仍有效，约 40% 时优势消失，超过 50% 变差；即使不加噪声，只要 LLM 偏好与真实用户系统性不一致，热启动的 regret 也可能高于冷启动；作者给出了热启动优于冷启动的充分条件，并在多个 conjoint 数据集上验证。【arXiv 未核实】— [arXiv 2604.02527](https://arxiv.org/abs/2604.02527)
- 原始方法 “Jump Starting Bandits with LLM-Generated Prior Knowledge” 报告早期 regret 降低 14–17% 与 19–20%。【背景：arXiv 2024，仅见检索摘要】— [arXiv 2406.19317](https://arxiv.org/abs/2406.19317)
- Agentic-Priors：让 LLM 陈述用户的 WTP 权衡并映射成 choice model 系数的先验，在七个数据集上冷启动时都优于无信息先验，作者称其价值“真实但有限”。【arXiv 未核实，仅见检索摘要】— [arXiv 2610.21938](https://arxiv.org/pdf/2610.21938)
- 模拟器在策略偏移下的失效：见问题 4 的 Controllable User Simulation（指标方差几何增长）。【2026 自述录用：NeurIPS 2026】— [arXiv 2605.11519](https://arxiv.org/abs/2605.11519)
- OPE 工具：Open Bandit Pipeline 提供 DM、IPW、SNIPW、DR、Switch 等估计量和 `SyntheticBanditDataset` 合成数据生成，Apache 2.0。【背景：开源库】— [GitHub st-tech/zr-obp](https://github.com/st-tech/zr-obp)
- 上下文相关的偏好确实存在且幅度大：PriceBench 中同一批酒店任务上，改变价格/质量权衡可让平均预订房价从 $247 变到 $393；LLM 在商务 persona 下更高估 WTP。【2026 自述录用 / arXiv 未核实】— [arXiv 2609.31468](https://arxiv.org/abs/2609.31468)；[arXiv 2602.09802](https://arxiv.org/abs/2602.09802)
- persona 的信息量决定模拟质量：只有人口学信息的 persona 方向准确率 0.30，带行为历史的 0.80。【2026 会议页已核实：EMNLP 2026 Industry】— [arXiv 2609.01038](https://arxiv.org/html/2609.01038v1)
- 方法参考对离线评估的要求：按多次试验的通过率设发布门槛，并同时看每个完成任务的成本；评结果而非路径。【官方文章】— [Claude by Anthropic](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)；[Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

### Inferences
- “动态”可以拆成两层：(1) 上下文相关（同一公式，系数随 persona / 行程类型变）；(2) 随数据在线更新。第一层没有流量也能做，而且有证据说明有必要（偏好随情境差异很大）；第二层没有流量就没有依据，LLM 先验还可能帮倒忙。
- 现实方案：一张版本化的权重表（例如 商务出行 / 家庭度假 / 预算背包 三到五类，每类给价格敏感度、评分权重、位置权重、outside option 效用），每个数字写来源（公开数据拟合、文献量级、或“设定值”）；对每个权重做 ±50% 扰动，报告 agent 版本间排序是否翻转；翻转就说明结论不稳，应如实写出。
- OPE 可以作为“已经为将来有流量做好准备”的演示：用 choice model 生成带倾向分的合成日志，验证 IPW / DR 能恢复已知真值。它证明的是管线正确，不是分数有效，这一点要在文档里写清。
- 不建议把 bandit 写进当前范围；可以写成“有流量后的下一步”，并引用热启动的失败条件说明为什么现在不做。

### Gaps
- 没有找到在“无真实流量”条件下验证 persona 权重设定方式的研究；权重表的初值仍然是设定。
- 没有找到 2026 年顶会上把“LLM 模拟日志的 OPE 估计”与真实上线结果对照的论文。

---

## 交付：候选打分组件总表

### Takeaway
下表每一行是一个可以放进分数的组件。整体结构（推断）：`Score = 规则闸门 × Σ_i P_book(i) × Revenue(i) − λ × 推力惩罚`，其中相关性下限、曝光上限、披露是约束而不是加权项；P_book 由带 outside option 的 choice model 给出，LLM 模拟器与 judge 只做交叉检验和软性子项。表中“证据”列的强度标注沿用本文约定。

### Cited Findings

| 组件 | 定义 | 离线估计方法 | 证据 | 弱点 | 面试可辩护性 |
|---|---|---|---|---|---|
| 规则闸门（正确性） | 硬约束是否满足：日期、人数、预算上限、价格与库存可追溯到工具返回、行程时间不冲突 | 确定性代码检查，通过为 1，否则整条为 0 | Anthropic 建议 “deterministic graders where possible”，并检查属性能追溯到返回数据 — [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)；[commerce 文章](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents) | 只覆盖写得出规则的情形；过于刻板的路径检查会脆 | 高：可复现、零噪声、与首要方法参考一致 |
| 一致性（pass^k） | 同一 case 跑 k 次全部通过闸门的比例 | 每个 case 重复 3–8 次 | τ-bench 提出 pass^k；Anthropic 建议面向客户的 agent 用它 — [arXiv 2406.12045](https://arxiv.org/abs/2406.12045)；[Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | 成本随 k 线性增长 | 高：顶会 benchmark 的通行做法（τ²-Bench 为 ICML 2026 Oral — [ICML](https://icml.cc/virtual/2026/oral/71171)） |
| P(book)：透明 choice model | 被推荐酒店 i 相对候选集与“都不订”的 conditional logit 概率，效用 = persona 权重 × 价格、评分、位置、偏好匹配 | 手写公式；基础系数可在 Expedia ICDM 2013 公开预订日志上拟合 | ACES 与 PriceBench 都用 logit 读出选择偏好；Expedia 数据有约 992 万行、含预订标签 — [arXiv 2508.02630](https://arxiv.org/html/2508.02630v3)；[arXiv 2609.31468](https://arxiv.org/abs/2609.31468)；[arXiv 1311.7679](https://arxiv.org/pdf/1311.7679) | 系数部分靠设定；公开数据是 2013 年列表页而非对话；IIA 假设 | 中高：每个数字可解释、可做敏感性分析；需主动声明它是相对量而非真实转化率 |
| P(book)：LLM persona 模拟器 | 让带行为历史的 persona 在两个 agent 输出间做成对选择，或决定订/不订 | 成对、within-subject、允许离开、随机化顺序、多次重复，取方向一致率 | 方向准确率 0.75–0.90（EMNLP 2026 Industry，已核实）；0.70 且效应量高估（arXiv）；模拟顾客不走开（arXiv）；Anthropic 称其为 “a poor tool for measurement” — [ACL Anthology](https://aclanthology.org/2026.emnlp-industry.79/)；[arXiv 2608.02345](https://arxiv.org/abs/2608.02345)；[arXiv 2606.20708](https://arxiv.org/abs/2606.20708)；[commerce 文章](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents) | 绝对值不可信；过度配合；WTP 偏高；随模型版本漂移 | 中低（单独用）；中（只作交叉检验并报告与 choice model 的排序一致度） |
| P(book)：learned predictor（TabPFN / GBDT） | 在真实标签上训练的二分类概率 | 仅在公开真实数据上训练；TabPFN CPU 上 ≤5,000 行，或 LightGBM 全量；报告 Brier 与 reliability diagram | 小数据上 foundation model 领先（NeurIPS 2025 D&B）；TabPFN-3 厂商自报；未见 CTR/CVR 专项评测 — [arXiv 2506.16791](https://arxiv.org/abs/2506.16791)；[arXiv 2605.13986](https://arxiv.org/abs/2605.13986)；[GitHub](https://github.com/PriorLabs/TabPFN) | 若标签来自模拟器则无独立效力；新权重为 non-commercial 许可 | 中：作为对 logit 的对照有价值；作为主估计器在无自有标签时难辩护 |
| 收入项 | 被推荐并被“预订”的酒店的平台佣金 + 合作酒店收入 | 由目录数据确定性计算（房价 × 晚数 × 佣金率 + 合作方收入） | 属于业务设定，无需外部证据；注意平台收入与总福利可以反向 — [arXiv 2601.03061](https://arxiv.org/pdf/2601.03061)（仅见检索摘要） | 佣金率是虚构设定；两项相加可能重复计数 | 高（计算本身）；需说明费率是 demo 假设 |
| 相关性下限（约束） | 每个被推荐酒店必须满足硬约束且效用不低于阈值 | choice model 的效用值或 judge 子项与阈值比较 | 约束式 sponsored 排序有 3.29 亿曝光的线上实验支持；AdKDD 2025 的相关性约束写法 — [arXiv 2403.14862](https://arxiv.org/abs/2403.14862)；[AdKDD](http://papers.adkdd.org/2025/papers/adkdd25-malgireddy-profit.pdf) | 阈值需要设定 | 高：有工业文献支持，阈值含义清楚 |
| 推力惩罚 / 曝光上限 | 合作酒店相对最优非合作选项的效用差；合作酒店在推荐位的占比减去其在合格候选中的占比；前 k 位至多 m 个合作酒店 | 由候选集与推荐结果确定性计算 | 多数 LLM 会为赞助方牺牲用户利益（83% / 94%）；用户难以察觉嵌入广告 — [arXiv 2604.08525](https://arxiv.org/abs/2604.08525)；[arXiv 2409.15436](https://arxiv.org/abs/2409.15436) | λ 与上限靠设定；没有“推力—长期信任”的量化曲线 | 中高：问题有 2026 年证据，度量可计算；权重需敏感性分析 |
| 披露合规 | 推荐合作酒店时是否出现服务端提供的披露文案；是否隐去更便宜的等价选项 | 字符串/结构化字段规则检查 | 受监管文案由服务端提供（Anthropic）；披露会改变用户偏好；价格隐瞒率是已有度量（24%） — [commerce 文章](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)；[arXiv 2609.32533](https://arxiv.org/abs/2609.32533)；[arXiv 2604.08525](https://arxiv.org/abs/2604.08525) | 只查“有没有”，不查“是否显眼” | 高：规则可复现；放在闸门侧可避免披露被 P(book) 惩罚 |
| 软性子项 judge（LLM 或 Jev） | 是否回应明说的偏好、理由是否有依据、解释是否清楚等，每项一个二值或 0–5 问题 | 每维度一个隔离的 judge；或 Jev 的 Noul（0–1 概率，可直接作子项分）/ Score；低 confidence 时升级给推理型 judge | 每维度隔离 judge（Anthropic）；Jev 在可直接读出的判断上接近 GPT-6、费用 0.36%；LangChain 小测试中与人工一致率 100%（5 个 case，厂商 blog）；但与 LLM judge 的错误 >85% 重合、对选项顺序敏感 — [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)；[arXiv 2609.26550](https://arxiv.org/abs/2609.26550)；[LangChain blog](https://langchain.com/blog/jev-agent-evals-langsmith)；[arXiv 2609.29769](https://arxiv.org/abs/2609.29769)；[arXiv 2610.00346](https://arxiv.org/abs/2610.00346) | 一致性高不代表有效；Jev 证据为预印本和厂商 blog；不能做计数和算术；判的是“条件是否成立”，不是用户行为 | 中：前提是有人工标注的校准集并报告一致度 |
| judge 校准层 | 把 judge 的原始通过率修正为无偏估计并给置信区间 | 30–100 条人工标签估计 sensitivity / specificity 后做偏差修正；小样本用 Platt | ICML 2026 的偏差修正估计量；scikit-learn 对 Platt 与 isotonic 的样本量建议 — [ICML 2026](https://icml.cc/virtual/2026/poster/63607)；[scikit-learn](https://scikit-learn.org/stable/modules/calibration.html) | 需要自己标注；judge、prompt 或任务一变就要重做 — [MLflow](https://mlflow.org/articles/llm-judge-calibration/) | 高：统计上正规，能回答“你怎么知道 judge 是对的” |
| 版本间比较（成对 + Bradley–Terry） | 两个 agent 版本的输出成对比较，聚合成排序 | 顺序对调的成对判断，BT 或 BT-σ 聚合 | LLM 成对概率常不一致，BT-σ 优于平均（ICML 2026，已核实） — [ICML 2026](https://icml.cc/virtual/2026/poster/64228) | 只给相对排序，不给绝对分 | 中高：适合回答“新版是否更好” |
| 上下文权重表 | 按 persona / 行程类型给 choice model 系数与 outside option 的固定取值 | 版本化查表 + ±50% 敏感性分析，报告排序是否翻转 | 偏好随情境差异大（$247 对 $393）；LLM 先验在不对齐时使 bandit 变差 — [arXiv 2609.31468](https://arxiv.org/abs/2609.31468)；[arXiv 2604.02527](https://arxiv.org/abs/2604.02527) | 初值是设定；类别划分主观 | 中高：承认是设定并展示稳健性，比声称“动态学习”更可信 |
| OPE 演示（可选） | 在合成日志上用 IPW / DR 估计新策略价值 | Open Bandit Pipeline 的合成数据与估计量 | 开源库；模拟器在策略偏移下有偏的理论结果 — [GitHub](https://github.com/st-tech/zr-obp)；[arXiv 2605.11519](https://arxiv.org/abs/2605.11519) | 只验证管线，不验证分数 | 中：作为“有流量后怎么接”的说明可以，作为有效性证据不行 |

### Inferences
- 表里“高”可辩护的组件都是确定性的或有统计修正的；“中/中低”的组件都依赖没有真实标签的模型输出。面试时最稳的叙述顺序是：规则闸门与一致性 → 约束（相关性下限、曝光上限、披露）→ 透明 choice model 给出的相对期望收入 → 模拟器与 judge 作为交叉检验 → 明确说出哪些数字是设定。
- 整个分数应被称为“版本间比较用的诊断指标”，并报告多次试验的区间与权重敏感性；不应称为“预测收入”。

### Gaps
- 表中没有任何一个 P(book) 估计方式在“对话式旅行推荐”场景被真实预订数据验证过；这是整个方案最大的未解问题。
- 各阈值（相关性下限、曝光上限、λ）的取值没有文献可直接引用，只能靠敏感性分析支撑。

---

## 追加问题 8：开放权重的 “Jev-class” 模型盘点（只做推理、不做任何训练），以及相邻的“无生成、无训练的 yes/no 概率”方案

前提（开发者确认）：模型就是 TypeSafe AI 的 Jev；本项目不做任何训练（不预训练、不后训练、不微调），只做推理；硬件为单张 16 GB 显存的 RTX 5070 Ti 加 20 个 CPU 线程；产品对话为中文。本节新增标注：【厂商自报】= 数字来自模型发布方自己的 model card、README 或 blog；【独立】= 数字来自与发布方无关的第三方论文或榜单（仍多为 arXiv 预印本，未经同行评审）。

### Takeaway
开发者的判断成立：Jev 发布后两个多月内出现了大量开放权重的同类模型（一个公开榜单在 10 月中旬已有上百个条目），其中 2B–5B 一档可以在 16 GB 显存上全精度本地运行，许可多为 Apache-2.0。但对“小模型当 judge”的独立证据并不乐观：4B–9B 档在 judge benchmark 上约 66–70%，低于无推理的前沿 LLM judge（约 84%），且对注入指令和选项顺序更脆弱；中文方面只有 Liquid AI 的 d1 系列在 model card 上明确列出中文，没有任何一个模型有中文 judge 场景的独立评测。结论是：本地开放模型在成本和可复现性上最好，但必须用自己标注的中文样本验证后才能把它的概率放进公式。

### Cited Findings

**生态规模与榜单（先说明数字从哪来）**
- “Jev Decision Index” 是 Hugging Face 上由 multimodalart 维护的社区榜单，冻结评测集为 37 个 benchmark、132,422 个请求；0.3.2 版的权重是 20% 公开 benchmark、50% 私有测试、30% 新领域私有任务；10 月中旬有 174 个条目、30 多个开放权重模型。【仅见检索摘要】— [aiweekly](https://aiweekly.co/alerts/jev-decision-index-ranks-30-open-weight-decision-models)；[llmreference](https://www.llmreference.com/benchmark/decision-index)
- 另一个同名不同物的榜单是 Artificial Analysis Decision Index（2026-10-13 上线，四个评测各占 25%）：Jev 1.13 得 58，是 decision model 第一；GLiDE 与 Microsoft-Decision-1 各 54；作为对照的 Claude Haiku 5.5 (Low) 61、GPT-6 Luna (Low) 55；decision model 的中位延迟 0.06–0.5 秒，每百万任务 $17–$199；整体过度自信，主要出在知识类题目上。【独立榜单，页面未说明与厂商的关系】— [Artificial Analysis](https://artificialanalysis.ai/articles/artificial-analysis-decision-index)
- 一篇面向本地部署的盘点文章（2026-10-23）列出 17 个有详细信息的开放权重 decision model，绝大多数是 26B–35B、Apache 2.0、基于 Qwen3.8-27B 或 Gemma 4 31B；并指出榜单延迟是数据中心 GPU 上的全精度测量，“Agreement is not accuracy, so test on your own data”。【二手盘点】— [HackerNoon](https://hackernoon.com/20-best-open-source-ai-decision-models-you-can-run-locally-in-2026)

**一、能在 16 GB 单卡上全精度运行的 Jev-class 模型（按证据充分程度排列）**

| 模型 | 发布方 / 上传日期 | 参数量 | 许可 | 权重 | 16 GB 单卡 | 中文 |
|---|---|---|---|---|---|---|
| d1-2B | Liquid AI / 2026-10-24 | 1.92B | LFM Open License v1.0 | [HF](https://huggingface.co/LiquidAI/d1-2B) | 能（BF16 权重按参数量估算约 4 GB） | card 明确列出 zh |
| d1-3B | Liquid AI / 2026-10-05 | 3.12B | LFM Open License v1.0 | [HF](https://huggingface.co/LiquidAI/d1-3B) | 能（估算约 6 GB） | 语言标签含 zh |
| Kev-4B（另有 0.8B、9B、27B） | Jared Palmer / 2026-09-19 | 4B（LoRA + pointer head） | Apache-2.0 | [HF](https://huggingface.co/api/models/jaredpalmer/kev-4b)；[GGUF](https://huggingface.co/ggml-org/kev-4b-gguf) | 能（GGUF 3.03–8.43 GB）；Kev-9B 约 17 GB，不能全精度 | 标签只有 en |
| decider-2b / decider-4b | Mapika / v12 为 2026-10-20；4b 上传于 2026-09-22 | 约 2B / 4.2B | Apache-2.0 | [HF 2b](https://huggingface.co/Mapika/decider-2b)；[HF 4b](https://huggingface.co/api/models/Mapika/decider-4b) | 能（3.8 GB / 8.4 GB） | 只列 English |
| d3-mini | Semantic Router Labs（vLLM Semantic Router）/ 2026-10-10 | 4.54B | Apache-2.0 | [HF](https://huggingface.co/vllm-sr/d3-mini) | 勉强能（实测峰值 14.8 GiB，测于 AMD MI325X） | 未说明 |
| Intern-Decision-4B（另有 0.8B、2B） | InternLM / 2026-09-26 | 4.54B | Apache-2.0（保留 LICENSE-QWEN） | [HF](https://huggingface.co/internlm/Intern-Decision-4B) | 应能（估算约 9 GB，card 未给显存） | 未说明 |
| Clef-flash | Cloudflare / 2026-09-30 | 9.41B | Apache-2.0 | [HF](https://huggingface.co/cloudflare/clef-flash) | 全精度不能（估算约 19 GB），需社区量化版 | 未说明 |

逐个模型的一手信息：
- **d1-3B 许可冲突已从一手来源解决**：仓库 LICENSE 文件是 LFM Open License v1.0；第 5 条规定商业使用权以“你或你的法律实体未超过门槛”为条件，门槛是“年收入 1,000 万美元或以上”；允许复制、分发和制作衍生作品，但须附带许可证副本；合格非营利组织的非商业或研究用途有豁免。blog 里“without restrictions”的说法与许可证正文不一致，应以许可证正文为准。【官方 LICENSE】— [LICENSE](https://huggingface.co/LiquidAI/d1-3B/blob/main/LICENSE)；[Liquid AI blog](https://liquid.ai/blog/open-d1/)
- **d1-3B**：基于 LFM2.5-VL-3B；输入为 state（文本、JSON、图片或混合）加命名问题（`noul` 返回 P(yes)，`choice` 返回 choice / confidence / probabilities，`score` 支持 2–10 个有序等级）；一次前向、零输出 token；上下文 32,768；`transformers>=5.14` 且 `trust_remote_code=True`，另列出 27 个量化版本；card 注明已有更新的 d1-2B。Decision Index 0.2.1 得 48.57 是 Liquid 自己用官方 scorer 跑的；RTX 4090 上单问 8 ms。【官方 card，数字为厂商自报】— [HF d1-3B](https://huggingface.co/LiquidAI/d1-3B)；上传时间与语言标签（含 zh）见 [HF API](https://huggingface.co/api/models/LiquidAI/d1-3B)
- **d1-2B**：基于 LFM3-VL-2B；16 种语言中包含 Chinese；问题类型比 d1-3B 多（多选 choice、text / number / date 抽取、box）；上下文 128K，card 自述 state 超过约 64K 后可靠性下降；`transformers>=5.19`，也给出 vLLM、SGLang、Docker Model Runner 的用法；公开套件 Decision Index v0.3 上 d1-2B 51.1、d1-3B 49.0（Liquid 自测）；card 称答案“calibrated”，但不给 ECE 或 Brier，并建议在自己的数据上定阈值；自述“对计数和打分的估计可靠，对自由数量不太可靠”。【官方 card，数字为厂商自报】— [HF d1-2B](https://huggingface.co/LiquidAI/d1-2B)；[HF API](https://huggingface.co/api/models/LiquidAI/d1-2B)
- **Kev 系列**：定位是“可以自己训练和运行的小型 Jev-like 模型”，API 与 TypeSafe 的 System One 一致（`/v1/systemone`），TypeSafe Python SDK 可以直接指向本地 Kev 服务；pointer head 加 softmax 出概率，每个 checkpoint 存一个拟合好的 temperature（4B 为 2.41）；PyTorch（CUDA / ROCm / MPS / CPU）与 MLX；已验证上下文 8,192 token；Kev-9B 约需 17 GB 显存。自测：new-source 准确率 Kev-4B 0.817、Kev-9B 0.820、Jev 0.857；Kev-9B 的校准误差经 temperature 从 0.103 降到 0.041；README 自己声明这不是受控对比，并说微调会损害日期算术等基础能力。【官方 README，数字为厂商自报】— [GitHub README](https://raw.githubusercontent.com/jaredpalmer/kev/main/README.md)
- **Kev-4B 的 llama.cpp 路线**：ggml-org 提供官方转换的 GGUF（Q4_K_M 3.03 GB、Q8_0 4.48 GB、BF16 8.43 GB），说明为“a decision model, to be used via `/v1/systemone` API”，安装方式包含 Windows 的 WinGet。【官方 GGUF 仓库】— [ggml-org/kev-4b-gguf](https://huggingface.co/ggml-org/kev-4b-gguf)
- **Mapika decider 系列**：自述是“an open reproduction of the 'System One' model class (TypeSafe AI's Jev)”；`decider` 包自带暴露 `POST /v1/systemone` 的服务。decider-2b v12 自测 Decision Index 0.3（4,500 请求抽样）38.17、抽样 ECE 0.164。重要的默认值陷阱：默认把 yes/no 的 temperature 设为 0.05 以迎合 JevBench 计分规则，这使 yes/no 概率未校准（ECE 0.341，对比拟合值下的 0.095），要校准概率须改用 `temperature_by_type={"choice": 2.465, "noul": 3.185, "score": 2.833}`。【官方 card，数字为厂商自报】— [HF decider-2b](https://huggingface.co/Mapika/decider-2b)；系列与大小见 [HF decider-35b-a3b](https://huggingface.co/Mapika/decider-35b-a3b)
- **d3-mini**：基于 Qwen3.5-4B；输入文本、JSON、图片、视频；Choice / Yes-No（代码里叫 `noul`）/ Score；Transformers 5.17 加 `trust_remote_code`，或 `vllm-sr serve`（仅开发通道）。Jev Decision Index 0.3.2 官方榜单文本总分 52.6（榜单方运行）；MI325X 上文本中位延迟 18.1 ms（团队自测）；批处理改变了 4,000 个请求中 0.136% 的决定，都是近似平局。card 元数据列出 safeagents-judge-bench 上准确率 0.74、Brier 0.12，但没说是谁跑的。【官方 card；榜单分为榜单方运行，其余为厂商自报】— [HF d3-mini](https://huggingface.co/vllm-sr/d3-mini)
- **Intern-Decision-4B**：基于 Qwen3.5-4B；文本加至多 8 张图；`choice` / `score` / `noul`；只实现了 Hugging Face 后端；输入上限 8,192 token，超长直接拒绝；RTX 4090 上平均 44.16 ms；默认 temperature 1.992 由 1,728 个校准样本拟合。自测七套评测平均 90.02（Jev v1.13.0 为 88.74）、ECE 0.065。【官方 card 与论文，数字为厂商自报】— [HF Intern-Decision-4B](https://huggingface.co/internlm/Intern-Decision-4B)；[arXiv 2610.22131](https://arxiv.org/abs/2610.22131)
- **Clef / Clef-flash**：Cloudflare 2026-10-01 发布，Clef 为 Qwen3.8-27B 加 rank-256 LoRA，Clef-flash 基于 Qwen3.5-9B；权重 Apache 2.0，API 与 Jev 兼容；训练数据是内部合成数据，未公开；用 Brier loss 改善校准但没有报告校准指标；benchmark 由 Cloudflare 自己运行。【官方 blog 与 card，数字为厂商自报】— [Cloudflare blog](https://blog.cloudflare.com/clef-decision-models/)；[HF clef-flash](https://huggingface.co/cloudflare/clef-flash)

**二、16 GB 上跑不了全精度、但常被引用的开放权重模型**
- Perplexity pplx-decider v1.1 27B：Apache-2.0，基于 Qwen3.8-27B，权重约需 49 GiB；card 自报 Decision Index 61.56（Jev 57.9）；`predict` 会套用保存的 calibration temperature；card 摘要显示仓库需要登录授权访问。Q4_K_S 量化版 15.28 GB、实际需要 16.6 GiB，与原模型在 96.8% 的决定上一致（量化方 TurinTech 测，二手转述）。【官方 card；量化数字为二手】— [HF pplx-decider-v1.1-27b](https://huggingface.co/perplexity-ai/pplx-decider-v1.1-27b)；[HackerNoon](https://hackernoon.com/20-best-open-source-ai-decision-models-you-can-run-locally-in-2026)
- 其余 26B–35B 档（vLLM-SR d3、Mapika Decider 31B、Sieve、Kev-27B、Eikos-27B、Shisa DE-2 等）：榜单总分约 57–66、ECE 0.022–0.207；Shisa DE-2 的原始 ECE 0.207 用其 SDK 的 temperature 后降到 0.021。d3（27B）的 Q3_K_S 量化版峰值 14.1 GiB，可进 16 GB 卡，但量化到 3 bit 的精度损失没有公开数字。【二手盘点】— [HackerNoon](https://hackernoon.com/20-best-open-source-ai-decision-models-you-can-run-locally-in-2026)
- SII-Decision-4B / 27B：论文称权重已在 Hugging Face 以全秩和 LoRA 两种形式发布，基于 Qwen3.5-4B / Qwen3.8-27B；我没有找到其 model card，许可未知。【arXiv 未核实】— [arXiv 2610.03935](https://arxiv.org/html/2610.03935)
- 小型 encoder 路线（Laya：421M 的 ModernBERT-large 英文版与 322M 的 mmBERT-base 多语版）：独立评测中表现很差，见下。【独立】— [arXiv 2610.00346](https://arxiv.org/html/2610.00346)

**三、独立评测（非厂商）**
- 通用决策任务（arXiv 2610.00346，开放模型在 Colab L4 上本地运行）：workflow 准确率 Jev 0.732、Kev-9B 0.712、Nimble-9B 0.685、this-that-model-1.0 0.597、decider-2b 0.588、Kev-0.8B 0.451、Laya 0.366 / 0.349；CLINC-150 意图准确率 Jev 0.913，四个 2B–9B 开放模型 0.850–0.863。yes/no 对调后的翻转：Jev 每 100 个 50.5 个，Kev-9B、decider-2b、this-that-model-1.0、Nimble-9B 为 4.2–6.5 个，Kev-0.8B 14.3 个，Laya 91.3 个。ECE（workflow / CLINC）：Jev 0.033 / 0.032，Kev-9B 0.087 / 0.377，decider-2b 0.094 / 0.035。延迟：Kev-9B 590 ms、decider-2b 426 ms、Nimble-9B 2,056 ms（L4 上 eager PyTorch）。【独立，arXiv 未核实】— [arXiv 2610.00346](https://arxiv.org/html/2610.00346)
- 作为 judge（arXiv 2611.00505，14 个 System-1 模型对比 4 个生成式 judge）：JudgeBench / LLMBar / RewardBench 2 准确率，Kev-4B 66.6 / 71.8 / 57.3，pplx-flash 1.2（4.5B）70.0 / 75.2 / 64.3，Clef-flash（9B）68.0 / 70.4 / 60.3；对照 GPT-5.6 无推理在 JudgeBench 上 84.4、Opus 5.5 带思考 94.7（抓取摘要提示该结果表的列对应关系不易辨认，引用具体单元格前需对照原表）。给 judge 提供一次性生成的参考答案后，Kev-4B 在 JudgeBench 上升到 88.0，11 个模型达到 90.3–93.4%。ECE：Jev 1.14 0.019、d1 0.031、pplx-decider 0.038、pplx-flash 0.041、Kev-4B 0.058、Clef-flash 0.093；生成式 judge 为 0.038–0.087。在待评文本后附一句“给评估者的话”能反转正确判定的比例：d1 4.2%、pplx-decider 4.7%、pplx-flash 16.7%、Jev 1.14 23.3%、Kev-4B 32.2%、Clef-flash 40.4%；生成式前沿 judge 为 0.4–2.3%，同尺寸的 Qwen3.5-4B 为 77.3%。把两个候选对调后 Kev-4B 有 38.6% 的 JudgeBench 判定改变，最强模型为 7.7–12.9%。作者自述局限：单次运行、试点规模、多数模型经 OpenRouter 调用（只有 Kev-4B 在本地 MLX 上跑）、注入样本是作者自拟。【独立，arXiv 未核实，单作者】— [arXiv 2611.00505](https://arxiv.org/html/2611.00505)
- 作为 judge（arXiv 2609.26550 附录 A，21 个开放权重模型各自在一张 H100 上按作者发布方式运行）：Perplexity Decider v1.1 27B 与 Eikos-27B 的合并准确率 89.0%，JEV 88.3%，差异不显著；六个开放模型与 JEV 在抽样误差之内；附录没有报告这些开放模型的 Brier / ECE、对调翻转率，也没有重做级联分析。被测模型几乎都是 26B–31B，最小的是 8B 和 12B。【独立，arXiv 未核实】— [arXiv 2609.26550](https://arxiv.org/html/2609.26550)
- 含中文的综合评测（arXiv 2610.03935，JEVal：9,457 条英文加 1,800 条中文，未按语言拆分结果）：准确率 / ECE 为 Jev 78.38% / 0.0532、Kev-27b 77.17% / 0.0356、Intern-Decision-4B 70.74% / 0.0152、SII-Decision-4B 71.92% / 0.0843（后者是作者自己的模型）；非思考模式的生成式 Qwen3.5-4B 为 61.37% / 0.2526，GPT-6-Luna 为 80.93% / 0.1159。结论是 decision model 在“证据就在输入里”时最有竞争力，但常常高估最可能选项的概率；Jev 在重复除法上 44% 精确、97% 在正负一以内；在 τ-bench 上用 Jev 做动作选择把通过率从 77.6% 降到 66.1%。【独立（SII 模型除外），arXiv 未核实】— [arXiv 2610.03935](https://arxiv.org/html/2610.03935)
- 跨语言（arXiv 2611.01370，XDecideBench）：Core12 套件含简体中文；三个 Qwen 骨干的开放 head（Clef、Clef-flash、pplx-decider）在全部 12 种语言上都优于各自的骨干；但在英文上按 5% 错误率拟合的 confidence 阈值迁移到其他语言后失效，XNLI 上德语和法语的风险升到 7.8–12.4%，conformal 覆盖率从英文的 0.90–0.92 降到高网络占比语言的 0.80–0.83；作者建议在目标语言数据上拟合阈值。正文没有给出中文单独的数字。【独立，arXiv 未核实】— [arXiv 2611.01370](https://arxiv.org/html/2611.01370)
- 评 agent 运行记录的直接证据很少：一篇预印本用自建的 LoRA 加 pointer head 模型给约 148K 条 agentic coding 会话做三个类型化问题的分拣，1,000 条会话约 3 分钟、约 $0.06；它没有报告自己模型与人工标签的一致度，只报告原先那个前沿 LLM judge 的存量标签与两位新 judge 共识的一致率仅 26.9%。【arXiv 未核实】— [arXiv 2610.29052](https://arxiv.org/abs/2610.29052)

**四、相邻方案：不训练、不生成，也能拿到 yes/no 概率，但不属于 Jev-class**
- 读开放 LLM 的选项 token 概率（training-free readout）。AnyJev（Nokia Applied Research，Apache-2.0）的 `Decider` 路径“no training and no labels”：对 state 加类型化问题做一次 prefill，把下一个 token 的分布限制在选项 token 上读出概率；L0 级别对选项顺序做循环轮换并除掉用无标签输入估计的 label prior；后端为 Transformers 和 vLLM；问题类型 `choice` / `yes_no` / `score`。README 自报：Qwen3-8B 在 20 选 1 任务上，从原始 logits 到 L0，答案翻转率 0.230 → 0.073、准确率 0.747 → 0.803、ECE 0.240 → 0.184；不改权重的 Gemma-4-31B 用 L0 在 Decision Index 上得 60.22。同一仓库的 Tacit 系列是经自蒸馏训练的 checkpoint，属于“用别人训练好的权重”。【官方 README 与技术报告，数字为厂商自报】— [GitHub AnyJev](https://github.com/MorrisZJ/AnyJev)；[arXiv 2610.00831](https://arxiv.org/abs/2610.00831)
- 旁证：一篇预印本的标题与摘要主张“LLM 本来就是 Jev 式的 decision model”，冻结的通用 LLM 在同一 4B 骨干上达到或超过已有的免训练读出方法；JEVal 论文第 6 节称未训练的 Qwen3.8-27B 首 token 读出“within a few points of Jev”。【arXiv 未核实】— [arXiv 2610.02076](https://arxiv.org/abs/2610.02076)；[arXiv 2610.03935](https://arxiv.org/html/2610.03935)
- 可用的中文骨干：Qwen3.5-4B 为 Apache-2.0，自述支持 201 种语言和方言，C-Eval 85.1，非思考模式用 `enable_thinking: False` 打开。【官方 card】— [HF Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)
- 本地运行时对 logprobs 的支持：Ollama 的 chat / generate 接口接受 `logprobs` 布尔值和 `top_logprobs`（0–20）。【仅见检索摘要】— [Ollama API 文档](https://docs.ollama.com/openapi.yaml)
- token 概率的校准对读法很敏感：同一答案，只改变读取 token 概率时的上下文和指令，verbalized 与 token 两种 confidence 的 ECE 差距就会移动约等于差距本身的幅度，20 个设定中有 8 个“谁更准”发生翻转。【arXiv 未核实】— [arXiv 2605.27752](https://arxiv.org/abs/2605.27752)
- 闭源 API 的限制：检索摘要称截至 2026 年 3 月 Anthropic Claude 各版本都不提供 logprobs。【仅见检索摘要】— [arXiv 2605.11334](https://arxiv.org/html/2605.11334)
- Cross-encoder reranker。Qwen3-Reranker-0.6B（另有 4B、8B，Apache-2.0，100+ 语言，中文检索基准 CMTEB-R 71.31）：取最后位置上 “yes” 与 “no” 两个 token 的 logit 做 log-softmax，输出 P(yes)，可以传自定义 instruction。BAAI/bge-reranker-v2-m3（Apache-2.0，0.6B，multilingual）：输出原始 logit，用 sigmoid 映射到 0–1。两者的 card 都没有对分数的校准含义做任何说明。【官方 card】— [HF Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)；[HF bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- NLI 零样本分类。MoritzLaurer/bge-m3-zeroshot-v2.0（MIT，0.6B，multilingual，最长 8,192 token）：把分类当作判断假设句对文本是 entailment 还是 not_entailment；card 自己提醒“multilingual models perform worse than English-only models”。【官方 card】— [HF bge-m3-zeroshot-v2.0](https://huggingface.co/MoritzLaurer/bge-m3-zeroshot-v2.0)
- Guard / classifier 模型。Granite Guardian 4.1 8B（Apache 2.0，2026 年 4 月）：支持 “Bring Your Own Criteria”，把自然语言规则放进 `### Criteria:`，但它是生成式的（先写可选的 think，再在 `<score>` 标签里输出 yes 或 no），只在英文数据上训练和测试，card 说自定义规则“require testing”。早期 3.0 版的 card 用 Yes / No token 的 logit 算概率。【官方 card；3.0 的做法仅见检索摘要】— [HF granite-guardian-4.1-8b](https://huggingface.co/ibm-granite/granite-guardian-4.1-8b)；[NVIDIA model card](https://build.nvidia.com/ibm/granite-guardian-3_0-8b/modelcard)

**相邻方案与 Jev-class 的区别（直说）**
- Jev-class 模型是发布方专门为“state 加多个类型化问题”训练过的：一次请求可以并行问多个问题，三种类型共用一个 schema，输出是按问题归一化的概率并带一个出厂拟合的 temperature，多数还兼容 `/v1/systemone`。— [GitHub Kev README](https://raw.githubusercontent.com/jaredpalmer/kev/main/README.md)；[HF Intern-Decision-4B](https://huggingface.co/internlm/Intern-Decision-4B)
- logprobs 读法用的是没有为此训练过的通用 LLM：概率来自“下一个 token 是哪个选项标签”的 softmax，受提示写法、选项顺序、标签先验影响，需要自己做去偏和校准。— [GitHub AnyJev](https://github.com/MorrisZJ/AnyJev)；[arXiv 2605.27752](https://arxiv.org/abs/2605.27752)
- reranker 的分数是“文档与查询的相关性”，NLI 的分数是“文本是否蕴含假设”，guard 模型判的是安全类条件；它们都不是为任意 rubric 条目训练的，也没有 choice / score 类型。— [HF Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)；[HF bge-m3-zeroshot-v2.0](https://huggingface.co/MoritzLaurer/bge-m3-zeroshot-v2.0)；[HF granite-guardian-4.1-8b](https://huggingface.co/ibm-granite/granite-guardian-4.1-8b)

**五、用于本项目软性条目打分的四方案对比**（条目举例：“回复是否披露了某酒店是合作推广”“行程是否符合用户说的节奏偏好”；输出概率进入公式）

| 维度 | Jev API | 本地开放权重 Jev-class（2B–5B） | 本地开放 LLM 读 logprobs | 普通 LLM rubric judge（生成式） |
|---|---|---|---|---|
| 成本 | $0.042 / 百万输入 token，输出免费 — [Models](https://docs.typesafe.ai/models) | 无调用费，只占本机显卡 | 同左；L0 去偏需要按选项数多次前向 — [arXiv 2610.00831](https://arxiv.org/abs/2610.00831) | 最高：flash 档 LLM judge 的费用是 decision model 的 16–357 倍 — [arXiv 2609.29769](https://arxiv.org/abs/2609.29769) |
| 延迟 | 厂商称 70–500 ms；独立测中位 138 ms — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)；[arXiv 2610.00346](https://arxiv.org/html/2610.00346) | 厂商在 RTX 4090 上报 8–44 ms；独立在 Colab L4 上测到 71–590 ms（Nimble-9B 为 2,056 ms）；RTX 5070 Ti 上无数据 — [HF d1-3B](https://huggingface.co/LiquidAI/d1-3B)；[HF Intern-Decision-4B](https://huggingface.co/internlm/Intern-Decision-4B)；[arXiv 2610.00346](https://arxiv.org/html/2610.00346) | 一次 prefill，量级与同尺寸 Jev-class 相近（推断，无实测） | 最慢：是 decision model 的 5–350 倍 — [arXiv 2609.29769](https://arxiv.org/abs/2609.29769) |
| 可复现性 | 可固定版本号；96 次重复请求无一改变决定，但 48 条改写的 rubric 中 4 条改变了决定；服务端版本由厂商控制 — [arXiv 2609.26550](https://arxiv.org/html/2609.26550) | 最好：固定权重 revision 的确定性前向；批处理只改变 0.136% 的近平局决定 — [HF d3-mini](https://huggingface.co/vllm-sr/d3-mini) | 好：本地、固定权重、无采样 | 最差：LangChain 小测试里三个 LLM judge 的逐 case 方差是 Jev 的 92–913 倍 — [LangChain blog](https://langchain.com/blog/jev-agent-evals-langsmith) |
| 校准 | 独立测 ECE 0.019–0.053；知识类题目过度自信；yes/no 对调翻转在一项研究中高达 50.5/100 — [arXiv 2611.00505](https://arxiv.org/html/2611.00505)；[arXiv 2610.03935](https://arxiv.org/html/2610.03935)；[arXiv 2610.00346](https://arxiv.org/html/2610.00346) | 出厂带 temperature；独立测 ECE 0.015–0.38，随任务差异很大；英文阈值不能迁移到其他语言 — [arXiv 2610.00346](https://arxiv.org/html/2610.00346)；[arXiv 2611.01370](https://arxiv.org/html/2611.01370) | 原始读数差（厂商自报 ECE 0.24，L0 后 0.18），且对读法敏感 — [GitHub AnyJev](https://github.com/MorrisZJ/AnyJev)；[arXiv 2605.27752](https://arxiv.org/abs/2605.27752) | 不直接给概率；通过率需用人工标签做 sensitivity / specificity 修正 — [ICML 2026](https://icml.cc/virtual/2026/poster/63607) |
| judge 能力 | 结论可从文本读出时接近无推理的前沿 LLM；需要推导时落后 — [arXiv 2609.26550](https://arxiv.org/abs/2609.26550) | 4B–9B 在 JudgeBench 上 66–70%，给参考答案后可到约 88% — [arXiv 2611.00505](https://arxiv.org/html/2611.00505) | 取决于骨干；同尺寸生成式 Qwen3.5-4B 在 JEVal 上 61.37% — [arXiv 2610.03935](https://arxiv.org/html/2610.03935) | 最强：带思考的前沿模型在 JudgeBench 上 94.7% — [arXiv 2611.00505](https://arxiv.org/html/2611.00505) |
| 中文 | 没有找到中文专项评测 | 只有 d1 系列的 card 列出中文；其余未说明或只标英文 — [HF d1-2B](https://huggingface.co/LiquidAI/d1-2B) | 可选中文能力强的骨干（Qwen3.5） — [HF Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | 前沿模型的中文理解最可靠（常识性判断，无专项引用） |
| 可辩护性 | 中：闭源、合成数据训练、证据多为预印本，数据要出本机 | 中到中高：可复现、可离线、许可清楚；弱点是小模型 judge 能力和中文证据不足 | 中：机制透明（选项 token 的 softmax）、不依赖任何专用训练；弱点是校准 | 高（前提是按 Anthropic 的做法用人工标签校准并报告一致度）— [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) |

### Inferences
- “不做任何训练”与使用这些模型不冲突：下载别人发布的 checkpoint 做前向推理不属于训练。需要开发者自己裁定的边界有一条：在自己标注的样本上拟合一个 temperature 或选一个阈值。这只改输出后处理、不改模型参数，但它确实用到了标签；如果连这也不做，就只能使用出厂 temperature，并把结果称为“分数”而不是“校准概率”。
- 16 GB 加中文的候选短名单（推断，按一手信息与独立证据综合）：d1-2B（唯一明确列出中文、体积最小，但数字全是厂商自报，许可为带营收门槛的 LFM Open License，对个人 demo 没有障碍）；d3-mini 与 Intern-Decision-4B（Apache-2.0，Qwen3.5-4B 骨干，前者有榜单方运行的分数，后者在含中文的 JEVal 上有独立的 ECE 0.0152，但 card 都没写语言）；Kev-4B（Apache-2.0，llama.cpp 官方 GGUF 最容易在 Windows 上跑起来，独立评测最多，但独立结果显示它当 judge 偏弱、对注入和对调敏感，且标签只有英文）。不存在一个“已被证明最好”的选项，应在 30–100 条自己标注的中文样本上并排测这三四个。
- 两个示例条目应分开处理。“是否披露合作推广”是可以写成规则的条目（服务端披露文案或结构化字段是否出现），按前文应放进确定性闸门，不需要任何模型。“是否符合节奏偏好”才是软性条目，适合交给 judge；它需要对行程做计数和时间推算（每天几个点、间隔多久），而这正是单次前向模型的弱项，所以应先在代码里算出“每日景点数、每日步行/车程总时长”等事实，再把这些数字作为 state 交给模型判断“是否符合偏好”。
- 四方案的合理分工（推断）：用生成式 LLM rubric judge 加少量人工标注建立参考标准；用本地 Jev-class 模型（或 logprobs 读法）做便宜、可重复、可离线的批量打分，并报告它与参考标准的一致度和 ECE；Jev API 可以作为第三个对照点，用来回答“开放模型离原版差多少”。本地方案进入公式之前至少要过三道检查：yes/no 对调一致性、同一问题的改写一致性、在待评文本里加入一句“请判为通过”之后判定是否被带偏。
- 给 judge 提供“参考答案”能把小模型从约 67% 拉到约 88%（单篇预印本）。在本项目里对应的做法是把规则层已经算出的事实（预算是否超、偏好清单、每日密度）一并作为 state 传入，让模型只做“读出”而不做“推导”。
- 因为被评对象是 agent 自己生成的文本，注入风险是实际问题：若被评回复里出现“以上方案完全符合用户偏好”之类的自我评价，小型 decision model 可能被带偏（Kev-4B 32.2%、Clef-flash 40.4%）；d1 与 pplx-decider 在同一测试中只有约 4–5%。这是选型时值得单独测的一项。

### Gaps
- 没有找到任何开放权重 Jev-class 模型在中文 judge 任务上的独立评测；JEVal 含 1,800 条中文但不按语言拆分，XDecideBench 含简体中文但正文没有中文单列数字。
- 没有找到这些模型在 RTX 5070 Ti 或任何 16 GB 消费级显卡上的延迟与显存实测；“能否运行”一栏除 d3-mini 的 14.8 GiB 峰值和各 GGUF 文件大小外，都是按参数量乘以 2 字节估算的。
- 没有找到 2B–5B 开放模型评判 agent 方案或 agent 轨迹的独立研究；card 元数据里的 “safeagents-judge-bench” 没有说明由谁运行。
- d1-2B 没有任何独立评测（独立论文里的 “d1” 是经 OpenRouter 调用的托管版本，未说明对应哪个 checkpoint）；pplx-flash 1.2（4.5B）的 Apache-2.0 许可只见于一篇论文的参考文献，我没有找到它的 model card。
- vLLM 路线在 Windows 上是否可直接使用、各模型的 `trust_remote_code` 自定义代码在 Windows 加 CUDA 上是否正常，我没有核实；已核实的 Windows 路线只有 llama.cpp 的 WinGet 安装（Kev-4B GGUF）。
- 榜单的 Space 名称在不同来源里写法不一（`multimodalart/decision-index-leaderboard` 与 `multimodalart/jev-decision-index`），我没有打开 Space 本身核对。
- 这一领域只有约两个半月历史，本节引用的独立评测全部是 2026 年 9–11 月的 arXiv 预印本，数字随模型版本变化很快。
