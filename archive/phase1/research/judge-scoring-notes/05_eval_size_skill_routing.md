# 05 评测集规模与 Skill 路由（hit rate）测量 —— 研究笔记

> 检索日期：2026-11-26。全文约定的来源分级标签：
> - **【2026 顶会·已核实】**：在会议官网 / proceedings / OpenReview 页面核实过接收（每条写明核实方式）。
> - **【2026 顶会·自述未独立核实】**：仅 arXiv comments 字段自述接收，未在会议页面查到。
> - **【2026 workshop】**：只是 workshop 论文，不算主会。
> - **【背景·≤2025】**：2025 年及更早的论文，只作背景。
> - **【arXiv 预印本·未核实 venue】**：只有 arXiv，未查到接收信息。
> - **【Anthropic 官方】**：工程博客 / 产品文档（厂商自述，非同行评审）。
> - **【行业博客】/【社区博客】**：公司技术博客 / 个人博客测量，样本小，仅作旁证。
> - **【统计参考】**：统计学公式出处，年份不限。
>
> 本笔记中凡是“表格里的数字”，除特别注明“原文数字”外，都是按所引公式自行计算的结果（脚本附在第 1 节 Inferences 末尾，可复算）。任务背景（30 个 case × 3 次 = 90 trials、6 个 skill、约 13% system prompt 迁入 skill）是任务给定信息，本笔记未去读项目代码核实。
> 为避免大段照抄原文，下文用中文转述，全篇只保留一处英文短引用（第 3 节）。

## 1. Eval 规模的统计学：置信区间、clustered SE、配对比较、pass^k

### Takeaway
30 个 case 的问题不在“数字不好看”，而在于：通过率 0.8–0.9 时 95% CI 半宽是 ±11–14 个点，配对比较对 20 个点以内的差异达不到 80% power；重复 3 次只能把“有效样本量”从 30 提到约 37–56（取决于 case 内相关性），不能当 90 个独立样本用。按公式反推，**检出 10 个点差异（80% power、配对）需要约 116–155 个 case，检出 5 个点需要约 470–630 个**——前者正好落在 100–200，后者只有便宜的单步 case 才负担得起，这就是分层的统计依据。

### Cited Findings

**公式出处（可复算）**
- 把 eval 题目看作从“题目总体”抽样，报告均值的同时报告 SEM；通用式 `SE_CLT = sqrt(Var(s)/n)`，0/1 得分时 `SE_Bernoulli = sqrt(s̄(1−s̄)/n)`，95% CI = 均值 ± 1.96·SE。【统计参考 / 背景·≤2025，Miller 2024】— [Adding Error Bars to Evals, arXiv 2411.00640](https://arxiv.org/html/2411.00640)
- 题目成组相关（同一篇文章的多道题、同一模板的多个变体）时要用 clustered SE：`SE_clustered = ( SE_CLT² + (1/n²)·Σ_c Σ_i Σ_{j≠i} (s_{i,c}−s̄)(s_{j,c}−s̄) )^{1/2}`。— [arXiv 2411.00640](https://arxiv.org/html/2411.00640)
- Anthropic 对该论文的官方解读称：常见 eval 上 clustered SE 可以是朴素 SE 的三倍以上。【Anthropic 官方，2024-11-19】— [A statistical approach to model evaluations](https://www.anthropic.com/research/statistical-approach-to-model-evals)
- 每题重复 K 次时的方差分解：`Var(μ̂) = ( Var(x) + E[σ_i²]/K ) / n`，其中 `x_i` 是第 i 题的“真实通过概率”，`σ_i²` 是该题单次作答的方差。重复只能压缩第二项（题内随机性），压不掉第一项（题间差异）。— [arXiv 2411.00640](https://arxiv.org/html/2411.00640)
- 两个系统比较时要用逐题配对差：`SE_{A−B,paired} = sqrt( Var(s_A − s_B)/n ) = sqrt( SE_A² + SE_B² − 2·SE_A·SE_B·Corr(s_A,s_B) )`；相关越高，配对比非配对省得越多。— [arXiv 2411.00640](https://arxiv.org/html/2411.00640)
- Anthropic 解读中报告：前沿模型之间在常见 eval 上的逐题得分相关大约在 0.3–0.7。— [A statistical approach to model evaluations](https://www.anthropic.com/research/statistical-approach-to-model-evals)
- Power analysis（配对、每题重复 K 次）：`n = (z_{α/2}+z_β)² · ( ω² + σ_A²/K_A + σ_B²/K_B ) / δ²`，其中 `ω² = Var(x_A)+Var(x_B)−2Cov(x_A,x_B)`（逐题真实差的方差），`σ_A² = E[σ_{A,i}²]`。论文自带算例：`ω²=1/9, σ²=0, δ=0.03, α=0.05, power=0.8` 得 n≈969；`n=198, σ_A²=σ_B²=1/6, ω²=1/9` 时把 K 从 1 提到 10，最小可检测差从 13.2% 降到 7.5%。（本笔记脚本复算得 968.997、13.27%、7.57%，吻合。）— [arXiv 2411.00640](https://arxiv.org/html/2411.00640)
- McNemar 检验的样本量（Connor 1987 正态近似，SAS PROC POWER 文档给出的形式）：记 `P_D = p10 + p01`（两版本结果不一致的 case 占比），`d = p01 − p10`（净差），单侧 `N = ( z_{1−α}·sqrt(P_D) + z_{power}·sqrt(P_D − d²) )² / d²`；双侧把 `z_{1−α}` 换成 `z_{1−α/2}`（SAS 文档说明双侧 N 是对 power 公式数值求逆得到的，另一尾的贡献可忽略）。【统计参考】— [SAS/STAT POWER Procedure: McNemar test, Connor method](https://support.sas.com/documentation/cdl/en/statug/66103/HTML/default/statug_power_details55.htm)
- 网上教程的算例不一定可靠：一份 McNemar 样本量教程给出的公式是 `n ≈ (z_{1−α/2}+z_{1−β})² / [ p_disc · ((p10−p01)/(p10+p01))² ]`，代入其例子（p10=0.15, p01=0.05）应得约 157，但页面写的是 79，与自身公式不符——所以表中数字一律按 SAS/Connor 公式自己算。【统计参考，有瑕疵】— [Power for McNemar's Test tutorial](https://cttir.github.io/tutorials/tutorials/sample-size/power-mcnemar.html)
- Wald 区间 `p̂ ± z·sqrt(p̂(1−p̂)/n)` 在 n 小或 p 接近 0/1 时不可靠，应改用 Wilson score 区间：中心 `(p̂ + z²/2n)/(1+z²/n)`，半宽 `z·sqrt(p̂(1−p̂)/n + z²/4n²)/(1+z²/n)`；0 次失败时可用 rule of three，95% 上界约 3/n。【统计参考】— [Binomial proportion confidence interval (Wikipedia)](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval)

**pass^k**
- τ-bench 的定义：pass^k 是“同一任务独立跑 k 次全部成功”的概率在任务上的平均；每个任务跑 n 次、成功 c 次时无偏估计为 `pass^k = E_task[ C(c,k)/C(n,k) ]`，pass^1 就是平均成功率。主结果每任务至少 3 次 trial；gpt-4o function calling 的 pass^1 为 retail 61.2、airline 35.2，retail 上 pass^8 低于 25%。【背景·≤2025，arXiv 2024-06，arXiv 页面未列 venue】— [τ-bench, arXiv 2406.12045](https://arxiv.org/html/2406.12045)
- Anthropic 的 agent eval 指南区分 pass@k（k 次里至少成功一次）与 pass^k（k 次全部成功），并举例：单次成功率 75%、跑 3 次，全部通过的概率约 42%。【Anthropic 官方，2026-01-09】— [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- pass^k 已是 2026 顶会 benchmark 的常规报告项：MCPMark（127 个任务）最好模型 pass@1 52.56%、pass^4 33.86%。【2026 顶会·已核实：ICLR 2026 proceedings 页面】— [MCPMark, ICLR 2026 proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8138d211ce8790fdfbeeeb9781838a37-Abstract-Conference.html)
- DynamicMCPBench 把“3 次独立尝试全部成功”（pass^3）作为任务解出的判据（750 个任务、24 个模型）。【2026 顶会·自述未独立核实：arXiv comments 写 Accepted to EMNLP 2026，未在 ACL Anthology 查到】— [DynamicMCPBench, arXiv 2607.20531](https://arxiv.org/abs/2607.20531)

**2026 年关于 agent eval 方差 / 样本量的文献**
- Anthropic 指南：很多团队以为需要几百个任务，但早期从真实失败里取 20–50 个简单任务就是好的起点，理由是早期每次改动效果大（effect size 大）、小样本就够；成熟的 agent 需要更大更难的 eval 才能检出更小的差异。同文建议每个 task 跑多次 trial，因为同一 task 这次过下次可能不过。【Anthropic 官方，2026-01-09】— [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- Anthropic 的 commerce agent 架构文（本项目首要方法参考）给的起点是**每个 user flow 50–100 个 eval case**，取自真实失败和生产对话；每个正例配一个反例；通过率要在少数几次 trial 上做门禁。【Anthropic 官方，2026-09-02；由抓取摘要转述】— [The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- Towards a Science of AI Agent Reliability：把 agent 可靠性拆成 consistency / robustness / predictability / safety 四个维度共 12 个指标，评了 15 个模型，结论是能力提升只带来很小的可靠性改善（单一成功率掩盖了跨次运行不一致、对扰动敏感等问题）。【2026 顶会·已核实：ICML 2026，PMLR 306，icml.cc poster 页面】— [PMLR v306 rabanser26a](https://proceedings.mlr.press/v306/rabanser26a.html)；[icml.cc poster 66364](https://icml.cc/virtual/2026/poster/66364)
- Holistic Agent Leaderboard (HAL)：21,730 次 agent rollout、9 个模型 × 9 个 benchmark、总成本约 4 万美元；用 LLM 辅助查日志发现了 agent 去 HuggingFace 搜 benchmark 答案等“走捷径”行为。【2026 顶会·已核实：ICLR 2026 proceedings 页面】— [HAL, ICLR 2026 proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/a0928f924a344aaebbb7f6cd8d56e34c-Abstract-Conference.html)
- On Randomness in Agentic Evals：在 SWE-Bench-Verified 上跑了 6 万条轨迹，单次 pass@1 随选哪一次运行而波动 2.2–6.0 个点，temperature 0 时标准差仍超过 1.5 个点，因此 2–3 个点的“提升”可能只是噪声。【2026 workshop：ICLR 2026 “Agents in the Wild” workshop poster，不是主会】— [iclr.cc/virtual/2026/10016323](https://iclr.cc/virtual/2026/10016323)
- How Many Tasks Are Enough for Agent Benchmark Decisions?：回放 SWE-bench / AppWorld / τ-bench 的公开逐题记录，问“跑多少比例的任务就能得到和全量一致的两两结论”；在其设定下 AppWorld 15%、τ-bench 25%、SWE-bench Verified 90% 才满足全部条件——所需比例随 benchmark 差异极大，不存在通用比例。【2026 workshop：KDD 2026 Workshop】— [arXiv 2607.12338](https://arxiv.org/abs/2607.12338)
- Agent Evaluation Reliability: More Tasks Won't (Always) Fix An Agent Leaderboard：对 22 个 benchmark 做贝叶斯方差分解；固定“模型+scaffold”的系统排名可靠度 0.935–0.994，但“底层模型”排名可靠度只有 0.148–0.841；当 scaffold 覆盖是瓶颈时，再加无穷多同类任务最多只提高 0.097。【arXiv 预印本·未核实 venue，2026-09-30】— [arXiv 2610.00651](https://arxiv.org/abs/2610.00651)
- Efficient Benchmarking of AI Agents：8 个 benchmark、33 个 scaffold、70+ 模型配置；只在历史通过率 30%–70% 的任务上评新 agent，可少跑 44%–70% 的任务而排名基本不变（绝对分数预测则会漂）。【arXiv 预印本·未核实 venue，2026-03-24】— [arXiv 2603.23749](https://arxiv.org/abs/2603.23749)

### Inferences

以下表格均为本笔记按上面公式计算（α=0.05 双侧，z=1.960；power=0.8，z=0.8416；(1.960+0.8416)²=7.849）。

**表 1-A：N 个独立 case、单次运行时，通过率的 95% CI 半宽（Wald，百分点）与 Wilson 区间**

| N | p=0.80 | p=0.90 | p=0.95 |
|---|---|---|---|
| 30 | ±14.3（Wilson 62.7–90.5） | ±10.7（74.4–96.5） | ±7.8（80.9–98.8） |
| 50 | ±11.1（67.0–88.8） | ±8.3（78.6–95.7） | ±6.0（85.1–98.4） |
| 60 | ±10.1（68.2–88.2） | ±7.6（79.9–95.3） | ±5.5（86.3–98.3） |
| 100 | ±7.8（71.1–86.7） | ±5.9（82.6–94.5） | ±4.3（88.8–97.8） |
| 120 | ±7.2（72.0–86.2） | ±5.4（83.3–94.2） | ±3.9（89.5–97.7） |
| 150 | ±6.4（72.9–85.6） | ±4.8（84.2–93.8） | ±3.5（90.3–97.5） |
| 200 | ±5.5（73.9–85.0） | ±4.2（85.1–93.4） | ±3.0（91.0–97.3） |
| 300 | ±4.5（75.1–84.1） | ±3.4（86.1–92.9） | ±2.5（91.9–96.9） |
| 500 | ±3.5（76.3–83.3） | ±2.6（87.1–92.3） | ±1.9（92.7–96.6） |
| 1000 | ±2.5 | ±1.9 | ±1.4 |

反过来，达到指定半宽所需 N（`N = 1.96²·p(1−p)/h²`）：±10 点 → 62 / 35 / 19（p=0.8/0.9/0.95）；±7.5 点 → 110 / 62 / 33；±5 点 → 246 / 139 / 73；±3 点 → 683 / 385 / 203。

**表 1-B：N 个 case 各跑 K 次时的 CI 半宽（百分点）。** 由 Miller 的分解 `Var(μ̂) = (Var(x) + E[σ_i²]/K)/n` 推导：令 `ρ = Var(x)/(p(1−p))`（case 间方差占比，即 ICC），则 `Var(μ̂) = p(1−p)·(ρ + (1−ρ)/K)/N`，等价于“N·K 个 trial 的有效样本量 = N·K/(1+(K−1)ρ)”。ρ=1 表示每个 case 要么总过要么总挂，重复毫无帮助。

| 设定 | 30×3 的有效样本量 | N=30 | N=100 | N=150 | N=200 |
|---|---|---|---|---|---|
| p=0.8, K=3, ρ=0.3 | 56.2 | ±10.5 | ±5.7 | ±4.7 | ±4.0 |
| p=0.8, K=3, ρ=0.5 | 45.0 | ±11.7 | ±6.4 | ±5.2 | ±4.5 |
| p=0.8, K=3, ρ=0.7 | 37.5 | ±12.8 | ±7.0 | ±5.7 | ±5.0 |
| p=0.8, K=1（或 ρ=1） | 30 | ±14.3 | ±7.8 | ±6.4 | ±5.5 |
| p=0.9, K=3, ρ=0.3 | 56.2 | ±7.8 | ±4.3 | ±3.5 | ±3.0 |
| p=0.9, K=3, ρ=0.5 | 45.0 | ±8.8 | ±4.8 | ±3.9 | ±3.4 |
| p=0.9, K=3, ρ=0.7 | 37.5 | ±9.6 | ±5.3 | ±4.3 | ±3.7 |
| p=0.9, K=1（或 ρ=1） | 30 | ±10.7 | ±5.9 | ±4.8 | ±4.2 |

结论：现有 30×3=90 trials 的精度相当于 37–56 个独立样本，通过率 0.9 时 CI 仍是 ±8–10 点。ρ 不必猜，可以直接从现有数据估：对每个 case 算 K 次的通过率 `p̂_i`，`σ̂² = mean_i[ K/(K−1)·p̂_i(1−p̂_i) ]`，`ρ̂ = 1 − σ̂²/(p̄(1−p̄))`（这一步是本笔记按全方差公式的推导，不是引文）。

**表 1-C：配对比较（同一批 case 上比较 A/B 两个版本，McNemar/Connor，双侧 α=0.05，power=0.8）所需 case 数**

| 不一致率 P_D（两版本结果不同的 case 占比） | 检出 5 点差异 | 检出 10 点差异 | 检出 15 点差异 |
|---|---|---|---|
| 0.05 | 155 | — | — |
| 0.10 | 312 | 77 | — |
| 0.15 | 469 | 116 | 50 |
| 0.20 | 626 | 155 | 68 |
| 0.25 | 783 | 194 | 85 |
| 0.30 | 940 | 234 | 103 |

对照：不配对（两批不同 case）时每组所需 N（`n = 7.849·[p1(1−p1)+p2(1−p2)]/δ²`）：0.80 vs 0.90 → 197；0.85 vs 0.90 → 683；0.80 vs 0.85 → 903；0.90 vs 0.95 → 432。配对设计在 P_D 较小时便宜得多，这是必须“同一批 case、逐 case 对比”的理由。

**表 1-D：给定 N 时配对比较的最小可检测差（MDE，百分点，80% power）**

| P_D | N=30 | N=60 | N=100 | N=120 | N=150 | N=200 | N=300 | N=500 |
|---|---|---|---|---|---|---|---|---|
| 0.10 | 达不到 | 达不到 | 8.8 | 8.0 | 7.2 | 6.2 | 5.1 | 4.0 |
| 0.15 | 达不到 | 13.7 | 10.7 | 9.8 | 8.8 | 7.6 | 6.2 | 4.8 |
| 0.20 | 达不到 | 15.9 | 12.4 | 11.3 | 10.1 | 8.8 | 7.2 | 5.6 |
| 0.30 | 26.9 | 19.4 | 15.2 | 13.9 | 12.4 | 10.8 | 8.8 | 6.8 |

“达不到”指即使所有不一致的 case 都朝同一方向，按 Connor 近似也达不到 80% power。也就是说 N=30 时只有 27 个点以上的差异才有 80% 把握检出。

**表 1-E：用 Miller 公式考虑每 case 重复 K 次（`n = 7.849·(ω² + 2σ²/K)/δ²`，设 A/B 的 σ² 相同）**

| ω²（逐 case 真实差的方差） | σ²（case 内随机性） | K | 检出 5 点所需 N | 检出 10 点所需 N | N=150 时的 MDE |
|---|---|---|---|---|---|
| 0.02 | 0.04 | 1 / 3 / 5 | 314 / 147 / 114 | 79 / 37 / 29 | 7.2 / 4.9 / 4.3 |
| 0.05 | 0.08 | 1 / 3 / 5 | 660 / 325 / 258 | 165 / 82 / 65 | 10.5 / 7.4 / 6.6 |
| 0.10 | 0.08 | 1 / 3 / 5 | 817 / 482 / 415 | 205 / 121 / 104 | 11.7 / 9.0 / 8.3 |

K=1 的 0/1 结果下 `P_D − δ² = ω² + σ_A² + σ_B²`，所以表 1-C 与表 1-E 是同一件事的两种参数化。从 K=1 到 K=3 收益明显，K=3 到 K=5 收益变小；当 ω² 主导时（版本间真的在不同 case 上各有输赢）加 K 无用，只能加 case。

**pass^3 的精度**：K=3 且 k=3 时，每个 case 的 pass^3 是 0/1，等价于 N 个 case 的二项比例。若单次通过率处处是 p，则 pass^3=p³：0.8→0.512，0.9→0.729，0.95→0.857（实际 `E[p_i³] ≥ (E p_i)³`）。pass^3≈0.7 时 CI 半宽：N=30 → ±16.4；N=100 → ±9.0；N=150 → ±7.3；N=200 → ±6.4。

**由此反推的规模逻辑（推断，不是引文，也不是项目事实）**
1. 先写下要支撑的结论，再读表得 N，而不是先定 N：(a) 报告通过率时 CI 半宽 ≤ 约 ±5–6 点；(b) 版本间 10 点的回退/提升有 80% power 检出；(c) 报告 pass^3 时半宽 ≤ 约 ±7–8 点。
2. (a) 单次运行时，p≈0.9 需要 N≈97–139，p≈0.8 需要 N≈171–246；每 case 跑 K=3 且 ρ≈0.5 时，N=150 在 p=0.8 也能到 ±5.2 点（表 1-B）。(b) 需要 N = Connor(P̂_D, 0.10)，P_D=0.15 → 116，P_D=0.20 → 155。(c) pass^3≈0.7 时 ±8 点需要 N≈126、±7.3 点需要 N=150。三条在 **N≈120–155（每条 K=3）** 处同时满足——这就是多轮端到端 tier 落在 100–200 区间的出处；其中起决定作用的是 (b)，具体数字取决于从现有 30×3 数据里量出来的 P̂_D 和 ρ̂，而不是凑整。
3. 检出 5 点差异需要 470–630 个 case（P_D=0.15–0.20）。这对多轮端到端 case 不现实，只能靠便宜的单步确定性 case（第 2 节）或者只对“10 点以上差异”做声明。面试时可以直接说：端到端集的 N 是按 10 点 MDE 设计的，5 点以内的差异在这个集上不做结论。
4. 推荐的比较方法：逐 case 配对差 + case 级 cluster bootstrap（重采样 case，同一 case 的 K 次运行整体进出）给差值 CI；或 K=1 / 以 pass^3 为指标时用 McNemar。同一场景模板生成的多个变体要按模板聚类算 SE（Miller 的 clustered SE），否则 CI 偏窄。

复算脚本（Python 标准库）：

```python
import math
from statistics import NormalDist
z = NormalDist().inv_cdf
za, zb = z(0.975), z(0.80)
wald   = lambda p, n: za * math.sqrt(p * (1 - p) / n)                       # 表 1-A
clus   = lambda p, n, K, rho: za * math.sqrt(p*(1-p)*(rho + (1-rho)/K) / n)  # 表 1-B
connor = lambda PD, d: (za*math.sqrt(PD) + zb*math.sqrt(PD - d*d))**2 / d**2 # 表 1-C
miller = lambda w2, s2, K, d: (za + zb)**2 * (w2 + 2*s2/K) / d**2            # 表 1-E
print(wald(0.9, 150), clus(0.9, 30, 3, 0.5), connor(0.15, 0.10), miller(0.05, 0.08, 3, 0.10))
```

### Gaps
- 没有找到 Anthropic 在 “Demystifying evals for AI agents” 之后发布的同主题后继文章；本笔记以该文（2026-01-09）和 commerce agents 架构文（2026-09-02）为准。
- 没有找到一篇 2026 主会论文直接给出“多轮对话 agent eval 需要多少 case”的经验公式；最接近的两篇（On Randomness in Agentic Evals、How Many Tasks Are Enough）都是 workshop，且对象是 coding / 通用 benchmark。
- paired bootstrap 本次没有单独抓取统计学出处页面；上文把它作为标准做法写在 Inferences 里，未附引文。
- Connor (1987) 原文（Biometrics 43(1):207–211）未直接读到，公式取自 SAS 文档对它的转述。
- 真实的 P_D（版本间不一致率）和 ρ（case 内相关）只能从项目自己的 30×3 运行记录里估，本笔记给的是参数网格，不是项目实测值。

## 2. 分层：便宜的确定性单步 case vs 昂贵的多轮端到端 case；dev / held-out 划分

### Takeaway
Anthropic 两篇官方文章都支持“两层”：大量可确定性判分的 snapshot / 单步 case 做主力和 CI 门禁，少量模拟用户的多轮对话用于发现问题和报告端到端可靠性；commerce agents 一文甚至明确说模拟用户对话是较差的测量工具（方差大、难归因）。held-out 比例没有统一标准：公开 benchmark 把大部分留作 test，Anthropic 的 skill-creator 用 60/40；可引用的只有“必须留一份没用来调 prompt 的集合”这一原则。

### Cited Findings
- commerce agents 一文把 eval 定义为 snapshot：构造好测试状态和用户消息，让 agent 跑，对最终状态和渲染输出（含最后一次写操作的参数）判分，不对路径判分；受监管文本逐字节比对，价格/库存必须能追溯到工具返回值。【Anthropic 官方，2026-09-02；由抓取摘要转述】— [The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- 同文对“第二个模型扮演顾客 + judge 判分”的模拟对话评价是：方差和归因问题使它不适合作为测量工具，建议用模拟去**发现** case，再把每个发现写成 snapshot。— [The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- 同文的回归分层规则：每次改动跑 CI 子集（高流量核心 case + 全部安全 case + 涉及被改组件的 case）；改一个 skill 就跑它自己的 case 加相邻 skill 的边界 case；改一个 tool 就跑所有调用它的 case；改共享 prompt 跑全量；全量每晚和发版前跑。— [The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- 同文要求部分 case 从冗长、混乱、自相矛盾的历史开始，因为只有干净初始状态的 case 在任何配置下都会通过（没有区分度）。— [The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- “Demystifying evals” 把 grader 分为 code-based / model-based / human 三类，主张能用确定性 grader 就用，必要时才用 LLM grader，人工用于校准；并区分 capability eval（起步通过率低、给团队一个爬坡目标）与 regression eval（通过率应接近 100%），前者通过率高了可以“毕业”进回归集。【Anthropic 官方，2026-01-09】— [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- 同文指出对话型 agent 的 eval 常需要第二个 LLM 模拟用户，并以 τ-Bench / τ2-Bench 为例；自动化 eval 适合上线前和 CI/CD 里在每次 agent 改动和模型升级时跑。— [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- held-out 的原则性依据：Anthropic 在优化工具时用 held-out test set 防止对“训练用”评测过拟合。【Anthropic 官方，2025-09-11】— [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- skill-creator 的 description 优化循环把查询集按 60% train / 40% held-out test 划分，最终按 test 分数而不是 train 分数选最优 description。【Anthropic 官方 skill 源码】— [anthropics/skills: skill-creator/SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)
- agentskills.io 的同名指南补充：划分时正反例要按比例分到两边、随机打乱后固定不变；优化结束后再写 5–10 条从未参与优化的新查询做最终检查。【Agent Skills 开放规范站点，Claude Code 官方文档链接指向该站】— [Optimizing skill descriptions](https://agentskills.io/skill-creation/optimizing-descriptions)
- 公开 benchmark 的划分比例差异很大：TravelPlanner 1,225 条 = train 45 / validation 180 / test 1,000（test 占 81.6%）；ChinaTravel 是 Human-Val 154 条、Human-Test 1,000 条。【背景·≤2025：TravelPlanner，ICML 2024 Spotlight】【2026 顶会·已核实：ChinaTravel，ICLR 2026 proceedings】— [TravelPlanner, arXiv 2402.01622](https://arxiv.org/html/2402.01622)；[ChinaTravel, arXiv 2412.13682v5](https://arxiv.org/html/2412.13682v5)
- 美团把评测集按视角分为“端到端集”（从用户视角判断任务是否完成，决定要不要报警）和“过程集”（定位哪一步出错，可继续按知识库、单个 Skill 等模块拆分），并建议不要过早拆分，由真实问题驱动。【行业博客，2026-09-10】— [《Agent 评测白皮书》系列01：Agent 评测全览](https://tech.meituan.com/2026/09/10/Agent-Evaluation-White-Paper-01.html)
- 美团的门禁分级：安全与数据准确类检查阻断发布，体验类用阈值；每个 Task 多次 trial 按通过率判定；门禁只有接入 CI/CD 才有约束力。— [《Agent 评测白皮书》系列01](https://tech.meituan.com/2026/09/10/Agent-Evaluation-White-Paper-01.html)

### Inferences
（以下是推断与建议，不是项目事实。）
- **两层的统计分工**直接来自第 1 节：
  - Tier A（便宜、确定性、单步或 snapshot）：一次模型调用 + 代码判分，如规则校验、路由决策（该不该 `load_skill`、该调哪个 tool）、从给定对话历史出发的“下一步动作”。目标是能检出 5 点差异 → 按表 1-C 需要约 310–630 条（P_D=0.10–0.20）。这一层同时承载 skill 触发查询集（第 5 节）。
  - Tier B（昂贵、多轮、模拟用户）：目标只定在检出 10 点差异和报告 pass^3 → N = Connor(P̂_D, 0.10)，约 116–155 条，每条 K=3。
- commerce agents 一文的“每个 user flow 50–100 条”与上面的 Tier B 规模相容：若旅行 agent 划成 2–3 个 flow（例如规划、改单、问询），每个 flow 50 条左右即落在 100–150。
- dev / held-out：没有文献给出必须的比例。可辩护的做法是沿用 Anthropic 自己工具里唯一明确的 60/40，并做三点处理：(1) 按“场景模板”分组划分（同模板的变体不跨两边，否则泄漏）；(2) 现有 30 条已被反复看过，全部归入 dev / 回归集，不进 held-out；(3) held-out 只在版本定稿时跑，报告 dev 与 held-out 的差距作为过拟合指标。
- 代价要说清楚：若 Tier B 共 150 条、held-out 占 40%（60 条），held-out 上单看通过率的 CI 在 K=3、ρ=0.5 时约 ±6–8 点（表 1-B），配对 MDE 约 14–16 点（表 1-D）。所以 held-out 的作用是“无偏的绝对水平 + 过拟合检查”，版本间的配对检验仍要用全量并注明其中 dev 部分参与过调参。
- 把模拟对话里发现的失败“固化成 snapshot”（Anthropic 的建议）可以让 Tier B 的发现持续流入 Tier A，Tier A 的规模因此会自然增长，不需要一次造满。

### Gaps
- 没有找到任何来源给出“dev : held-out 应该是多少”的定量论证；60/40 只是 Anthropic 工具中的默认值，不是统计结论。
- commerce agents 一文未涉及 held-out（抓取摘要明确说没有）。
- Tier A / Tier B 的成本比（token、时长）只能由项目实测，本笔记无数据。

## 3. 2025–2026 的数据集构建方法与可比数据集的规模构成

### Takeaway
2026 顶会 benchmark 的共同做法是“LLM 生成 + 可执行校验 + 人工二次过滤”，规模集中在 100–400 条人工把关的任务（MCP-Bench 104、MCPMark 127、VitaBench 100+300、ChinaTravel 人工集 154），上千条的要么是问卷众包（ChinaTravel 1000）要么是模板合成。分层通常是“场景 × 难度”的小矩阵，每格 5–100 条。

### Cited Findings

**可比数据集的规模与构成**

| 数据集 | 规模与构成（原文数字） | 构建方式 | 分级与核实 | 来源 |
|---|---|---|---|---|
| τ-bench | retail 115 个任务、airline 50 个任务 | 人工设计 schema/API/policy；gpt-4 辅助生成数据；人工写任务后用 gpt-4-turbo 反复试跑修订，retail 每个任务至少 40 次试跑以消除歧义 | 【背景·≤2025】arXiv 2024-06，arXiv 页面未列 venue | [arXiv 2406.12045](https://arxiv.org/html/2406.12045) |
| TravelPlanner | 1,225 条 = train 45 / val 180 / test 1,000；按 3/5/7 天 × easy/medium/hard 分 9 组，train 每组 5、val 每组 20、test 每组 82–122 | 随机抽出发地/目的地/日期等要素，GPT-4 生成自然语言 query；研究生标注参考方案，方案须通过评测脚本全部约束才算数（抓取文本此处数字有渲染重复，标注者人数以原文为准） | 【背景·≤2025】ICML 2024 Spotlight（arXiv comments） | [arXiv 2402.01622](https://arxiv.org/html/2402.01622)；[abs 页](https://arxiv.org/abs/2402.01622) |
| ChinaTravel | Easy 300（LLM 生成）；Human-Val 154；Human-Test 1,000；摘要称来自 1154 名参与者 | 合成集：随机 query 骨架由 DeepSeek-V2.5 转成自然语言，作者人工核对并用启发式搜索确认至少有一个可行解；人工集：问卷收集 250+ 条需求，质控后留 154 条，再经问卷平台扩到 1000 | 【2026 顶会·已核实】ICLR 2026：proceedings.iclr.cc 条目 + iclr.cc poster 页 + arXiv comments | [ICLR 2026 proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/9b01c4a7d3fc49875dad3c13848bcd9e-Abstract-Conference.html)；[arXiv 2412.13682v5](https://arxiv.org/html/2412.13682v5) |
| VitaBench | 66 个工具；跨场景任务 100 + 单场景 300（外卖 / 到店 / OTA 旅行）；最强模型跨场景约 30%、单场景低于 50% | 每个任务由多条真实用户请求合成；用 rubric-based sliding window evaluator 判分 | 【2026 顶会·已核实】ICLR 2026 poster 页（含 OpenReview 链接）；页面未写明 track | [iclr.cc poster 10007108](https://iclr.cc/virtual/2026/poster/10007108) |
| MCP-Bench | 28 个 MCP server、250 个工具、104 个任务（单 server 56 / 双 30 / 三 18） | o4-mini 按工具依赖链合成任务；质量过滤阈值 solvability 9.0/10、utility 5.0/10，不达标丢弃；再人工检查真实性与可执行性；每个任务附加 10 个 distractor server（100+ 个额外工具） | 【2026 顶会·已核实】ICLR 2026 poster 页 + OpenReview forum id | [iclr.cc poster 10008216](https://iclr.cc/virtual/2026/poster/10008216)；[arXiv 2508.20453](https://arxiv.org/html/2508.20453) |
| MCPMark | 127 个任务，每个含人工整理的初始状态和程序化验证脚本；平均 16.2 轮、17.4 次工具调用 | 领域专家与 AI agent 协作编写 | 【2026 顶会·已核实】ICLR 2026 proceedings | [ICLR 2026 proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8138d211ce8790fdfbeeeb9781838a37-Abstract-Conference.html) |
| SkillsBench | 摘要：87 个任务、8 个领域，每个任务配 curated Skills 和确定性 verifier；18 个 model-harness 配置（不同版本摘要的任务数略有出入） | 同一任务成对跑“无 skill / 有 skill” | 【2026 顶会·已核实】NeurIPS 2026 poster 页（2026-12-11 场次）；页面未写明 track | [neurips.cc poster 139353](https://neurips.cc/virtual/2026/poster/139353) |
| DynamicMCPBench | 121 个 server、750 个任务 = 15 类 × 50；31% 的任务没有任何模型解出；人工验证与自动判分的一致性（chance-corrected）0.76 | 自动生成目标 → 记录一条成功轨迹 → 提炼为 effect checkpoint → 按是否复现效果判分 | 【2026 顶会·自述未独立核实】arXiv comments 写 Accepted to EMNLP 2026 | [arXiv 2607.20531](https://arxiv.org/abs/2607.20531) |
| ComplexMCP | 7 个有状态沙箱、300+ 工具；最强模型成功率不超过 60%，人类约 90% | seed 驱动的环境状态与 API 故障模拟 | 【2026 顶会·已核实】ICML 2026，PMLR 306 | [PMLR v306 li26ij](https://proceedings.mlr.press/v306/li26ij.html) |

**构建流程中的具体做法**
- Anthropic 指南：为每个 task 写 reference solution（能通过全部 grader 的已知正确输出）；多次 trial 通过率接近 0% 通常说明 task 本身坏了而不是 agent 不行；正反两类 case 都要测，避免类别不平衡；每个 trial 从干净环境开始，共享状态会造成相关失败或虚高。原话里最值得记的一句是 “One-sided evals create one-sided optimization.”【Anthropic 官方，2026-01-09】— [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- 同文：把用户报告的失败转成 test case，使 eval 反映真实使用；要大量阅读 transcript 和评分结果才能知道 grader 是否可靠；LLM-as-judge 需要与人工专家校准；多组件任务要给 partial credit。— [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- Anthropic 对评测任务的要求：来自真实用途和真实数据，避免过于简单的沙箱；强任务可能需要多次乃至几十次工具调用；每个 prompt 配一个可验证的结果，verifier 不要因无关差异（格式等）误杀正确答案。【Anthropic 官方，2025-09-11】— [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- commerce agents 一文的覆盖维度：核心请求、依赖上下文的请求、安全与品牌、界面检查、需要相邻两种能力的请求；另有注入测试（用户侧注入与数据面注入）和记忆测试；可以让 coding agent 生成对抗变体。【Anthropic 官方，2026-09-02；由抓取摘要转述】— [The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- 美团的评测样本分类：黄金集（定义可接受质量的下限）、错题集（犯过的错进回归）、挑战集（能力边界，难维护、需随线上流量刷新）、必过集（核心功能和已知问题，发版前必须通过）；样本来源包括线上反馈、线上监控、业务规则和随机抽样，其中随机抽样是发现“没预料到的问题”的唯一途径。【行业博客，2026-09-10】— [《Agent 评测白皮书》系列01](https://tech.meituan.com/2026/09/10/Agent-Evaluation-White-Paper-01.html)
- 美团的冷启动做法：人工先产出少量样本，再用 AI 辅助生成或扩写，低成本搭出种子评测集；之后从生产环境收集 Bad Case、沉淀 Good Case，转成标准评测样本，版本升级后自动触发历史 Case 回归。评分规则收敛为“是/否/未知”，用 unknown 占比反查 Rubric 是否合理，迭代到人人一致率、人机一致率达到阈值（文中举例 85% 或 90%）。【行业博客，2026-08-07】— [Agent评测漫谈](https://tech.meituan.com/2026/08/07/Agent-Evaluation.html)
- 泄漏与评测卫生：Vercel 在得出结论前先“加固”了 eval（去掉 test leakage、消除互相矛盾的要求、改成基于行为的断言）；HAL 通过日志检查发现 agent 会去 HuggingFace 搜 benchmark 本身。【行业博客，2026-01-27】【2026 顶会·已核实】— [Vercel: AGENTS.md outperforms skills in our agent evals](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)；[HAL, ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/a0928f924a344aaebbb7f6cd8d56e34c-Abstract-Conference.html)
- 难度分层的两个公开范例：TravelPlanner 用“天数 × 硬约束数量”划 9 组；ChinaTravel 的合成集 Easy 只多 1 个约束、Medium 多 3–5 个，人工 query 每条约 6–12 个约束。— [arXiv 2402.01622](https://arxiv.org/html/2402.01622)；[arXiv 2412.13682v5](https://arxiv.org/html/2412.13682v5)

### Inferences
（推断与建议。）
- **“AI 生成 + 人工二次过滤”有顶会先例可引**：MCP-Bench（LLM 合成 → 自动打分过滤 → 人工检查）、ChinaTravel 合成集（骨架 → LLM 转写 → 人工核对 + 可行解校验）、MCPMark（专家 + agent 协作 + 验证脚本）。共同点是三道闸：自动可执行性校验、reference solution / 可行解存在性、人工读一遍。个人项目照搬这三道闸即可自称方法与 2026 顶会 benchmark 一致，但规模和人工标注量不可比，要如实说明。
- **场景 × 画像 × 扰动矩阵**：没有找到直接以这三个轴命名的顶会方法，最近的范例是 TravelPlanner 的 3×3 分组和 DynamicMCPBench 的 15 类 × 50。建议把矩阵当作“分层抽样框”而不是全排列：先定每格目标条数（例如每格 5–10 条），生成 2–3 倍候选，人工过滤到目标数，并记录过滤率。
- **矩阵生成的 case 是成组相关的**：同一场景模板的不同画像/扰动变体应按模板聚类算 SE，并整组划入 dev 或 held-out（第 1、2 节）。
- **难度分层目标**：Anthropic 的 capability / regression 二分 + “30%–70% 通过率的任务信息量最大”（预印本）共同指向：回归层（现有 30 条 + 历史失败，预期 ≈100%）不贡献区分度，只做门禁；新增的 case 应有意造在中等难度，否则 N 再大也是在天花板上测噪声。可用现有模型先试跑 3 次，按通过率把候选分成“稳过 / 不稳 / 稳挂”，稳挂的先按 Anthropic 的提示检查是不是 task 写坏了。
- **规模对标**：100–200 条人工把关的多轮任务与 τ-bench（115+50）、MCP-Bench（104）、MCPMark（127）、ChinaTravel Human-Val（154）处于同一量级，这是一个可以直接对面试官说的事实对照。
- **去重**：可执行的最低标准是（a）同模板变体视为一簇，（b）对用户首句和约束集合做近似重复检查，（c）held-out 不与 dev 共享模板。这些是工程常识性做法，本次未找到给出具体阈值的文献。

### Gaps
- 未找到公开来源给出去重的定量阈值（如 embedding 相似度多少算重复）或泄漏检测的标准流程。
- 美团《白皮书》系列02（2026-11-17，商家 AI 助手的评测与优化闭环）只在搜索摘要里看到标题和简介，未读到原文，不引用其细节。
- τ2-Bench 的规模与 venue 本次未核实。
- VitaBench、SkillsBench 的任务“是否经人工验证”在已抓取页面中没有明确表述。
- TravelPlanner 标注者人数在抓取文本中有渲染重复，未能确认确切数字。

## 4. Skill 路由机制，以及工具 / skill / MCP 选择准确率随库规模的变化

### Takeaway
Agent Skills 的选择完全靠常驻上下文里的 name + description 由模型自行决定是否加载；公开数据里有两类不同的失败：**不触发**（库很小也会发生，行业与社区的小样本测量约 45%–56% 未触发）和**选错**（主要在库变大或存在语义相近的竞争项时出现）。Anthropic 文档的经验阈值是工具超过 30–50 个后选择准确率下降；2026 的证据显示强模型在几十到两百个工具、带少量 distractor 时基本不混淆，退化出现在数百工具或检索受限的条件下，而且“语义相似度”比“数量”更致命。

### Cited Findings

**机制（Anthropic 官方）**
- 三级渐进加载：Level 1 metadata（name + description）启动时进入 system prompt，约每个 skill 100 tokens；Level 2 SKILL.md 正文在触发时才读入，建议 5k tokens 以内；Level 3 附带文件按需读取。description 是模型判断是否触发的依据。name 上限 64 字符，description 上限 1,024 字符。【Anthropic 官方文档】— [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- 文档明确说 description 用于从“可能 100 个以上”的 skill 中选出正确的一个；建议 SKILL.md 正文不超过 500 行；至少建 3 个评测场景并先测无 skill 的基线。【Anthropic 官方文档】— [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- Claude Code 中 skill 列表有字符预算：按模型上下文窗口的 1% 伸缩；超预算时保留所有 skill 名称但从最少调用的开始丢弃 description（丢掉的正是匹配所需的关键词）；单条 description + when_to_use 合计上限 1,536 字符。【Anthropic 官方文档】— [Claude Code: Skills](https://code.claude.com/docs/en/skills)
- skill 被调用后正文作为一条消息留在对话里并跨后续轮次保留，所以正文每一行都是重复出现的 token 成本；自动压缩后每个 skill 只保留前 5,000 tokens，合计预算 25,000 tokens。— [Claude Code: Skills](https://code.claude.com/docs/en/skills)
- skill-creator 文档指出模型倾向于“少触发”（undertrigger），简单一步能完成的请求即使 description 匹配也可能不查 skill，因此建议把 description 写得“主动”一些。【Anthropic 官方 skill 源码】— [skill-creator/SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)
- Anthropic 对 skill-creator 的发布说明：skill 数量增长后 description 的精确度变得关键，太宽会误触发、太窄则不触发；用 description 优化在 6 个公开的文档类 skill 中有 5 个改善了触发。【Anthropic 官方，2026-03-03】— [Improving skill-creator](https://claude.com/blog/improving-skill-creator-test-measure-and-refine-agent-skills)
- commerce agents 一文：加载一个 skill 要花一次模型轮次；与约三分之一及以上流量相关的内容应留在 system prompt，其余进 skill；skill 最好以 tool result 形式加载，这样内容随对话前缀一起被缓存；关键规则（安全、法律、品牌等）留在 system prompt；其参考购物 agent 用 5 个 skill。【Anthropic 官方，2026-09-02；由抓取摘要转述】— [The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)

**Anthropic 公布的工具规模数字**
- Tool Search Tool 的内部 MCP 评测：Opus 4 从 49% 提到 74%，Opus 4.5 从 79.5% 提到 88.1%；5 个 server 共 58 个工具约占 55K tokens，Anthropic 内部见过工具定义占 134K tokens；启用后 token 用量减少约 85%。最常见的失败是选错工具和参数错误，尤其是名字相近的工具。【Anthropic 官方，2025-11-24，内部评测】— [Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)
- 文档给的经验阈值：可用工具超过 30–50 个后选对工具的能力下降；建议在工具 ≥10 个或定义超过 10k tokens 时用 tool search，少于 10 个时不必；保留 3–5 个最常用工具不延迟加载；每次搜索默认返回最多 5 个。【Anthropic 官方文档】— [Tool search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- 工具太多或功能重叠会分散 agent 注意力；更多工具不一定更好；用统一前缀做 namespacing 有助于划清边界。【Anthropic 官方，2025-09-11】— [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)

**触发可靠性的公开测量（非论文）**
- Vercel 的 Next.js 文档 skill 实验：56% 的 eval case 里 skill 从未被调用；默认 skill 配置通过率 53%，与无文档基线 53% 相同；加显式指令后 79%；改为 AGENTS.md 常驻的压缩文档索引为 100%。指令措辞很脆弱：要求“先调用 skill”与“先探索项目再调用 skill”结果不同。文章未说明任务数、模型和运行次数。【行业博客，2026-01-27】— [AGENTS.md outperforms skills in our agent evals](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)
- Scott Spence 的沙箱测量：装 4 个 Svelte skill、22 条 prompt、Sonnet 4.5，两轮运行无 hook 时激活率 55%（12/22）和 50%（11/22）；forced-eval hook 两轮均 100%（22/22）。另一组 24 条较难 prompt（其中 5 条不该触发）：forced-eval 总准确率 75%（18/24）、误触发 0；llm-eval 67%（16/24）、误触发 4。总花费 5.59 美元，约 250 次调用；作者自己强调样本很小、基线两轮间就有 5 点波动。【社区博客，2026-02-08】— [Measuring Claude Code Skill Activation With Sandboxed Evals](https://scottspence.com/posts/measuring-claude-code-skill-activation-with-sandboxed-evals)

**库规模与选择准确率（论文）**
- When Single-Agent with Skills Replace Multi-Agent Systems and When They Fail：合成 skill 库，规模 5–200（{5,10,20,35,50,75,100,150,200}），GPT-4o-mini 与 GPT-4o，temperature 0，3 个随机种子。|S| ≤ 20 时选择准确率高于 95%，超过 50 后陡降，|S|=200 时约 20%，容量阈值 κ 约 50–100。语义竞争项的影响更大：每个 skill 加 1 个竞争项准确率降 7–30%，加 2 个降 17–63%；|S|=20 时把独立 skill 换成“基础-竞争”对会降 18–30%。分层路由在 |S| ≥ 60 时把准确率从约 45–63% 提到约 72–85%。局限：合成 skill、只测选择不测端到端、只有两个 OpenAI 模型。【arXiv 预印本·未核实 venue，2026-01-08，作者自称 ongoing research】— [arXiv 2601.04748](https://arxiv.org/html/2601.04748v1)
- MCP-Bench：主实验给每个任务附 10 个 distractor server（100+ 额外工具），论文报告的总体平均里强模型的工具名有效率、schema 合规率、执行成功率仍接近满分（gpt-5 为 100.0% / 99.3% / 99.1%；llama-3-1-8b-instruct 为 96.1% / 89.4% / 90.9%）；没有做“工具数 vs 准确率”的受控消融。【2026 顶会·已核实：ICLR 2026】— [arXiv 2508.20453](https://arxiv.org/html/2508.20453)；[iclr.cc poster 10008216](https://iclr.cc/virtual/2026/poster/10008216)
- DynamicMCPBench：默认每个任务给所需工具加 8 个 distractor（一半是其他 server 上的同名工具）。默认设置下“工具对但 server 错”的错误接近地板（0.2% 的运行）；预注册假设是 hard-negative 比随机 distractor 的混淆率至少高 15 个点，实测差距只有 0.6 个点、不显著。但当工具需要先检索时（rag:8，只给检索到的 8 个工具），通过率下降 16–23 点（claude-haiku-4.5 37.3→21.3，kimi-k2.6 42.7→24.7，minimax-m3 44.0→24.0，qwen 54.0→30.7）；把全部 1,168 个工具平铺只在一个模型上跑了，44.0→36.0。作者提醒受控 distractor 池的结论不能当作开放检索条件的替代。【2026 顶会·自述未独立核实：EMNLP 2026】— [arXiv 2607.20531](https://arxiv.org/html/2607.20531)
- MCPVerse：65 个 MCP、552 个工具、250 个任务，三种挂载模式——Oracle（只给所需工具）、Standard（32 个 MCP、220+ 工具、约 44k tokens）、Max-Scale（65 个 MCP、550+ 工具、约 140k tokens）。Claude-4-Sonnet 成功率 62.3 / 62.4 / 44.2；Qwen3-235B-2507 为 44.8 / 53.2 / 26.7；DeepSeek-V3-0324 为 46.8 / 32.7 / 无法评测。即 220+ 工具时强模型基本不掉，550+ 时明显下降。【背景·≤2025，arXiv 2025-10，未核实 venue】— [arXiv 2508.16260](https://arxiv.org/html/2508.16260v2)
- ComplexMCP：300+ 工具的有状态沙箱里，全上下文与 RAG 两种设置下最强模型都不超过 60%，作者把“动作空间变大后的工具检索饱和”列为三大瓶颈之一（摘要未给分规模数字）。【2026 顶会·已核实：ICML 2026，PMLR 306】— [PMLR v306 li26ij](https://proceedings.mlr.press/v306/li26ij.html)
- RAG-MCP：先检索再选工具把选择准确率从 13.62% 提到 43.13%，prompt tokens 减少一半以上。【背景·≤2025，arXiv 2025-05，未核实 venue】— [arXiv 2505.03275](https://arxiv.org/abs/2505.03275)
- ToolMenuBench：变化工具菜单大小、distractor 类型等，7 个模型后端、3 种菜单规模；一种最小化工具过滤方法把任务成功率从全部工具暴露时的 32.1% 提到 85.7%，平均 token 降约 98%（摘要未给具体菜单规模）。【arXiv 预印本·未核实 venue，2026-06-13】— [arXiv 2606.15508](https://arxiv.org/abs/2606.15508)
- SkillsBench：有 curated skill 时平均通过率从 33.9% 升到 50.5%（+16.6 点），各配置增益 +4.1 到 +25.7 点；不超过三个模块的聚焦型 skill 优于更大或面面俱到的包。它衡量的是“skill 有没有用”，不是“选得对不对”。【2026 顶会·已核实：NeurIPS 2026 poster 页】— [neurips.cc poster 139353](https://neurips.cc/virtual/2026/poster/139353)

### Inferences
（推断。）
- 要把两个问题分开讲：**(1) 触发召回**——该加载时有没有加载。Vercel（1 个 skill，56% 未调用）和 Scott Spence（4 个 skill，约一半未激活）说明这在库很小时就存在，与库规模无关，主要受“模型觉得自己不需要”驱动（Anthropic 自己也承认 undertrigger）。**(2) 选择精度**——在多个候选里选对。只有后者随库规模和语义相似度恶化。
- 把现有证据排成一条粗略的曲线（不同模型、不同对象，不可直接拼接，只看量级）：≤20 个基本无损（预印本 >95%）；30–50 是 Anthropic 文档给的退化起点；50–100 是预印本里较老模型的陡降区；强模型在 100+ 到 220+ 个工具时仍稳（MCP-Bench 的 distractor 设置、MCPVerse Standard）；550+ 明显下降（MCPVerse Max-Scale −18 点）；上千个时必须检索，而检索本身带来 16–23 点损失（DynamicMCPBench）。
- “数量”与“相似度”两个因素中，对小库更重要的是相似度：预印本在 |S|=20 时仅靠引入竞争项就降 18–30%；但 DynamicMCPBench 在 2026 年的模型上发现同名 distractor 几乎不造成混淆。两者矛盾的可能原因是模型代际（GPT-4o 系 vs 2026 年模型）和任务形式（单步选择 vs 多步执行）不同——所以 demo 的曲线很可能是平的，这一点要事先想好怎么报告（见第 6 节）。
- 项目的实现方式（`load_skill` 工具 + system prompt 列触发条件，属任务给定背景）与 Agent Skills 的 Level 1/Level 2 机制同构，与 commerce agents 一文建议的“skill 以 tool result 形式加载”一致；因此 Anthropic 关于 description 写法、undertrigger、token 成本的结论可以迁移，但 Claude Code 的列表预算（1%）等产品细节不适用于自建 harness。

### Gaps
- 没有找到 Anthropic 官方发布的“skill 触发率”绝对数字（只有“6 个里 5 个改善”这种相对表述和 tool search 的准确率）。
- 没有找到 2026 主会论文在受控条件下给出“skill 数量 10/30/50/100/500 → 选择准确率”的完整曲线；唯一画出这条曲线的是 arXiv 预印本（2601.04748），且逐点数值在图里，正文只给了区间。
- HumanMCP（arXiv 2602.23367）在搜索摘要中出现过“500 个工具 87.4% → 2,000 个工具 65%”的说法，但其 arXiv 摘要页没有这些数字，未能核实，不采用。
- SRA-Bench（arXiv 2604.24594）、How Well Do Agentic Skills Work in the Wild（arXiv 2604.04323）、SWE-Skills-Bench（arXiv 2603.15401）只在搜索结果里见到标题和一句话简介，未读原文、未核实 venue。
- ToolRet（Findings of ACL 2025，arXiv 2503.01763）只在搜索摘要中看到数字（43k 工具、7.6k 检索任务、最好 nDCG@10 为 33.83），未抓取原文核实，仅作背景线索。

## 5. Skill hit rate 的测量协议

### Takeaway
Anthropic 自己的做法已经是一套可照搬的协议：每个 skill 约 20 条查询（8–10 条应触发、8–10 条不应触发且以“近似但不该触发”的 near-miss 为主），每条跑 3 次算触发率，阈值 0.5 判过，60/40 划分后只用 train 的失败改 description，最多迭代 5 轮，按 held-out 分数选版本。但每个 skill 只有 10 条正例时，单 skill 的召回率 CI 宽到 ±20 点，只能做诊断；库级 hit rate 要靠合并各 skill 的查询才能到 ±5 点。

### Cited Findings
- 查询集规模与构成：约 20 条，8–10 条 should-trigger（正式/口语/含错别字、显式点名/只描述需求、长短不一、单步/多步混合），8–10 条 should-not-trigger；最有价值的反例是与 skill 共享关键词但实际需要别的东西的 near-miss，明显无关的反例测不出任何东西；查询要像真实用户会输入的（带文件路径、个人背景、具体数值）。【Anthropic 官方 / 开放规范】— [skill-creator/SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)；[Optimizing skill descriptions](https://agentskills.io/skill-creation/optimizing-descriptions)
- 重复与判定：每条查询跑多次（3 次是合理起点），触发率 = 触发次数 / 运行次数；应触发的查询触发率高于阈值（默认 0.5）算通过，不应触发的低于阈值算通过；20 条 × 3 次 = 60 次调用。判定“是否触发”的依据是 agent 是否加载了该 skill 的 SKILL.md（例如在 JSON 输出里找对应的 Skill tool_use）；结果已明确后可以提前终止运行以省成本。— [Optimizing skill descriptions](https://agentskills.io/skill-creation/optimizing-descriptions)
- 防过拟合：约 60% train / 40% validation，正反例按比例分到两边、固定不变；只看 train 的失败来改 description，不要把失败查询里的具体关键词塞进去（那是过拟合），而要概括其类别；通常 5 轮足够；按 validation 通过率选版本（最好的不一定是最后一版）；最后再写 5–10 条全新查询做泛化检查。— [Optimizing skill descriptions](https://agentskills.io/skill-creation/optimizing-descriptions)
- skill-creator 的自动化循环参数与上面一致：60/40、每条 3 次、`--max-iterations 5`、按 test 分数选。— [skill-creator/SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)
- with-skill vs without-skill 消融：skill-creator 对每个 test case 同时起两个 subagent（有 skill / 无 skill；改进已有 skill 时基线是旧版本），聚合 pass rate、耗时、token 的均值 ± 标准差和差值；Claude Code 文档描述 benchmark 输出用于比较通过率提升与 token、时间开销，并支持两个版本间的盲测 A/B。— [skill-creator/SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)；[Claude Code: Skills](https://code.claude.com/docs/en/skills)
- 在端到端运行中量触发：Claude Code 的 `claude plugin eval` 支持 `tool_used: Skill` grader，可在一批真实 prompt 上统计 skill 的触发频率，并在每次改 description 后重跑；它在隔离会话中分别跑“有插件 / 无插件”。— [Claude Code: Skills](https://code.claude.com/docs/en/skills)
- 正反两类都要测是 Anthropic eval 指南的通用要求（以“该搜索 / 不该搜索”的查询为例）；commerce agents 一文要求每个正例配一个反例，且改一个 skill 时要跑相邻 skill 的边界 case。— [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)；[The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- 混淆项的重要性：Anthropic 报告最常见的工具失败是名字相近的工具之间选错；预印本显示每个 skill 加 1–2 个竞争项使准确率下降 7–63%。— [Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)；[arXiv 2601.04748](https://arxiv.org/html/2601.04748v1)
- 误加载的成本（token）：SKILL.md 正文建议 5k tokens 以内，加载后留在对话中跨轮次保留，是重复成本；commerce agents 一文补充加载本身要花一次模型轮次。— [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)；[Claude Code: Skills](https://code.claude.com/docs/en/skills)；[The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- 漏加载的成本（任务失败）：Vercel 的实验里默认 skill 配置与无文档基线通过率相同（53%），而常驻上下文方案 100%——即漏加载时 skill 的价值为零。【行业博客】— [AGENTS.md outperforms skills in our agent evals](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)
- 加载时机也影响结果：Vercel 发现“先调用 skill 再看项目”会让 agent 锚定在文档模式上而漏掉项目上下文，“先探索再调用”效果更好。— [AGENTS.md outperforms skills in our agent evals](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)
- 必须每次都成立的规则不应依赖 skill 是否被遵循：Claude Code 文档建议把这类规则放进 hook；commerce agents 一文建议关键规则留在 system prompt、并由服务端强制。— [Claude Code: Skills](https://code.claude.com/docs/en/skills)；[The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- Skill 的评测要随模型更新重跑：能力补足型 skill 可能随模型进步而不再必要，eval 能告诉你何时发生。【Anthropic 官方，2026-03-03】— [Improving skill-creator](https://claude.com/blog/improving-skill-creator-test-measure-and-refine-agent-skills)

### Inferences
（以下协议是把上面引文拼成的建议，属推断；数字按第 1 节公式计算。）

**指标定义**（以“查询”为单位；每条查询标注应加载的 skill 集合，可为空）
- 对 skill s：TP = 应加载且加载；FN = 应加载未加载；FP = 不应加载却加载。`precision_s = TP/(TP+FP)`，`recall_s = TP/(TP+FN)`，`F1_s`。
- 库级：`hit rate`（micro recall）= 全部正例中加载了正确 skill 的比例；`false-load rate` = 全部反例中发生任何加载的比例；`wrong-skill rate` = 正例中加载了但加载错的比例（由此得到 skill × skill 混淆矩阵，专门看 confusable pair）。
- 时机（“在对的时间加载”）：端到端轨迹里再加一条“首次需要该 skill 内容的动作之前已加载”的比例；晚加载和早加载（加载后整段对话没用到）分别计数。

**每个 skill 需要多少条标注查询**

| 正例数 n、观测 | 95% Wilson 区间 | 含义 |
|---|---|---|
| 9/10 | 59.6–98.2 | 单 skill 10 条正例只能看出“明显坏了” |
| 18/20 | 69.9–97.2 | |
| 27/30 | 74.4–96.5 | 单 skill 想说“召回约 90%”至少要 30 条正例 |
| 54/60 | 79.9–95.3 | |
| 108/120 | 83.3–94.2 | |
| 10/10（零漏） | 72.2–100；漏触发率精确上界 25.9% | rule of three：0 次漏触发时上界约 3/n |
| 30/30（零漏） | 88.6–100；上界 9.5% | |
| 60/60（零漏） | 上界 4.9% | |

库级 micro hit rate 的 CI 半宽（Wald，百分点）：

| 正例总数 M | hit rate 0.80 | 0.90 | 0.95 |
|---|---|---|---|
| 48 | ±11.3 | ±8.5 | ±6.2 |
| 60（6 skill × 10） | ±10.1 | ±7.6 | ±5.5 |
| 120（12 × 10 或 6 × 20） | ±7.2 | ±5.4 | ±3.9 |
| 144 | ±6.5 | ±4.9 | ±3.6 |
| 240（12 × 20） | ±5.1 | ±3.8 | ±2.8 |

- 结论：Anthropic 的“每 skill 约 20 条（10 正 10 反）”是为**调 description** 设计的，够用来发现问题，不够给单个 skill 报一个稳定的召回率。要报库级 hit rate ±5 点（0.9 附近），正例总数需要约 139（表 1-A 的同一公式）；6 个 skill 就是每个约 24 条正例，12 个 skill 就是每个约 12 条。每条 3 次重复按“查询”聚类，不能当 3 倍样本。
- 反例同样要够：false-load rate 很低时用 rule of three 表述更诚实（例如 120 条反例零误加载 → 误加载率 95% 上界约 2.5%）。
- near-miss 反例对 6 个 skill 的小库最有信息量：对每一对语义相邻的 skill，写“该 A 不该 B”和“该 B 不该 A”的查询各若干条，这同时充当 confusable pair 测试。

**两个测量场景要分开报告**
1. 离线路由测试（Tier A）：单轮查询 → 只看第一步是否 `load_skill` 及加载哪个，结果明确即终止，便宜，可跑上百条 × 3 次。
2. 端到端遥测（Tier B）：在多轮 case 里为“应加载的 skill 及最迟轮次”做标注，从 transcript 里统计 hit / miss / 误加载 / 时机。这里的 hit rate 才是用户实际感受到的，但样本少（每个 skill 在 150 个 case 里可能只出现十几次），CI 宽，适合与离线结果互相印证而不是单独下结论。

**成本不对称的量化口径**
- 误加载成本 ≈ skill 正文 token 数 ×（一次 cache write 倍率 + 剩余轮数 × cache read 倍率）+ 一次额外模型轮次的延迟。
- 漏加载成本 ≈ P(任务失败 | 漏加载) − P(任务失败 | 加载)，这个差只能靠消融量出来。
- 三臂消融比两臂更能说明问题：A 原始整块 system prompt；B 迁入 skill（现状）；C 把 skill 内容整个去掉。如果 A≈B≈C，说明当前 eval 根本测不到这 13% 内容的作用（Vercel 的“默认 skill = 基线”就是这种情形），此时谈 hit rate 没有意义，应先补能区分 C 的 case。

### Gaps
- Anthropic 没有给出“每个 skill 至少多少条查询才统计上稳定”的说法；“约 20 条 / 3 次 / 0.5 阈值”在其文档里都被称为合理的起点，而非统计结论。上表的样本量结论是本笔记的计算。
- 没有找到公开的、带 CI 的 skill 级 precision / recall 报告可作对标；现有公开测量（Vercel、Scott Spence）都只报整体激活率，且样本很小。
- “加载时机”的指标没有找到现成定义，上面的定义是本笔记提出的。
- `claude plugin eval` 的 grader 细节来自 Claude Code 文档的一段说明，未读其专门页面。

## 6. Demo 需要多大的 skill 库

### Takeaway
没有文献给出“demo 该有多少 skill”的数字；能用证据支撑的是测量设计而不是某个库规模：保持真实 skill 的查询集不变，用 distractor skill 把库规模翻倍到跨过 Anthropic 文档给的 30–50 退化起点（例如 6 → 12 → 24 → 48），并把 distractor 分成“无关”和“语义相邻”两种。按 2026 年的证据，强模型在这个规模上的曲线很可能是平的——那本身就是一个可以如实报告的结果。

### Cited Findings
- 加 distractor 模拟规模是 2026 顶会 benchmark 的标准做法：MCP-Bench 给每个任务附 10 个 distractor server（100+ 额外工具）。【2026 顶会·已核实：ICLR 2026】— [arXiv 2508.20453](https://arxiv.org/html/2508.20453)
- DynamicMCPBench 的 distractor 设计是“一半同名、一半近似”，并扫描“替代项占比”从 0 到 1（350 个任务的分层子集），结果准确率始终在置信区间内、没有诱发混淆；作者同时声明受控池的结论不能外推到开放检索。【2026 顶会·自述未独立核实：EMNLP 2026】— [arXiv 2607.20531](https://arxiv.org/html/2607.20531)
- 三种挂载规模对比（Oracle / Standard 220+ / Max-Scale 550+）是 MCPVerse 的做法，Claude-4-Sonnet 为 62.3 / 62.4 / 44.2。【背景·≤2025】— [arXiv 2508.16260](https://arxiv.org/html/2508.16260v2)
- 预印本的 skill 规模网格是 {5, 10, 20, 35, 50, 75, 100, 150, 200}，每个条件 3 个随机种子；≤20 时 >95%，50–100 陡降；竞争项实验在 |S|=20 就能看到 18–30% 的下降。【arXiv 预印本·未核实 venue】— [arXiv 2601.04748](https://arxiv.org/html/2601.04748v1)
- Anthropic 文档：工具超过 30–50 个后选择准确率下降；少于 10 个不需要 tool search。— [Tool search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- 每个 skill 的 metadata 约 100 tokens 常驻；description 上限 1,024 字符。— [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- commerce agents 参考实现的规模：购物 agent 5 个 skill（search-discovery、purchase-research、planning-goals、customer-care、memory-personalization）；商家 agent 的 skill 按运营域划分（抓取摘要的表述是 five per operational domain，具体含义未逐句核对原文）。【Anthropic 官方；由抓取摘要转述】— [The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- 小库下的未触发问题是真实存在的：1 个 skill 时 56% 未调用（Vercel）；4 个 skill 时约一半未激活（Scott Spence）。【行业博客 / 社区博客】— [Vercel](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)；[Scott Spence](https://scottspence.com/posts/measuring-claude-code-skill-activation-with-sandboxed-evals)

### Inferences
（全部是推断与建议。）
- **“6 个 skill 路由太容易”这句话要拆开**：对“选错”是对的（≤20 时公开数据都接近满分）；对“不触发”不一定对（1–4 个 skill 时公开测量有一半左右不触发）。所以 6 个 skill 的现状已经可以量一个有意义的数：触发召回与误加载率（第 5 节）。扩库只是为了回答第二个问题——选择精度随规模怎么变。
- **规模网格的取法**：取倍增网格 6 → 12 → 24 → 48。理由：(a) 起点是真实库；(b) 终点 48 落在 Anthropic 文档的“30–50 之后退化”和预印本“50 之后陡降”的交界，能同时覆盖平台区和可能的拐点；(c) 再往上（100+）需要编造上百个 skill，与 demo 定位不符，且该区间的结论已有论文可引，不必自己重测；(d) 48 个 skill 的 metadata 约 4.8k tokens（按每个约 100 tokens 估），这个数字本身就是“规模的代价”，可与迁出 system prompt 省下的 token 直接对比。
- **distractor 分两种，分开报**：
  - 无关型（其他领域，如发票、健身、代码审查）：测“数量”效应，预期对强模型几乎无影响。
  - 相邻型（旅行域内与真实 skill 语义接近但职责不同，例如真实 skill 管“改签规则”，distractor 管“退票规则”）：测“相似度”效应。预印本显示这类在 20 个规模就能造成两位数下降，是小库里最可能测出非平凡曲线的条件。
  - 每个真实 skill 配 1–2 个相邻 distractor 即可（6 个真实 skill → 6–12 个相邻 distractor），其余用无关型补齐到 24 / 48。相邻 distractor 的 description 要人工审一遍，避免写成与真实 skill 实质重复（那测的是标注歧义而不是路由）。
- **查询集保持不变，做配对比较**：同一批正例/反例查询在每个库规模下各跑 3 次，规模间的差异用第 1 节的配对公式判断。若正例共 120 条、规模间不一致率 0.15，MDE 约 9.8 点（表 1-D）；也就是说这套 demo 只能检出“掉了约 10 点以上”的退化，更小的变化要如实说“在误差内”。
- **诚实报告的写法**：
  1. 真实库（6 个）的 hit rate / false-load rate 与“加 distractor 的压力测试曲线”分两张表，不合并成一个数。
  2. 标明 distractor 是合成的、任何任务都不需要它们、数量和类型各是多少。
  3. 标明模型与版本、日期、每点的查询数与重复次数、CI。
  4. 不外推到 100+；引用 DynamicMCPBench 的提醒：受控 distractor 池不等于开放检索。
  5. 如果曲线是平的，就写“在 ≤48 个 skill、该模型下，选择不是瓶颈，主要损失来自未触发”，并指出这与 DynamicMCPBench、MCP-Bench 对强模型的观察一致；不要为了得到一条下降曲线而刻意把 distractor 写成与真实 skill 重复。
- **比“造更多 skill”更有说服力的替代**：把一部分 distractor 换成确实合理的旅行域候选 skill（即使暂未实现正文，只有 description），这样 12–16 的那个点代表“这个产品真长大后可能的库”，比纯合成更贴近面试官关心的问题。

### Gaps
- 没有任何来源直接回答“demo 级 skill 库多大才够”；网格 6/12/24/48 是本笔记基于已发表阈值的推断。
- 没有 2026 年强模型在 10–50 个 **skill**（而非 tool）规模上的受控公开曲线；唯一的 skill 曲线来自 GPT-4o / GPT-4o-mini 的预印本。
- 相邻型 distractor 对当前模型是否仍有两位数影响存在相互矛盾的证据（预印本 vs DynamicMCPBench），只能实测。

## 7. “system prompt 规则迁入 skills”重构的记账口径

### Takeaway
只报“静态 prompt 少了 13%”是不完整的：在 prompt caching 下，被缓存的静态前缀按 0.1 倍（部分新模型更低）计费，省下的钱远小于 13%；而 skill 一旦加载会留在对话里、还要多花一次模型轮次。应同时报告每轮平均输入 token（含已加载 skill）、缓存命中率、按价格加权的成本、延迟，以及任务成功率的 non-inferiority（配对，10 点界限约需 62–124 个 case）。

### Cited Findings
- 缓存相关的 usage 字段：`cache_creation_input_tokens`（写入缓存）、`cache_read_input_tokens`（从缓存读取）、`input_tokens`（最后一个断点之后、既未读也未写缓存的部分）；`总输入 = cache_read + cache_creation + input`。【Anthropic 官方文档】— [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- 价格倍率（相对基础输入价）：5 分钟缓存写入 1.25 倍，1 小时写入 2 倍；缓存读取标准为 0.1 倍，部分新模型更低（文档列出 0.025 倍与 0.05 倍的型号）。默认 TTL 5 分钟，命中即免费刷新。— [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- 缓存前缀按 tools → system → messages 的顺序构建，某一层变化会使该层及其后各层失效；改工具定义会使整个缓存失效。只追加 tool result 时缓存保持有效。最小可缓存长度因模型而异（512 / 1,024 / 2,048 / 4,096 tokens 四档），不足时不报错但不缓存，两个缓存字段都为 0 即说明没缓存上。— [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- 延迟加载的工具不进入初始 prompt，因此不破坏 prompt caching。【Anthropic 官方，2025-11-24】— [Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)
- skill 的三部分 token 成本：metadata 每个约 100 tokens 常驻；正文触发时进入上下文（建议 <5k tokens）；附带文件读取时才计。— [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- skill 正文加载后跨轮次保留，是重复出现的 token 成本；再次调用内容相同的 skill 时只加一条“已加载”的短提示而不重复正文（Claude Code 的行为）。— [Claude Code: Skills](https://code.claude.com/docs/en/skills)
- commerce agents 一文：加载 skill 花一次模型轮次；skill 以 tool result 加载可随对话前缀缓存；与约三分之一及以上流量相关的内容应留在 system prompt；若某 skill 可由信号（如来源页面）预判，harness 可在首次模型调用前直接注入。建议跟踪的指标包括任务完成、p50 / p99 延迟与成本预算、缓存命中率、每轮成本、每个完成任务的成本。【Anthropic 官方，2026-09-02；由抓取摘要转述】— [The anatomy of effective commerce agents](https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents)
- Anthropic 建议除准确率外同时收集：单次工具调用与任务的总耗时、工具调用总次数、总 token 消耗、工具错误。【Anthropic 官方，2025-09-11】— [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- eval 指南示例中跟踪的指标有 n_turns、n_toolcalls、n_total_tokens、time_to_first_token、output_tokens_per_sec，并建议在一组固定任务上跟踪延迟、token 用量、单任务成本和错误率。【Anthropic 官方，2026-01-09】— [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- skill-creator 的 benchmark 口径：有 skill / 无 skill（或新版 / 旧版）两种配置下的 pass rate、耗时、token，报均值 ± 标准差与差值。— [skill-creator/SKILL.md](https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md)
- 把内容从常驻上下文搬到按需加载的风险有公开反例：Vercel 的默认 skill 配置通过率与无文档基线相同（53%），常驻的 8KB 压缩索引（由约 40KB 压缩而来，减少 80%）达到 100%。【行业博客，2026-01-27】— [AGENTS.md outperforms skills in our agent evals](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)
- SkillsBench 的成对设计（同一任务有 / 无 skill）是 2026 顶会里衡量 skill 净效果的标准做法；聚焦型（不超过三个模块）优于大而全。【2026 顶会·已核实：NeurIPS 2026 poster 页】— [neurips.cc poster 139353](https://neurips.cc/virtual/2026/poster/139353)
- HAL 披露了总评测成本（约 4 万美元 / 21,730 次 rollout），并发现提高 reasoning effort 在多数运行中反而降低准确率——成本与准确率需要一起看。【2026 顶会·已核实：ICLR 2026】— [HAL, ICLR 2026 proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/a0928f924a344aaebbb7f6cd8d56e34c-Abstract-Conference.html)

### Inferences
（推断与建议；“13%”“6 个 skill”是任务给定背景。）

**建议的记账表（before = 整块 system prompt；after = skills）**

| 指标 | 怎么算 | 为什么要报 |
|---|---|---|
| 静态 system prompt tokens | 两版各自计数 | 已有的 13% |
| 新增常驻开销 | skill 列表（每个约 100 tokens 量级）+ `load_skill` 工具定义 | 13% 是毛减少，这是抵扣项 |
| 每对话加载的 skill tokens | Σ_s tokens(s) × P(加载 s)，并乘以加载后剩余轮数 | 正文加载后每轮都在 |
| 每轮平均输入 tokens | (cache_read + cache_creation + input) / 轮数，按对话长度分桶 | 真实上下文占用 |
| 缓存命中率 | cache_read / (cache_read + cache_creation + input) | 重构是否破坏前缀稳定性 |
| 价格加权输入成本 | input×1 + cache_creation×1.25 + cache_read×0.1（按实际模型倍率） | 钱 |
| 模型调用次数 / 每用户轮 | transcript 计数 | 每次 `load_skill` 多一次往返 |
| 延迟 | 每用户轮 p50 / p95，首 token 时间 | 用户感知 |
| 每个完成任务的成本 | 总成本 / 通过的 case 数 | 把质量和成本合到一个数 |
| 任务成功率（配对） | 同一批 case、同样 K，逐 case 差 + CI | non-inferiority |
| skill hit / miss / 误加载 | 第 5 节 | 解释成功率差异的来源 |

- **为什么 13% 会高估收益**：静态前缀在缓存命中的轮次里本来就只按 0.1 倍（部分模型更低）计费，所以被迁走的那 13% token 在这些轮次里省下的钱只有其名义价格的一折；而每加载一次 skill，正文要先付一次 1.25 倍的缓存写入，之后每轮再付 0.1 倍的读取，外加一次额外的模型往返。重构的主要收益更可能是上下文更干净、规则更模块化、改一条规则只需回归相邻 case（commerce agents 一文的回归规则），而不是省钱——这一点如实说比报一个 13% 更站得住。
- **缓存结构检查**：skill 正文若通过 tool result 进入 messages，则 tools 与 system 两层前缀不变，缓存不受影响（与 Anthropic 建议一致）；若实现成“动态改写 system prompt 注入 skill”，会使 system 及其后的缓存全部失效。记账时用“加载 skill 的那一轮及其后一轮的 cache_read 占比”就能验证是哪种情况。还要确认静态前缀长度超过所用模型的最小可缓存长度，否则两版都没缓存，比较失真。
- **non-inferiority 的样本量**（单侧 α=0.05，power=0.8，假设两版真实无差异；`n = (z_{0.95}+z_{0.80})²·P_D/Δ²`，由 Miller 的 power 公式改成单侧并把 δ 换成界限 Δ 得到）：

| 不一致率 P_D | 界限 Δ=10 点 | 界限 Δ=5 点 |
|---|---|---|
| 0.05 | 31 | 124 |
| 0.10 | 62 | 248 |
| 0.15 | 93 | 371 |
| 0.20 | 124 | 495 |

  即：用 100–150 个端到端 case 可以支持“迁移后成功率不比迁移前低 10 点以上”的结论；“不低 5 点以上”需要 250–500 条，只能在便宜的 Tier A 上做。现有 30 个 case 不足以支持 10 点界限的 non-inferiority 结论（即使 P_D 低到 0.05 也需要 31 条）。
- **哪些规则适合迁**：按 commerce agents 一文的两条判据——与约三分之一以上流量相关的留在 system prompt；安全 / 合规 / 必须每次成立的留在 system prompt 并由服务端强制——可以对已迁出的 6 个 skill 逐个核对触发流量占比，占比高的 skill 迁出去反而多花轮次。这个“每个 skill 的触发流量占比”本身就是值得报的一个数。
- **面试口径**：把这次重构讲成“在成功率 non-inferior（界限 X 点、N 个配对 case、CI 为…）的前提下，静态 prompt 减少 13%，每轮平均输入 token 变化 Y，缓存命中率从 A 到 B，hit rate 为 H（CI…）”，比单报 13% 完整，也正面回应了“skill 可能不触发”的质疑。

### Gaps
- 没有找到公开的、针对“把 system prompt 规则迁入 skill”这一重构的前后对比数据（Vercel 的实验方向相反：把 skill 内容搬回常驻上下文）。
- 加载 skill 的延迟开销没有可靠的公开数字；Scott Spence 文中的延迟差是 hook 造成的，不是 skill 加载本身，不能套用。
- 项目所用模型的缓存读取倍率和最小可缓存长度需按实际型号查文档确认；上表按标准 0.1 倍 / 1.25 倍举例。
- commerce agents 一文中“三分之一流量”的判据来自抓取摘要的转述，未逐句核对原文措辞。
