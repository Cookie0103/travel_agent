# 第一阶段归档（2026-10-02 ～ 2026-11-26）

这里是第一阶段的全部过程材料：把旅行 Agent 从零做到可运行、可评测，再到为第二阶段做的调研。**只读**：以后只迁入、不改写；要更正就在新阶段的文档里写更正说明。

现在在做的事情不在这里，见 [docs/README](../../docs/README.md)。

## 这里有什么

| 目录 | 内容 | 想找什么时来这里 |
| --- | --- | --- |
| [docs/plans/](docs/plans/) | 25 份批次计划（任务表、每日进展、问题解决记录）和[问题索引](docs/plans/problems.md) | 某个功能当时怎么做的、踩过什么坑、P-编号对应的问题 |
| [docs/evidence/](docs/evidence/README.md) | 242 份脱敏证据（JSON、截图、乐天原始响应样本） | 某个结论的原始数据 |
| [docs/operations/](docs/operations/README.md) | 操作手册与命令原始过程 | 当时怎么部署、怎么跑评测 |
| [docs/review/](docs/review/README.md) | 面试案例、审计报告、架构复盘、项目讲解稿 | 准备面试、回顾设计取舍 |
| [docs/proposals/](docs/proposals/) | Product V2 方案、规划修复论文调研、v3 评测重设计与结果 | v3 评测为什么这么设计、30 题的结果 |
| [docs/tasks/](docs/tasks/) | M0–M4 里程碑规格 | 最初的验收标准 |
| [docs/protocols/](docs/protocols/) | Agent SDK 与 DeepSeek 的协议实测 | SDK 行为、兼容性结论 |
| [docs/archive/](docs/archive/README.md) | 2026-10-08 之前更早的归档（M0 日志、旧执行计划） | 最早期的历史 |
| [docs/README.md](docs/README.md) | 第一阶段的文档总入口（当时的导航页） | 按当时的目录找东西 |
| [research/sdk/](research/sdk/README.md) | Agent SDK 选型实测：五个框架在同一模型、同一工具下的对比（代码 + 结果） | 为什么选 Claude Agent SDK |
| [research/judge-scoring-notes/](research/judge-scoring-notes/) | 第二阶段方案的 9 篇调研笔记（约 60 万字节） | 第二阶段每个设计决定的论文与数据依据 |

调研笔记逐篇：

| 文件 | 主题 |
| --- | --- |
| [00](research/judge-scoring-notes/00_codebase_inventory.md) | 代码库盘点：41 条现有校验、酒店报价字段、v3 评测、6 个 Skill、系统提示词逐段分类 |
| [01](research/judge-scoring-notes/01_rule_verification.md) | 规则校验：约 60 篇实践文章归纳出的规则清单与依据 |
| [02](research/judge-scoring-notes/02_ota_ranking_economics.md) | 在线旅行平台的排序与佣金经济学 |
| [03](research/judge-scoring-notes/03_scoring_models.md) | 打分模型：选择模型、Jev 等只输出概率的决策模型 |
| [04](research/judge-scoring-notes/04_self_evolution.md) | 自进化：GEPA、ACE、SkillsBench 等方法谱系与防过拟合 |
| [05](research/judge-scoring-notes/05_eval_size_skill_routing.md) | 评测集规模的统计学与 Skill 路由测量 |
| [06](research/judge-scoring-notes/06_choice_model_fitting.md) | 选择模型拟合：Expedia 数据事实、可借用的已发表系数 |
| [07](research/judge-scoring-notes/07_small_eval_power.md) | 小评测集的统计功效与反复复用的过拟合 |
| [08](research/judge-scoring-notes/08_skill_governance.md) | Skill 该不该预先设计、企业怎么治理会增长的指令库 |

## 没有归档、仍在用的

第一阶段沉淀下来的规则和系统说明两个阶段都要用，留在 [docs/handbook/](../../docs/handbook/README.md)：工作流、工程标准、记录规则、长期方法约定、产品设计 01–07、全部 ADR、测试总览、安全与可靠性不变量。

## 旧路径对照

归档文档里的**链接**已经全部改到新位置，可以直接点。正文里以纯文字出现的旧路径和旧命令没有改（历史记录不改写），按下表换算；逐文件的完整对照在 [path-map.json](path-map.json)。

| 以前（2026-11-27 之前） | 现在 |
| --- | --- |
| `docs/plans/<批次>.md`、`docs/plans/problems.md` | `archive/phase1/docs/plans/` |
| `docs/plans/README.md`（记录规则） | `docs/handbook/recording.md` |
| `docs/evidence`、`operations`、`review`、`proposals`、`tasks`、`protocols`、`archive` | `archive/phase1/docs/<同名>` |
| `docs/design`、`adr`、`execution`、`guides`、`testing`、`DESIGN.md`、`RELIABILITY.md`、`SECURITY.md` | `docs/handbook/<同名>` |
| `research/` | `archive/phase1/research/` |
| `research_notes/旅行 Agent 评判打分落地方案/` | `archive/phase1/research/judge-scoring-notes/` |
| `eval/<模块>.py`，例如 `eval/v3_run.py`、`eval/run.py` | `eval/<子包>/…`，例如 `eval/v3/run.py`、`eval/v1v2/run.py`，见 [eval/README](../../eval/README.md) |
| `python -m eval.run`、`python -m eval.v3_judge` | `python -m eval.v1v2.run`、`python -m eval.v3.judge` |
| `tests/test_<名>.py` | `tests/unit/<层>/test_<名>.py`，见 [tests/README](../../tests/README.md) |
| `tests/integration/test_<名>.py` | `tests/integration/<领域>/test_<名>.py` |
| `tests/fakes.py`、`runner.py`、`cli.py`、`errors.py`、`model_bodies.py` | `tests/support/` |
| `scripts/<名>.py`（`dev.py` 除外） | `scripts/devtools/`、`scripts/demo/`、`scripts/live/`，见 [scripts/README](../../scripts/README.md) |
| `python -m scripts.smoke_demo` | `python -m scripts.demo.smoke_demo` |

`research/sdk/` 里的 `.venv` 和 `node_modules` 是本机生成物，不进 Git；要重跑那组实验，先在该目录执行 `uv sync` 和 `npm install`。
