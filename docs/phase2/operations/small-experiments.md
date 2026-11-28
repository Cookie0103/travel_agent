# D9 小样本的复核入口

D5、F2 与 F4 使用隔离 PostgreSQL 和合成供应商世界。模型线路选 DeepSeek Flash，默认关闭付费 rubric，使用 `human` 配置。完整日志、对话、账本和账户查询响应留在本机缓存。真实乐天快照只供离线回放。

## 复核基线与两版实验

1. D5 从冻结的反思和验证子集各取 12 题，共 24 道，11 个类别。运行入口为 `uv run python scripts/dev.py eval-v3 --live --no-judge --split all --repeat 1`，附逐题的 `--case-id` 和当时的账本剩余额度。固定题号在本机 `.cache/phase2/d5-small-case-ids.json`。原始输出目录为 `.cache/eval-v3/20261128T023011Z-2ffe72/`。
2. 第一版通过 `eval.evolve.round.first_round` 生成候选和审核页。复测使用 `eval-v3 --split reflection --candidate-skills <候选目录>` 及 D5 同一批反思题。运行引用在 `.cache/phase2/f2-small/`，原始反思记录留在各次运行的 `transcripts/`。
3. 第二版通过 `eval.evolve.guarded.evaluate_candidate` 生成候选。复测使用 `eval-v3 --split validation --candidate-skills <候选目录>`，沿用 D5 固定验证子集。结果引用在 `.cache/phase2/f4-small/`，候选审核页与配对结果保存在候选目录。两版当时的被测代码与内置 Skill 均与 `4a432d0` 一致。
4. 两次终点仅使用同一批六道留出题。按固定盐值 `D9-20261128` 和题号的 SHA-256 排序，按不同类别各取第一条。冻结分区的题目内容未传给反思器，本页保留抽样方法和汇总入口。

本机软项使用 `eval.commerce.soft_replay` 和 C5 固定模型版本。命令输入为已保存的 `trials.jsonl`，采用 C4 冻结的 `eval/commerce/parameters-rakuten-v1.json`，输出新的 `trials-with-soft.jsonl`。缺少可核对推荐证据的试验保留原硬分。

以上命令可从保存结果复核。重新发起模型批次前，先核对阶段账本和原有预算约束。[基线报告](../evidence/small-baseline-v1.md) · [两版对照](../evidence/evolution-comparison-small-v1.md)
