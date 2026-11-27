# 规则/符号化校验 LLM 生成行程，以及自然语言需求如何编译成可机检约束

> 检索日期：2026-11-26。标注约定：
> - 【已开页】= 本次直接打开了会议/Anthology/PMLR/官方页并看到 venue 信息。
> - 【搜索条目】= 搜索结果里出现了官方 proceedings/virtual 页面条目且标题一致，但没有单独打开该页。
> - 【arXiv 注记】= 仅 arXiv comments 或 HTML 页眉自述 venue，未在出版方页面复核。
> - 【仅 arXiv】= 未找到任何录用信息，只能当背景/未验证。
> - 【二手】= 数字来自他人综述/博客转述，未回到原文核对。
> - 模型名（GPT-5.2、Gemini-3-Pro 等）均按来源原样转录，未另行核实。
> - 多数论文正文是经 WebFetch 的小模型摘要读取的，表格数字建议在引用前回原文复核；已知不一致处都单独标出。

---

## 1. 旅行规划 benchmark 用了哪些 hard / commonsense 约束分类？每条在代码里怎么查？指标怎么算？

### Takeaway
各 benchmark 的共同骨架是三层：**环境/常识可行性（实体存在、时间、空间、不重复、信息完整）→ 用户显式硬约束（预算、类型、必去/排除）→ 偏好/质量（连续分）**，并用 micro（按约束条数）/ macro（按整份计划全过）/ final pass 三类口径报告；2026 的新作（TRIP-Bench、TREK、Trip+、TravelEval、VeriTrip）在此之上加了"多轮修订""不可行请求""隐含人群需求""天气暴露""逐格事实核对"。
代码级最值得移植的两套是 TravelPlanner（8 常识 + 5 硬约束，`None` = 不适用）和 ChinaTravel（8 个检查函数 27 个列 + Python 风格 DSL 表达用户逻辑约束）。

### Cited Findings

#### 1.0 venue 核实台账（benchmark 部分）

| 工作 | venue | 核实方式 |
|---|---|---|
| TravelPlanner | ICML 2024（任务书给定；本次未在 PMLR 复核） | 论文 [arXiv 2402.01622](https://arxiv.org/pdf/2402.01622)；评测脚本直接读取 GitHub raw 文件 |
| ChinaTravel | ICLR 2026 | 【搜索条目】[proceedings.iclr.cc](https://proceedings.iclr.cc/paper_files/paper/2026/hash/9b01c4a7d3fc49875dad3c13848bcd9e-Abstract-Conference.html)、[iclr.cc poster](https://iclr.cc/virtual/2026/poster/10011926)；【已开页】[GitHub README 标题带 ICLR'26，BibTeX 写第 14 届 ICLR](https://github.com/LAMDASZ-ML/ChinaTravel) |
| TripCraft | ACL 2025 long | 【搜索条目】[ACL Anthology 2025.acl-long.834](https://aclanthology.org/2025.acl-long.834)（pp. 17035–17064）；正文读的是 [arXiv HTML](https://arxiv.org/html/2502.20508) |
| TripTailor | ACL 2025 Findings | 【arXiv 注记】搜索摘要称 arXiv 列表写明 accepted to ACL 2025 Findings，未找到 Anthology 条目；[arXiv 2508.01432](https://arxiv.org/html/2508.01432v1) |
| TP-RAG | EMNLP 2025 main | 【搜索条目】[ACL Anthology 2025.emnlp-main.626](https://aclanthology.org/2025.emnlp-main.626)；页码两处来源不一致（12403–12429 vs 12392–12418），引用前需核对 |
| TravelBench（"Beyond Itinerary Planning"） | ACL 2026 long（Volume 1） | 【已开页】[ACL Anthology 2026.acl-long.1347](https://aclanthology.org/2026.acl-long.1347/)，pp. 29200–29251，San Diego，2026-07 |
| TRIP-Bench | ICML 2026 | 【已开页】[PMLR v306](https://proceedings.mlr.press/v306/shen26j.html)，Proceedings of the 43rd ICML，PMLR 306:110995–111034；另有 [icml.cc poster](https://icml.cc/virtual/2026/poster/62985) |
| TripTide | Findings of ACL 2026 | 【搜索条目】[ACL Anthology 2026.findings-acl.2002](https://aclanthology.org/2026.findings-acl.2002/)，pp. 40269–40292；正文读的是 [arXiv v1](https://arxiv.org/html/2510.21329v1) |
| VeriTrip | NeurIPS 2026 poster | 【搜索条目】[neurips.cc poster 139167](https://neurips.cc/virtual/2026/poster/139167)；正文读的是 [arXiv HTML](https://arxiv.org/html/2605.28683)（该页本身未写 venue） |
| iTIMO | SIGIR 2026 | 【arXiv 注记】[arXiv HTML 页眉](https://arxiv.org/html/2601.10609)自述 SIGIR '26（Melbourne，2026-07-20~24），未在 ACM DL 复核 |
| TravelEval | KDD 2026（**部分验证**） | [ACM DL DOI PDF](https://dl.acm.org/doi/pdf/10.1145/3770855.3817533) 返回 403 打不开；搜索索引摘要称其为第 32 届 SIGKDD（2026-08，济州）论文；[arXiv 版](https://arxiv.org/html/2606.01046)只有占位 DOI；TREK 论文把它引作 KDD 2026（二手） |
| TREK | 【仅 arXiv】页眉 "Preprint. Under review" | [arXiv 2607.26977](https://arxiv.org/html/2607.26977) |
| Trip+ | 【仅 arXiv】 | [arXiv 2606.21169](https://arxiv.org/html/2606.21169) |
| Flex-TravelPlanner | 【仅 arXiv】venue 未核实 | [arXiv 2506.04649](https://arxiv.org/abs/2506.04649) |

#### 1.1 TravelPlanner（谱系起点）

常识约束（`commonsense_constraint.py::evaluation` 返回 8 个键，每个值是 `(bool, message)`）— [源码](https://raw.githubusercontent.com/OSU-NLP-Group/TravelPlanner/main/evaluation/commonsense_constraint.py)：

| 键 | 代码逻辑 |
|---|---|
| `is_reasonable_visiting_city` | 首日出发城市必须等于 `org`；城市序列首尾相同（闭环）；`is_valid_city_sequence`：长度 ≥3、同一城市只能连续出现、中间城市不能只出现 1 天；城市须在 `city_state_map` 内；`days > 3` 时中间城市所属州必须等于 `dest` |
| `is_valid_restaurants` | 全程 `breakfast/lunch/dinner` 的餐厅名不得重复（空或 `-` 跳过） |
| `is_valid_attractions` | `attraction` 字段按 `;` 切分，全程不得重复 |
| `is_valid_accommodation` | 每天必须有 `accommodation` 键；把连续相同住宿合并成段，段长 < 该房源 `minimum nights` 即失败 |
| `is_valid_transportation` | 第 1 天交通不能为空；全程不能同时出现 Self-driving 与 Flight，或 Taxi 与 Self-driving |
| `is_valid_information_in_current_city` | 交通字符串须包含当天所有城市；三餐/景点须包含当天某个城市；住宿须包含当天最后一个城市（子串匹配） |
| `is_valid_information_in_sandbox` | 航班号+起讫城市须在 flight 表命中；自驾/出租调距离矩阵，`cost is None` 即失败；餐厅/景点/住宿按"名称+城市"在对应表命中 |
| `is_not_absent` | 天数等于 `days`、访问城市数等于 `visiting_city_number`；每天 6 个键都存在；跨城日必须有交通、非跨城日必须有景点、非末日必须有住宿、非出发日三餐不能缺；有效信息量 / (6×days) < 0.5 即失败 |

硬约束（`hard_constraint.py::evaluation` 返回 5 个键；查询没提该约束时返回 `(None, None)` 表示不适用，`valid_cost` 永远是布尔）— [源码](https://raw.githubusercontent.com/OSU-NLP-Group/TravelPlanner/main/evaluation/hard_constraint.py)：

| 键 | 代码逻辑 |
|---|---|
| `valid_cuisine` | 汇总全程餐厅的 `Cuisines`，要求覆盖用户列出的每一种菜系（出发城市的餐厅不计） |
| `valid_room_rule` | 查住宿 `house_rules` 文本里是否有 No smoking / No parties / No children under 10 / No visitors / No pets |
| `valid_transportation` | `no flight` → 任一天交通含 "Flight" 即失败；`no self-driving` 同理 |
| `valid_room_type` | 房型字段与 shared / not shared / private / entire 的精确匹配 |
| `valid_cost` | `get_total_cost`：航班价 × 人数；自驾 cost × ceil(人数/5)；出租 cost × ceil(人数/4)；餐厅 Average Cost × 人数；住宿 price × ceil(人数/maximum occupancy)；总和 ≤ budget |

指标（`eval.py`）— [源码](https://raw.githubusercontent.com/OSU-NLP-Group/TravelPlanner/main/evaluation/eval.py)：
- **Delivery Rate**：`plan` 非空的条数 / 固定分母（train 45 / validation 180 / test 1000）。
- **门控**：只有 `is_not_absent` 和 `is_valid_information_in_sandbox` 都为真才跑硬约束，否则 `hard_info_box = None`（硬约束整体不计分）。
- **Commonsense Micro**：所有常识检查中 `True` 的个数 / 硬编码分母 360 / 1440 / 8000。**Macro**：没有任何"非 None 且为假"的检查，才算该计划通过。
- **Hard Micro**：`True` 个数 / 硬编码分母 105 / 420 / 2290；`None` 既不计入 True 也不计入 False。**Macro**：没有任何等于 False 的硬约束。
- **Final Pass Rate**：常识 macro 与硬约束 macro 同时通过。
- 计划先由 GPT-4-Turbo 把自由文本转成 JSON 再交给脚本，评测并非完全无解析器 — 【二手】[Stanford 综述博客](https://web.stanford.edu/~shuhuiq/blog/review-checking-agents.html)。
- 二手描述：13 条约束 = 8 常识 + 5 硬；test 集约束与预算不公开，需盲提交 — [HiMAP-Travel](https://arxiv.org/html/2603.04750)。

#### 1.2 ChinaTravel（ICLR 2026）

环境约束（README 分类，共 4+3+5+6+4+2+1 = 25 条）— [symbol_verification/readme.md](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/symbol_verification/readme.md)：
- **Cross-city Transportation**：必须有跨城交通事件；车次/航班在沙盒可用；价格与时长与沙盒一致；给出票数与分项费用。
- **Inner-city Transportation**：地铁/出租/步行路线可用；价格、距离、时长与沙盒一致；给出票数或车数与分项费用（出租每车 4 人）。
- **Attractions**：存在于目标城市；游览落在开放时间内；价格一致；票数与费用；全程不重复。
- **Restaurants**：存在；营业时间内；价格一致；票数与费用；不重复；早/午/晚餐落在各自时间窗。
- **Accommodation**：存在；房价与房型一致；房间数与费用；多日行程必须有住宿。
- **Time**：每个活动有起止时间且止晚于起；按时间顺序，且晚于到达它的交通的到达时刻。
- **Space**：与上一事件位置不同则必须给出其间的交通路线。

代码实现（8 个函数，返回 0/1 列，当前仓库合计 27 列）— [symbol_verification/commonsense_constraint.py](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/symbol_verification/commonsense_constraint.py)：

| 函数 | 列（每列一条可独立计分的检查） | 关键阈值/实现细节 |
|---|---|---|
| `Is_activity_grounded` | 实体类型与字段合法 | 活动类型只能是 airplane/train/attraction/breakfast/lunch/dinner/accommodation；跨城活动只能是首日首项或末日末项且不得带 `position`；POI 活动必须带 `position` 且不得带 FlightID/TrainID |
| `Is_intercity_transport_correct` | 必须出现；ID/起讫非法；价格/时刻不符；费用不符 | 起止时刻须等于沙盒 BeginTime/EndTime；price 精确相等；`|price × tickets − cost| > 0.1` 判错 |
| `Is_attractions_correct` | 不存在；闭馆时游览；重复；价格不符；费用不符 | `open ≤ start` 且 `end ≤ close`；闭馆时刻 ≤ 开馆时刻则 +24h（跨夜）；价格按 `int()` 截断比较；费用容差 0.1 |
| `Is_hotels_correct` | 不存在；价格/房型不符；费用不符；多日必须有住宿 | 价格、房型精确相等；`|rooms × price − cost| > 0.1` |
| `Is_restaurants_correct` | 不存在；闭店时就餐；重复；价格不符；费用不符；用餐时间不当；同日同餐别重复 | 早餐 06:00–09:00、午餐 11:00–14:00、晚餐 17:00–20:00，按"与窗口有交集"判定（start ≥ 窗口止或 end ≤ 窗口起才判错）；酒店早餐价格须为 0 |
| `Is_transport_correct` | 市内交通不可用；价格/距离/时长不符；费用不符 | 三段必须是 walk→metro→walk，单段只能是 walk 或 taxi；与工具返回逐段比对，价格/距离容差 0.1；walk 费用必须为 0；taxi `|price × cars − cost| ≤ 0.1` |
| `Is_time_correct` | 起止时间缺失；时间顺序 | `start ≥ end` 判错（航班/火车除外）；同日后一活动不得早于前一活动结束；首段交通不得早于前一活动结束、活动不得早于末段交通到达；分钟级精确比较无容差 |
| `Is_space_correct` | 位置间交通信息非法 | 位置变化则 `transports[0].start == 上一位置` 且 `transports[-1].end == 当前位置`；位置未变却有交通也判错 |

- 聚合：macro = 全部列为 0 的样本占比；micro = 1 − 被标记的格子数 /（样本数 × 列数）；检查抛异常时记一列 `Commonsense Evaluator Exception = 1` — [evaluation/commonsense_constraint.py](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/evaluation/commonsense_constraint.py)。
- 论文正文称环境约束 25 条；README 也是 25 条；当前代码多出"同日同餐别重复"与 `Is_activity_grounded` 两列，合计 27 列（27 是我按抓取结果逐列数出来的，未见作者说明差异）— [arXiv v5](https://arxiv.org/html/2412.13682v5)、[代码](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/symbol_verification/commonsense_constraint.py)。

逻辑约束 DSL — [arXiv v5](https://arxiv.org/html/2412.13682v5)：
- 语法元素：变量、`not/and/or`、`< > ==`、`+ − * /`、属性函数（费用、类型、时间）、`dist(a, b)`、赋值、集合运算（并/交/差）、`for … in …` 枚举、`if …: …` 条件效果；Python 风格，用 Python 编译器查语法错误（缺冒号、未定义变量）。
- 数据里以 `hard_logic_py`（JSON 列表）存放；`hard_logic_nl` 是对应自然语言，只有 `--oracle_translation` 才暴露给 agent — [GitHub README](https://github.com/LAMDASZ-ML/ChinaTravel)。
- 约束类型：交通方式；景点类型或指定景点；餐厅类型或指定餐厅；住宿房间数/房型；酒店设施或指定酒店；总预算。人写查询里新出现的类型：POI 的否定/合取/析取；对特定活动的时长上限；对特定活动的预算上限。
- 预算示例的写法：遍历 `all_activities(plan)` 累加 `activity_cost` 与 `innercity_transport_cost`，再与上限比较。
- 作者指出 TravelPlanner 只有 5 个预定义概念，无法验证开放世界里的组合需求；人写集 78.4% 的 DSL 语句含语义化 POI，TravelPlanner 为 5.4%。
- 偏好（6 个，P0–P5）：每日景点数最大化、交通时间最小化、到餐厅的交通时间最小化、餐饮花费占比最大化、酒店花费最小化、到指定 POI 的距离最小化。

指标 — [arXiv v5](https://arxiv.org/html/2412.13682v5)：
- **DR**：是否交付了格式合法的计划。
- **EPR**：micro = 通过的（计划,环境约束）对 /（|P| × |Env|）；macro = 全过环境约束的计划占比。
- **LPR**：micro = 通过的逻辑约束数 / Σ|C_p|；macro = 自身逻辑约束全过的计划占比。
- **C-LPR**：只有环境约束全过的计划，其逻辑约束才计分（分母仍是 Σ|C_p|）。
- **FPR**：环境与逻辑约束全过的计划占比。
- 数据：Easy 300、Human-Val 154、Human-Test 1000；沙盒 10 城、720 航班、5,770 车次、3,413 景点、4,655 餐厅、4,124 酒店。
- 标注阶段，沙盒里无法验证的查询被直接剔除。
- 被选为 IJCAI 2025 与 IJCAI 2026 Travel Planning Challenge 的官方 benchmark — [GitHub README](https://github.com/LAMDASZ-ML/ChinaTravel)、[IJCAI 2026 赛事页](https://chinatravel-competition.github.io/IJCAI2026/)。

#### 1.3 TripCraft（ACL 2025）— [arXiv HTML](https://arxiv.org/html/2502.20508)
- 常识约束（相对 TravelPlanner 新增 3 条）：Within Sandbox、Complete Information、**Sufficient Meal Gaps（新增）**、**Valid PoI list（新增）**、**Diverse Events（新增）**、Within Current City、Reasonable City Route、Diverse Restaurants、Diverse Attractions、Non-conflicting Transportation。
- 硬约束：Budget、Room Rule、Room Type、Cuisine、Transportation、**Event Types（新增）**、**Attraction Types（新增）**；另有 persona（Traveler Type、Purpose、Spending Preference、Location Preference）与环境约束（交通不可用、景点不可用）。
- 阈值：两餐之间至少间隔 4 小时；景点游览时长取其类别的平均时长（15 个类别，如 Museums 3.0 h、Nature & Parks 4.5 h）；PoI 优先选 5 km 内有公交站的。
- 5 个连续指标：Temporal Meal Score（用餐中点时刻与时长的二元正态密度，归一到 0–1）；Temporal Attraction Score（时长高斯项 × 景点数泊松项，期望时长随人设与景点数平移，k = 0.28 h）；Spatial Score（距公交站 d ≤ 5 km 时 1 − 0.5·d/d₀，否则 0.5·exp(−λ(d − d₀))，λ = 0.0002）；Ordering Score（1 − 编辑距离 / max 长度，对比标注序列）；Persona Score（BERT 嵌入余弦相似度）。
- 沿用 Delivery Rate、Commonsense Pass Rate（micro/macro）、Hard Constraint Pass Rate（micro/macro）、Final Pass Rate；7 日行程不给参数信息时常识 micro 70.35、macro 0.00、final 0.00。

#### 1.4 TripTailor（ACL 2025 Findings）— [arXiv HTML](https://arxiv.org/html/2508.01432v1)
- 规模：40 城、50 万+ POI、近 4,000 条真实行程（训练 3,145 / 测试 703）。
- Feasibility（规则）：Within Sandbox、Complete Information；30 步内出不了合法结果或往返信息错也判不可行。
- Rationality（LLM 先抽取要素，再由脚本判）：Diverse Restaurants、Reasonable Meal Prices、Diverse Attractions、Appropriate Visit Duration（落在推荐区间）、Defined Budget Limit；Optimized Route（相邻 POI 平均距离）只报告不计入通过率。
- Personalization：LLM-as-a-Judge（两模型、交换位置取平均、1–5 分）+ 微调的 reward model；Final Surpassing Rate = 过可行与合理且被任一 judge 评为优于真实行程。
- 结果：GPT-4o final pass 21.5% / surpassing 7.5%；工作流基线 63.3% / 16.2%；LLM 行程相邻 POI 平均 17 km 以上，真实行程 7.3 km。

#### 1.5 TP-RAG（EMNLP 2025）— [arXiv HTML](https://arxiv.org/html/2504.08694)
- 2,348 条查询、85,575 个景点 POI、18,784 条参考轨迹；不标注唯一最优解。
- 规则指标：Failure Rate（POI 不在候选集）、Repetition Rate、Distance Margin Ratio（与 TSP 最优路程的差距）、Duration Underflow Ratio（计划时长是否达到 POI 期望时长）、Time Buffer Ratio（景点间空闲缓冲占比）。
- LLM-judge 指标：Start Time Rationality（到达时刻是否符合开放时间/推荐时段）、POI Relevance、Time Schedule Relevance；POI Popularity 用 LLM 生成的热度排序算召回。
- LLM judge 与人工一致率（100 份 GPT-4o 计划）：STR 93.70%、PR 95.54%、TSR 97.55%。

#### 1.6 TravelBench（ACL 2026）— [arXiv HTML](https://arxiv.org/html/2512.22673)、[Anthology](https://aclanthology.org/2026.acl-long.1347/)
- 1,100 例：Single-Turn 500、Multi-Turn 500（平均 2.51 个用户轮）、**Unsolvable 100**（原因：工具不支持、缺必要上下文、没有可执行意图；三个标注模型一致判不可解才收录）。
- 10 个工具、约 20 万条真实工具调用缓存。
- 评分：Unsolvable 用规则——首条回复含 `[Unsolved]` 标签即正确；Single/Multi-Turn 用 LLM judge 按维度打 1–5 分（单轮 3 维、多轮 4 维），再乘工具调用错误惩罚 (1 − 错误调用/总调用)；meta-judge 校准约 3% 的样本触发。
- 结果（惩罚后）：Qwen-Plus 82.64 / 62.56 / 83.67，总分 76.29；DeepSeek-V3.2 的 Unsolvable 只有 51.33；Kimi-K2 的 Unsolvable 94.00 但 Multi 49.99。
- 对比表：TravelPlanner、ChinaTravel、TripTailor、TP-RAG 均不含 multi-turn、unsolved、implicit preference 三项。

#### 1.7 TRIP-Bench（ICML 2026）— [PMLR](https://proceedings.mlr.press/v306/shen26j.html)、[arXiv HTML](https://arxiv.org/html/2602.01675)
- 18 个工具、40+ 类旅行需求；最长 15 个用户轮、150+ 次工具调用、上下文可超 200k tokens。
- 约束 rubric：景点（类别包含/排除、热度、评分、票价、距离、评论数、景区等级）；酒店（价格、档次、评论数、好评率、星级、退订政策、宠物、早餐份数、有窗、相对市中心位置）；餐厅（人均、评分、菜系包含/排除、是否需预约、分项评分）；交通（出发/返回时刻、交通预算、订票平台、准点率与最大延误、排除航司）。
- 每条 rubric 配一个生成器 G(e)（产出可行 ID 集合）和一个校验器 V(e, i)（检查单个 ID）。
- 12 条通用约束 = 4 条基本可行性 + 8 条规划合理性（逐条清单未抓到）。
- 指标：**Strict** = I(F_feas = 0 ∧ F_sound = 0 ∧ F_user = 0)；**Loose** = I(F_feas = 0 ∧ F_sound ≤ 2 ∧ F_user ≤ 1)；可行性违规是硬门，loose 也不放过。
- 多轮行为：最多 3 步逐步收紧的修改链；指令修改、删除/回滚、对模型输出的局部修订、报错；PMR 在两份相似行程间切换/回滚/合并；FIT 链在当前步不可行、回滚一步后可行。
- 结果（loose / strict）：GPT-5.2 thinking 45.0 / 18.5；Hard-FIT 18.0 / 0.0；easy split 最好不超过 50%。
- 论文没有描述"修订后未改动部分保持不变"的检查，也没有说明约束打分器是否经人工校验（人工校验只覆盖用户模拟器：104 轮 98% 一致）。

#### 1.8 TripTide（Findings of ACL 2026）— [arXiv v1](https://arxiv.org/html/2510.21329v1)、[Anthology](https://aclanthology.org/2026.findings-acl.2002/)
- 基于 TripCraft 1,000 条查询，11,058 个候选扰动；扰动类型：Transport、Accommodation、Restaurant、Attractions、Miscellaneous；严重度：Step / Day / Plan 级；旅客容忍度：Flexi-Venturer（接受变化）与 Plan-Bound（偏好最小改动，范围随严重度）。
- 指标：Preservation of Intent（修订后计划重跑 TravelPlanner 式 delivery / CPR / HCPR / final）；Responsiveness = 被缓解的计划 / 总数；Adaptability 三项——A_sem（修订前后 persona 相似度之差）、A_spa（修订前后空间得分之差）、A_seq（修订前后 PoI 序列的编辑距离 / 较长序列长度，按天平均），三项越低越好。
- GPT-4o（3/5/7 天）：final pass 29.37 / 41.98 / 32.54%；responsiveness 89.53 / 81.79 / 79.82%；A_seq 10.89 / 1.86 / 5.58。
- 没有自动检查"未受扰动部分保持不变"；只在标注规范里要求 Plan-Bound 把修订限定在受扰动范围。

#### 1.9 TravelEval（KDD 2026，部分验证）— [arXiv HTML](https://arxiv.org/html/2606.01046)
22 个指标，全部是规则/公式，无 LLM judge：
- **Accuracy（6）**：Cost Calculation Deviation、Fictitious Attraction Rate、Violation Rate of Opening Hours、Failure Rate of Traffic Connection、Intercity Traffic Deviation、Personnel Deviation（床位/车辆/票数与人数的偏差）。
- **Compliance（5）**：Budget / Time / Headcount Compliance Sign、Preference Achievement Sign（住宿、交通、菜系匹配）、Tour-Time Compliance Sign（游览时长落在推荐区间）。
- **Temporality（3）**：Scene-Time Ratio（含排队的有效游览占比）、Daily / Overall Time Utilization。
- **Spatiality（2）**：Scene Sequence Rationality（实际驾车距离对最优路线的惩罚）、Cross-Day Spatial Mismatch（同日簇内距离 / 跨日簇距离，取 P90、P95）。
- **Economy（2）**：Budget Efficiency、Cost Composition（6 类成本占比）。
- **Utility（4）**：Experience Diversity Index（香农熵）、Attractions Density Score（每日景点数相对该人群类型的目标值）、Attractions Quality Efficiency、Profit。
- 模拟式全局评估：用 Amap 路网距离而非直线距离；排队时间模型 T_queue = B_category × K_date × K_time；景点密度基线来自游记。
- 数据：1,150 条查询（easy 200 / medium 400 / hard 400 / progressive 150），沙盒建立在 ChinaTravel 之上。
- 发现：LLM 预算合规率低于 40%（Claude-4.5 Sonnet 31.10%，GPT-4o Direct 38.26%）；两个代码基线 62.73% 与 92.17%；工具增强 agent 的 BCS 总体 0.5703、hard 查询 0.28；高级 prompting 策略相对 Direct 没有稳定增益。
- 不涉及天气。

#### 1.10 VeriTrip（NeurIPS 2026）— [arXiv HTML](https://arxiv.org/html/2605.28683)
- 输出 schema：`transportationTable`、`accommodationTable`、`itineraryTable` 三张表。
- 逐格事实核对：交通 ID、出发时刻、酒店名、POI 名与 agent 不可见的 Verifiable Knowledge Base 比对；数值/时间字段精确匹配，文本字段按语义相似度模糊匹配；正确格子占比 = Factual Reliability。
- 19 条约束：14 条硬/常识（预算、到达与离开时刻、交通连续性与闭环、交通日期、住宿容量与覆盖、景点与用餐不重复、市内时间效率、天数覆盖、午间有活动、信息密度）+ 5 条偏好（跨城交通、住宿、必去景点、餐饮、市内交通）。
- 指标：DR、FR、PR（micro / macro）、PFR、AM（超出 TSP 最优的路程 / POI 数）。
- 结果：Claude-4.5-Sonnet 复杂查询 FR 68.60%、约 37 次工具调用；复杂查询上各模型偏好满足率都大幅下降（o3 下降 27.81 点）。

#### 1.11 TREK（仅 arXiv）— [arXiv HTML](https://arxiv.org/html/2607.26977)
- 完全确定性的规则评测器：无 LLM judge、无嵌入模型、无学习阈值、无网络访问；人工核验的 gold 方案在该评测器下得 1.0。
- 800 任务 = 533 可行 + 267 不可行（entity / route / budget 各 89）；375 城、13 个 persona。
- 9 个维度 4 类：Constraint Satisfaction（D0-key 显式要素与完整性、D1 隐含 persona 需求、D2 目的地城市全部订到、D3 预算）；Truthfulness（D0-src 每个实体都能解析到知识库记录）；Executability（B2 景点在开放时间内、B3 同日交通时间可行）；Infeasibility Handling（D4 对不可行任务给出类型正确的拒绝）。
- 硬门（二值）：什么都没订、编造实体、过半可检的游览落在开放时间外、漏掉显式要求的实体；这些硬门在 800 份 gold 方案上一次都不触发。
- 预算 D3：超支指数惩罚 β = 4（超 25% 得 0.37，超 50% 得 0.14）。
- 不可行任务的标签由构造决定，并由评测器独立重算真实原因；D4 只有拒绝理由指对了原因才得 1.0。
- 指标：每类"全有或全无"；总分 = 四类得分的几何平均；头条指标是 task-perfect rate。15 个模型里最好的在可解任务上 46.2% 完全可行，中位数 6.6%。

#### 1.12 Trip+（仅 arXiv）— [arXiv HTML](https://arxiv.org/html/2606.21169)
- 回复模式门：`<plan>`、`<clarification>`（如局部修改请求含糊，或新硬约束与现有硬约束冲突且用户没给优先级）、`<no_solution>`（现有硬约束可证明不可满足，且用户已授权直接给无解结论）；R_t = 1[预测模式 = 标注模式]。
- 行程可行性 F_p = (D_structure + D_evidence + D_operability) / 3，每个维度是其原子检查的通过率；硬约束 H_p = 通过数 / 可评估数；软偏好按规则打 1.0 / 0.5 / 0.0，先在族内平均再跨族平均（四族：舒适与节奏、交通便利、预算与价值、兴趣匹配）。
- 硬约束类型：行程元数据（日期、天数、人数、房间数）、跨城方式与票（方式、起讫、日期、时间窗、直达、票数、舱位）、住宿（指定酒店、星级、品牌、服务、价格区间）、餐饮、景点（必去/禁去、类型、排名）、预算（**只有用户明确说出的上限才算硬预算**，画像里的预算区间不算）。
- 多轮：Request Fulfillment F_t = 本轮新增或修订的检查的通过率；Intent Preservation I_t = 仍然有效的既往承诺的通过率，被用户明确删除或修订的承诺不计入。
- 可行性、硬约束、软偏好检查是确定性的；用户模拟体验分用 4 个 LLM judge 取中位数。

#### 1.13 其他
- Flex-TravelPlanner：在 TravelPlanner 上做多轮逐步加约束与带优先级的冲突约束；结论是单轮成绩不能预测多轮适应能力、约束引入顺序显著影响结果、模型常让新来的低优先级偏好压过已有的高优先级约束 — [arXiv 2506.04649](https://arxiv.org/abs/2506.04649)。

### Inferences

可移植约束目录（checker 设计均来自上面的来源，"建议档位"是我对本项目的推断）：

| 约束类型 | 检查器设计 | 判 unknown 的条件 | 来源 | 建议档位 |
|---|---|---|---|---|
| 实体落地（grounding） | 计划里每个 POI/酒店/交通 ID 必须能解析到工具返回记录 | 工具结果已过期或未缓存 | TravelPlanner `is_valid_information_in_sandbox`、ChinaTravel `Is_activity_grounded`、TREK D0-src、VeriTrip FR | hard block |
| 信息完整 | 每天必备槽位齐全；有效信息占比下限 0.5 | — | TravelPlanner `is_not_absent` | hard block |
| 不重复 | 景点、餐厅全程去重；同日同餐别不重复 | — | TravelPlanner、ChinaTravel | hard block |
| 开放时间 | `open ≤ start ∧ end ≤ close`，跨夜 +24h | 无营业时间数据 | ChinaTravel、TREK B2、TravelEval VROH | hard block（数据缺失时 unknown） |
| 时间顺序与衔接 | 活动不重叠；活动开始 ≥ 到达交通的到达时刻 | — | ChinaTravel `Is_time_correct` | hard block |
| 空间连续 | 位置变化必须有交通段且首尾端点对上；位置没变不应有交通段 | — | ChinaTravel `Is_space_correct` | hard block |
| 交通时间可行 | 分配时间 ≥ 最小门到门时间；可加上限（如 2×最小值）抓"留白过长" | 路线工具失败 | TREK B3、Iti-Validator、TravelEval FRTC/ITD | hard block / warning |
| 用餐时间窗 | 早 06–09、午 11–14、晚 17–20（交集判定）；或两餐间隔 ≥ 4h | — | ChinaTravel、TripCraft | warning（日本场景需重设窗口） |
| 游览时长 | 落在类别推荐区间内 | 无推荐时长 | TripTailor、TravelEval TTCS、TP-RAG DUR | warning |
| 首末日窗口 | 首个活动 ≥ 到达时刻、末个活动 ≤ 离开时刻 | 未知航班时刻 | VeriTrip（到达/离开时刻约束）、ChinaTravel（首末事件为跨城交通） | hard block |
| 住宿覆盖 | 多日必须有住宿；非末日每晚有住宿；最少入住晚数 | — | TravelPlanner、ChinaTravel、VeriTrip | hard block |
| 人数容量 | 房间数/车数/票数 ≥ ceil(人数/容量) | — | TravelPlanner cost 公式、TravelEval HCS/PD | hard block |
| 预算 | 分项 price × qty 与 cost 容差 0.1；总和 ≤ 上限；只有用户明说的上限才算硬 | 有分项缺价格 | ChinaTravel、TravelPlanner、Trip+、TREK D3 | hard block；超支幅度另给连续分 |
| 类型/必去/排除 | 集合包含/排除、计数、单项预算或时长上限（DSL 原子组合） | 类别词不在词表 | ChinaTravel DSL、TRIP-Bench rubric | hard block |
| 路线效率 | 实际路程 / TSP 最优；同日簇内距离 / 跨日距离 | — | TP-RAG DMR、TravelEval SSR/CSM、VeriTrip AM | info / 连续分 |
| 人群适配 | persona → 必需设施的确定性映射；按节奏限制每日景点数、休息块、最早出发 | 设施字段缺失 | TREK D1、Trip+、TravelEval ADS | warning |
| 天气暴露 | 户外分钟数阈值、是否有室内备选 | 无预报或 POI 未标室内外 | Trip+ | warning（论文侧推断；按开发者决定改为硬规则，见第 6 节 P13） |
| 修订保真 | 既往承诺通过率 I_t；槽位保留率；逻辑编辑数 | — | Trip+、Replan/Repair/Edit、TripTide A_seq | hard block（越界修改）/ info（保留率） |
| 不可行处理 | 类型化拒绝（entity / route / budget）且原因须与评测器重算的一致 | — | TREK D4、TravelBench、Trip+ | hard block |

- 指标口径建议直接沿用三层：micro（按检查条数，`None`/unknown 不进分子也不进分母）、macro（整份计划无 False）、final（环境 + 用户约束全过）；并补 C-LPR 式的"先过环境再算用户约束"口径，避免靠编造实体"满足"用户要求（依据 TravelPlanner 的门控与 ChinaTravel 的 C-LPR）。
- TRIP-Bench 的 strict / loose 双口径（可行性零容忍，合理性容 2 条、用户约束容 1 条）适合做"可上线"与"理想"两条线。

### Gaps
- TRIP-Bench 的 12 条通用约束逐条清单、阈值与评测器实现没有抓到（arXiv HTML 截断，PDF 文本未能解析）。
- ChinaTravel 论文附录 Table 7 的原文 25 条与当前代码 27 列的对应关系，作者没有说明；我只做了逐列计数。
- ChinaTravel 的 DSL 概念函数完整签名表（`activity_cost`、`activity_type` 等）没有拿到，README 把它指向 `symbol_verification/readme.md`，而该文件只列了常识约束。
- TravelEval 的 KDD 2026 录用未能在 ACM DL 或 KDD 官网直接确认（403）。
- TravelPlanner 的 ICML 2024、TripTailor 的 ACL 2025 Findings 本次没有在出版方页面复核。
- 没有找到 AAAI 2026、WWW 2026、EMNLP 2026 主会的旅行规划 benchmark；AAAI 2026 只搜到一篇 workshop 综述，不计入。

---

## 2. 2026 顶会的 neuro-symbolic 规划与校验方法：机制、增益、成本、无 solver 可抄什么

### Takeaway
2026 顶会里与本题最贴近的是 ChinaTravel 的 NeSy Planning（ICLR 2026：NL→DSL + 符号搜索，人写查询 FPR 37.0% 对纯 LLM 2.60%）、ATLAS（ICLR 2026：Constraint Manager + Checker 三值判定 + 不可满足时回去补检索，TravelPlanner 验证集 23.3%→44.4%）和 Soteria（NeurIPS 2026 oral：执行前先形式化验证计划）；其余强证据仍来自 2024–2025 的 LLM-Modulo 与 SMT 路线，以及 2026 的 arXiv 预印本。
不用 solver 也能抄的核心是四件事：**约束先结构化成闭词表的类型化规则；校验器给出"违规 / 未知 / 不可满足"三类不同反馈；修复轮数封顶在 3 左右；不可满足时改走"补信息或请用户放宽"而不是继续修。**

### Cited Findings

#### 2.0 venue 核实台账（方法部分）

| 工作 | venue | 核实方式 |
|---|---|---|
| ChinaTravel（NeSy Planning） | ICLR 2026 | 见 1.0 |
| ATLAS | ICLR 2026 | 【搜索条目】[proceedings.iclr.cc](https://proceedings.iclr.cc/paper_files/paper/2026/hash/6c78ae0c1140902bf3a430b1725bcc4e-Abstract-Conference.html)、[iclr.cc poster](https://iclr.cc/virtual/2026/poster/10007591)；[arXiv abs 页](https://arxiv.org/abs/2509.25586)没有 comments；正文读 [arXiv HTML](https://arxiv.org/html/2509.25586) |
| Soteria | NeurIPS 2026 oral | 【已开页】[neurips.cc oral 154928](https://neurips.cc/virtual/2026/oral/154928)（2026-12-10 口头报告）；只读到摘要 |
| TRIP-Bench（含 GTPO） | ICML 2026 | 见 1.0 |
| iTIMO | SIGIR 2026 | 见 1.0【arXiv 注记】 |
| TimeWarp | NeurIPS 2026 Evaluations and Datasets | 【arXiv 注记】[arXiv 2603.04949](https://arxiv.org/abs/2603.04949) comments |
| AgentSpec | ICSE 2026（软件工程顶会，**不在任务书列的 venue 名单内**） | 【arXiv 注记】[arXiv 2503.18666](https://arxiv.org/abs/2503.18666) comments：ICSE'26 pp. 2938–2950 |
| LLM-Modulo（立场论文） | ICML 2024 —— 背景 | 【二手】[Stanford 综述博客](https://web.stanford.edu/~shuhuiq/blog/review-checking-agents.html)标注为 ICML 2024 |
| LLM-Modulo 旅行案例 | 【仅 arXiv】2024 —— 背景 | [arXiv 2405.20625](https://arxiv.org/html/2405.20625v1) |
| Hao et al.（SMT） | NAACL 2025 long —— 背景 | 【搜索条目】[ACL Anthology 2025.naacl-long.176](https://aclanthology.org/2025.naacl-long.176)，pp. 3434–3483 |
| HiMAP-Travel、Replan/Repair/Edit、ROAM、TREK、Trip+、ContextCov、AgentLTL、VRR-Stop、The Verifier Tax、VERGE、Iti-Validator | 【仅 arXiv】未验证 | 各自 arXiv 链接见下文 |

#### 2.1 2026 顶会已核实的方法

**ChinaTravel NeSy Planning（ICLR 2026）** — [arXiv v5](https://arxiv.org/html/2412.13682v5)
- 机制：LLM 把自然语言需求译成 DSL（Reflexion + DSL 语法检查器，5 轮迭代）；随后做交互式符号搜索并回溯，直到找到可行解；每条查询限时 5 分钟（不含 LLM 推理）；超时则返回通过校验代码最多的计划，没有任何环境合规方案时返回空计划。
- 增益：NeSy Planning（DeepSeek）FPR 为 Easy 52.6%、Human-Val 37.0%、Human-Test 23.3%；纯神经方法 2.60%（摘要口径约 10 倍）；Act（DeepSeek）与 ReAct one-shot（GPT-4o）在 Easy 上 FPR 都是 0。
- 成本：ReAct one-shot + GPT-4o 平均每条查询 $2.43；NeSy Planning + DeepSeek $0.003，+ GPT-4o $0.306。
- NL2DSL 的失败模式：语法修复循环会**丢约束**（小模型的约束条数随迭代下降；GPT-4o 平均比 DeepSeek-V3 少产出约 2 条约束）；84% 的案例是训练示例里没见过的 DSL 结构，结构对齐率 12%（见过的结构 16%，准确率 93%）；含语义化 POI 时 DeepSeek-V3 准确率从 94% 降到 76%，GPT-4o 从 79% 降到 53%。
- 同文对 LLM-modulo 的观察：修正在约 3–5 轮后停滞，每轮新修正 ≤1 条；对 TTG（MILP 路线）的观察：Easy 上只有 18% 找到有效解，2 日行程 23%、3 日 6%。

**ATLAS（ICLR 2026）** — [arXiv HTML](https://arxiv.org/html/2509.25586)
- 机制：把旅行规划写成 CSP（变量 = 每日决策，域 = 搜索结果，约束 = 显式 + 隐式）。五个角色：Search Agent（ReAct 式取数并抽成结构化域）、Constraint Manager（从查询和当前域推导显式约束，并补上常识隐式约束）、Planner、Checker（返回 **valid / invalid / unsat** 加违规反馈）、Search Advisor（unsat 时诊断信息缺口并写定向检索指令）。
- 循环上限：每轮检索内 Planner–Checker 最多修订 K = 3 次；交错检索最多 L = 10 轮（live search 时 L = 5）。
- Checker 是 LLM agent，不是代码；作者在 future work 里说接入正式 CSP solver 可以让校验更稳健。
- 增益（TravelPlanner，final pass）：验证集 Gemini-2.5-Pro——ReAct 20.56、PMC 23.33、ATLAS 44.44；测试集——ReAct 19.50、ReAct+Reflexion 22.70、PMC 21.08、ATLAS 35.00；Claude-Sonnet-4 测试集 ReAct 10.40、ATLAS 18.00。
- 消融：去掉 Constraint Manager 后 44.44 → 30.00（硬约束 macro 74.44 → 60.00）；L = 0 时 K = 0/1/3/5 对应 17.78 / 29.44 / 31.11 / 32.22（K = 3 之后基本持平，瓶颈是信息不足而不是逻辑）；K = 3 时 L = 0/1/3/5 对应 31.11 / 40.56 / 42.78 / 44.44。
- 多轮（Flex-TravelPlanner，ReAct → ATLAS）：2 轮局部约束 30.16 → 39.15；2 轮全局约束 26.25 → 39.59；3 轮 15.34 → 33.60 与 17.20 → 31.75。多轮时先在上一轮缓存的域上跑 Planner–Checker，K 次仍 unsat 才重新检索。
- live search + 多轮反馈：三轮后 final pass ATLAS 83.9%、ReAct 58.9%、单体 agent 27.2%；幻觉结果由另一个带搜索工具的 LLM judge 检查。
- 成本：3 日计划中位墙钟约 6 分钟，5/7 日约 15 分钟；Planner 最耗资源，Checker 与 Constraint Manager 开销很小；token 数未抓到。

**Soteria（NeurIPS 2026 oral）** — [neurips.cc](https://neurips.cc/virtual/2026/oral/154928)
- 机制：agent 在执行任何工具前先生成结构化计划，该计划对照规格做形式化验证；执行中用已验证计划做运行时约束，并在不安全动作被拦下时给出下一步指引（分层规划 + 运行时强制）。
- 摘要口径：平均任务成功率是最佳基线的 1.7 倍，且没有任何策略规格违规。规格语言、benchmark 名称与成本在该页都没有给出。（搜索摘要里出现过"up to 5×"的说法，与我打开的页面不一致，以页面为准。）

**AgentSpec（ICSE 2026，名单外）** — [arXiv 2503.18666](https://arxiv.org/abs/2503.18666)
- 规则 DSL = trigger + predicate + enforcement；开销毫秒级；代码 agent 场景拦下 90% 以上不安全执行。
- 用 LLM（o1）自动生成规则：具身场景 precision 95.56%、recall 70.96%；代码场景识别 87.26% 的风险代码。
- 【二手】误报主要来自对含糊需求写得过死的规则 — [Stanford 综述博客](https://web.stanford.edu/~shuhuiq/blog/review-checking-agents.html)。

**iTIMO（SIGIR 2026）** — [arXiv HTML](https://arxiv.org/html/2601.10609)
- 把行程修改形式化为 REPLACE / ADD / DELETE 三种原子操作；Modification Accuracy（与 ground truth 一致）与 All Pass Rate（只改变目标分布、其余分布不变）。
- Melbourne ADD：Qwen3-8B + LoRA 为 Mod 0.263 / APR 0.632；GPT-o4-mini 为 0.197 / 0.618。

#### 2.2 背景（2025 及更早）

**LLM-Modulo 旅行案例（arXiv 2024）** — [arXiv 2405.20625](https://arxiv.org/html/2405.20625v1)
- 机制：生成 → 一组二值 critic 检查 → 把各 critic 的 backprompt 拼接后回灌，最多 10 轮；format critic（JSON 合法与必备键）优先，其余是硬约束 critic 与常识 critic。
- 增益（TravelPlanner 验证集 final pass）：GPT-4-Turbo 4.4% → 20.6%（4.6 倍）；GPT-3.5-Turbo 0% → 5%。critic 子集（GPT-3.5）：只用常识 2.8%、只用硬约束 1.6%、只用格式 1.1%。
- 让 GPT-4-Turbo 自己写 critic 实现：只需小修（函数签名、语法）就能达到既有 critic 的效果（无定量数字）。
- 成本未报告。

**Hao et al.，LLM + SMT（NAACL 2025）** — [arXiv 2404.11891](https://arxiv.org/abs/2404.11891)
- 机制：LLM 把查询形式化成 SMT 约束代码交给 solver；不可满足时用 unsat core 提取原因，LLM 据此建议修改查询。
- 数字：TravelPlanner 成功率 93.9%；两个数据集上平均 81.6% 与 91.7% 的不可满足查询被修改并解出。
- ChinaTravel 作者的质疑：该路线的高分建立在模板化查询上，开放查询泛化存疑 — [arXiv v5](https://arxiv.org/html/2412.13682v5)。

**Google "AI trip ideas"（工程博客，2025-06-06）** — [Google Research blog](https://research.google/blog/optimizing-llm-based-trip-planning/)
- LLM 先出初始计划（含建议时长与重要度）；用实时营业时间与交通时间做 grounding；搜索后端补充可替换的活动。
- 两阶段优化：单日内对活动子集做动态规划，打分 = 与原计划的相似度 + 可行性（完全不可行得 0 分）；跨日是加权 set packing（NP-complete），用局部搜索在日与日之间交换活动。
- 没有给出任何量化结果。

#### 2.3 2026 arXiv 预印本（未验证 venue）

| 工作 | 机制 | 数字 | 来源 |
|---|---|---|---|
| HiMAP-Travel | Coordinator 拆成按天子目标；并行 Day Executor；**Synchronized Global State 是确定性事务监视器**（check / commit / checkpoint / rollback），在 commit 时强制预算与不重复（名称模糊匹配阈值 0.95）；协商最多 3 轮；只管资源冲突，路线可行性不管 | TravelPlanner test FPR 52.65%（Qwen3-8B）；7 日行程墙钟 72s 对 189.5s | [arXiv 2603.04750](https://arxiv.org/html/2603.04750) |
| Replan, Repair, or Edit? | 三种修订策略对比：LLM–Z3 全量重规划（1 次 LLM 调用抽需求 + 固定 Z3 模型）、IPyHOPPER 经典计划修复（无 LLM）、iTIMO 局部编辑 | 单一扰动 500 例：LLM–Z3（Gemini）成功 97.0%、平均 6.63 处编辑、槽位保留 65.35%、1 次调用 1,369 tokens、5.10s；IPyHOPPER 96.8%、1.00 处、92.67%、0 token、2.05s；iTIMO（Gemini）87.8%、1.00 处、92.59%、23,469 tokens、14.21s | [arXiv 2609.19654](https://arxiv.org/html/2609.19654) |
| ROAM | LLM 只负责把请求解析成结构化约束和最后成文；检索 + 团分析聚类 + 模拟退火 TSP + 贪心交换修复时间窗（最多 10 轮） | 去掉时间窗修复后约 30% 的到访晚于闭馆（定性表） | [arXiv 2611.09407](https://arxiv.org/html/2611.09407) |
| Iti-Validator | 规则校验 + **确定性修正**（过短则推后到达、过长则提前、重叠则顺延）；LLM 自我修正试了 3 次重提示，作者认为不可靠而弃用 | 原始输出无效率：Gemini-2.0 48–76%、GPT-4o-mini 97–100%；校验修正后 0% | [arXiv 2510.24719](https://arxiv.org/html/2510.24719v1) |
| ContextCov | 把 AGENTS.md 类指令文件编译成三类可执行检查（AST 静态查询、shell shim 运行时拦截、架构校验器），违规时返回可复现的违规轨迹 | SWE-bench Lite：约束合规 88.3%，prompt-only 67.0%，LLM reflection 50.3%；反馈成本低 3.4 倍 | [arXiv 2603.00822](https://arxiv.org/abs/2603.00822) |
| AgentLTL | 用 FO-LTL 派生语言在 agent 轨迹上表达过程规则，得到确定性、无 judge 的合规分；可离线打分也可在线逐前缀拦截 | block-and-warn 在 7 个模型里 5 个提升合规；用同一分数做微调奖励，保留模式上准确率 +38 点、合规 +17.5 点 | [arXiv 2607.02599](https://arxiv.org/abs/2607.02599) |
| VRR-Stop | 校验器和修复器都有噪声时，多轮修复会把原本正确的计划修坏；提出四参数噪声模型的停止规则 | GSM8K 压力设定：比固定 5 轮修复的最终真实有效性高 60.6 点，平均只用 0.72 轮修复 | [arXiv 2607.17641](https://arxiv.org/abs/2607.17641) |
| The Verifier Tax | 运行时安全拦截对端到端任务的代价 | tau-bench：最多拦下 94% 不合规动作，但多数设定 safe success rate 低于 5%；被拦后的恢复率 21%（简单任务）到接近 0 | [arXiv 2603.19328](https://arxiv.org/abs/2603.19328) |
| VERGE | 用 solver unsat core 的最小修正集来精炼反馈 | 只指出冲突约束、不给修正建议的反馈比完整版平均低 10.9%（搜索摘要） | [arXiv 2601.20055](https://arxiv.org/html/2601.20055) |

### Inferences
无 solver 可抄清单（每条对应上面的证据）：
1. **约束单独成对象**：对话里抽出的需求落成类型化约束表（类型、参数、来源轮次、是否硬），再让 planner 和 validator 都读它。依据：ATLAS 去掉 Constraint Manager 掉 14.4 点；ChinaTravel 的 `hard_logic_py`。
2. **闭词表 + 编译检查**：约束只能由一组预定义原子（cost / type / time / dist / count / 集合运算）组合；用解析器或 JSON schema 做语法门；并且**比较修复前后的约束条数**，防止语法修复循环悄悄丢约束。依据：ChinaTravel 的 DSL 语法检查器与丢约束现象。
3. **三值判定并分流**：违规 → 带规则 ID 与证据回灌修复；不可满足 → 不再修，改去补检索或请用户放宽；未知 → 明示。依据：ATLAS 的 valid / invalid / unsat 与 K 的平台期；Hao et al. 的 unsat core。
4. **修复轮数封顶 3**：ATLAS K = 3 后持平；ChinaTravel 观察到 3–5 轮停滞；VRR-Stop 说明多修有害；HiMAP 协商上限 3。
5. **写入时强制资源类约束**：预算与去重在 stage / commit 时由事务层确定性拦截，而不是事后才查。依据：HiMAP 的 Synchronized Global State。
6. **能确定性修的就别回灌 LLM**：时间顺延、过短过长的交通留白可以直接代码修。依据：Iti-Validator（LLM 自修被弃用）、Google 的 DP + 局部搜索、ROAM 的贪心交换。
7. **修订走局部编辑而非重规划**：把修改表示成 REPLACE / ADD / DELETE，并度量保留率。依据：iTIMO、Replan/Repair/Edit（局部修复约 1 处编辑、92% 保留；重规划 6.6 处、65%）。
8. **用下界证明不可行**：最便宜住宿 × 晚数 + 最低交通费 > 预算即可判 budget 不可行；实体或路线不存在即判 entity / route 不可行。依据：TREK 的三类不可行构造（这条是不用 solver 的近似，覆盖不了约束之间的组合冲突）。

- ATLAS 的 Checker 是 LLM，与"正确性只由确定性规则判定"的既定决策不一致；可借鉴的是它的流程（三值 + 回检索），不是它的 checker 实现。
- 被拦截后 agent 恢复率很低（The Verifier Tax）提示：违规反馈里应带"可行的替代项"，而不只是"哪条错了"（与 VERGE 搜索摘要、Stanford 博客转述的 VeriHarness 结论方向一致）。

### Gaps
- Soteria 只读到 NeurIPS 摘要页：规格语言、benchmark、成本未知，无法判断是否适用于行程类约束。
- 没有找到在 ACL / EMNLP / ICML / KDD / WWW / AAAI / IJCAI 2026 主会**已确认录用**的、专门做"用户话语 → DSL/JSON 规则"的独立方法论文；这方面 2026 顶会的证据只有 ChinaTravel 的 NL2DSL 与 ATLAS 的 Constraint Manager。搜到的 VERGE、Faithful Autoformalization、AgentLTL、ContextCov 都未能确认 venue。
- ATLAS 的 token 成本与 LLM 调用次数（附录 D.7）没有抓到。
- LLM-Modulo 立场论文的 ICML 2024 录用只有二手标注，未在 PMLR 页复核。

---

## 3. 这些工作怎么处理：(a) 无法机检的自由文本需求 (b) 天气/情境规则 (c) 修订后的编辑局部性 (d) 时间可行性 (e) 预算 (f) 同行人适配

### Takeaway
成熟做法都把"查不了"与"违规"分成不同的返回值并给不同的后续动作（AWS Automated Reasoning 有 7 种结果类型，TravelPlanner 用 `None`，Trip+ / TravelBench / TREK 把"澄清"和"类型化无解"做成可评分的回复模式）；时间与预算是所有 benchmark 里规则化最彻底的两块。
天气和编辑局部性是文献里最薄的两块：天气只有 Trip+（arXiv）给出了可移植的户外时长阈值规则，编辑局部性只有 Replan/Repair/Edit（arXiv）给出了槽位级 diff 定义，顶会论文（TRIP-Bench、TripTide）都没有做"未请求部分不变"的自动检查。

### Cited Findings

#### (a) 无法机检的自由文本需求：unknown vs violated
- TravelPlanner：查询没设的硬约束返回 `None`；`None` 不计入 micro 的 True/False，也不导致 macro 失败；常识门没过时整组硬约束为 `None`、不评 — [eval.py](https://raw.githubusercontent.com/OSU-NLP-Group/TravelPlanner/main/evaluation/eval.py)、[hard_constraint.py](https://raw.githubusercontent.com/OSU-NLP-Group/TravelPlanner/main/evaluation/hard_constraint.py)。
- ChinaTravel：标注阶段直接剔除沙盒里无法验证的查询；NL2DSL 的未见结构占 84%、对齐率 12% — [arXiv v5](https://arxiv.org/html/2412.13682v5)。
- AWS Bedrock Automated Reasoning checks 的结果类型（两步：LLM 翻译成逻辑 → SMT 校验；翻译可能出错，校验本身是 sound 的）— [concepts 文档](https://docs.aws.amazon.com/bedrock/latest/userguide/automated-reasoning-checks-concepts.html)：
  - `VALID`：可放行；记录 supportingRules 做审计；但只覆盖被翻译进变量的部分。
  - `INVALID`：不放行；把 contradictingRules 与错误 claim 回灌 LLM 重写。
  - `SATISFIABLE`：在某些条件下成立、某些条件下不成立；补全缺失条件、向用户澄清，或带提示放行。
  - `IMPOSSIBLE`：前提自相矛盾，或策略本身有冲突。
  - `TRANSLATION_AMBIGUOUS`：多个翻译模型给出不同解释；改进变量描述或向用户澄清。
  - `TOO_COMPLEX`：输入或策略超出处理能力。
  - `NO_TRANSLATIONS`：部分内容无法映射到策略变量；文档要求把未翻译内容当**警告信号**处理。
  - 聚合时按严重度取最差：TRANSLATION_AMBIGUOUS > IMPOSSIBLE > INVALID > SATISFIABLE > VALID。
  - 置信度 = 多个翻译模型给出语义等价翻译的比例；阈值越高，准确率越高但更多输入落入 AMBIGUOUS。
  - 文档明确：能逐字符判断的校验（如密码规则）应交给确定性规则代码，而不是这套自然语言推理。
- Trip+：`<clarification>` 用于局部修改请求含糊、或新硬约束与现有硬约束冲突且没给优先级；`<no_solution>` 只在硬约束可证明不可满足且用户授权时使用；回复模式对不对单独计分 — [arXiv 2606.21169](https://arxiv.org/html/2606.21169)。
- TravelBench：Unsolvable 子集按"首条回复是否带 `[Unsolved]`"规则计分；模型间差异很大（51.33 到 94.00）— [arXiv 2512.22673](https://arxiv.org/html/2512.22673)。
- TREK：不可行任务占 33.4%，拒绝必须指对原因类型（entity / route / budget）才得分 — [arXiv 2607.26977](https://arxiv.org/html/2607.26977)。
- ATLAS：unsat 的定义是"在当前信息下不存在有效计划"，触发补检索而不是继续修订 — [arXiv HTML](https://arxiv.org/html/2509.25586)。
- Anthropic 评测指南：给 LLM grader 留出口（信息不足时返回 Unknown）以减少幻觉 — [Anthropic Engineering](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)。
- 【二手，小样本】某确定性需求核查器在 20 个规划任务、142 条需求标签上对"已满足"的需求有 39% 选择弃权，且从未误确认被破坏的需求；LLM judge 一致率 72–83% 但会接受被破坏的需求 — [Stanford 综述博客（作者自测）](https://web.stanford.edu/~shuhuiq/blog/review-checking-agents.html)。

#### (b) 天气/情境依赖规则
- Trip+：沙盒存每日城市天气（天况、温度、降水信号），环境参考另含降雨量与降雨小时数。户外暴露规则：高温日 11:00–15:00 户外 ≤ 90 分钟；寒冷日 18:00 后户外 ≤ 90 分钟；全天户外合计 ≤ 240 分钟；90–120 分钟（或合计 240–300 分钟）得 0.5，再超得 0.0。`weather_need_backup`：存在室内/天气备选且户外负荷 ≤ 240 分钟才通过。环境驱动重规划按"是否确认事件、是否修订、是否保住既往硬约束"评分。结果：95% 的有效计划存在环境暴露负担；环境驱动重规划的 request fulfillment 只有 0.60 — [arXiv 2606.21169](https://arxiv.org/html/2606.21169)。
- ROAM：预报表示为每日天况、温度区间、降雨概率；没有定义室内占比指标；消融只定性说明去掉上下文后雨天计划会忽略预报、仍排户外；上海雨天覆盖数从 33 降到 15，作者归因于数据库里室内 POI 稀少 — [arXiv 2611.09407](https://arxiv.org/html/2611.09407)。
- TripTide：天气不是独立类别，分散在 Transport（恶劣天气影响航班）、Attractions、Miscellaneous 的扰动原因里 — [arXiv v1](https://arxiv.org/html/2510.21329v1)。
- TravelEval 不涉及天气 — [arXiv 2606.01046](https://arxiv.org/html/2606.01046)。
- TravelBench 的工具集含天气预报工具，天气相关决策由 LLM judge 评，而非规则 — [arXiv 2512.22673](https://arxiv.org/html/2512.22673)。

#### (c) 修订后的编辑局部性
- Replan/Repair/Edit：**Logical edits** d(P, P′) 数的是语义变化而非文本差异，每日景点编辑数 = max(|移除|, |新增|)；**Preserved slots** = 原计划逻辑槽位中取值不变的平均比例；槽位键——航班按 route、酒店与租车按 city、城市与景点按 day；稳定性只在成功修复的案例上统计。复合扰动：LLM–Z3 约 9.0 处编辑 / 57% 保留，IPyHOPPER 2.23 处 / 86.73%，iTIMO 约 2.2 处 / 86% — [arXiv 2609.19654](https://arxiv.org/html/2609.19654)。
- TripTide：A_seq = 修订前后 PoI 序列的编辑距离 / 较长序列长度；Plan-Bound 旅客的修订范围应限定在 step / day / plan 级扰动范围内，但这只是标注规范，没有自动检查 — [arXiv v1](https://arxiv.org/html/2510.21329v1)。
- Trip+：Intent Preservation I_t 只查"仍然有效的既往承诺"是否仍通过，被用户明确修改或删除的不计；它查的是约束是否仍满足，不是计划内容是否未变 — [arXiv 2606.21169](https://arxiv.org/html/2606.21169)。
- iTIMO：REPLACE / ADD / DELETE 原子操作；APR 检查是否只改变了目标分布而其余分布不变 — [arXiv 2601.10609](https://arxiv.org/html/2601.10609)。
- TRIP-Bench：有回滚、局部修订、版本合并等用户行为，要求每次返回完整 `trip_plan`，但没有描述"未改动部分保持不变"的检查 — [arXiv 2602.01675](https://arxiv.org/html/2602.01675)。
- Flex-TravelPlanner：模型常让新来的低优先级偏好压过已有的高优先级约束 — [arXiv 2506.04649](https://arxiv.org/abs/2506.04649)。
- Google trip ideas：优化目标本身包含"与 LLM 初始计划的相似度"，把保持原意写进了打分函数 — [Google Research blog](https://research.google/blog/optimizing-llm-based-trip-planning/)。

#### (d) 时间可行性
- 开放时间：ChinaTravel `open ≤ start ∧ end ≤ close`，跨夜 +24h — [代码](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/symbol_verification/commonsense_constraint.py)；TREK B2，且"过半可检的游览落在开放时间外"是硬门 — [arXiv 2607.26977](https://arxiv.org/html/2607.26977)；TravelEval VROH — [arXiv 2606.01046](https://arxiv.org/html/2606.01046)；ROAM 只要求到达时刻 ≤ 闭馆时刻 — [arXiv 2611.09407](https://arxiv.org/html/2611.09407)。
- 交通时间：TREK B3 用规范模型算最小门到门时间，且 agent 的交通时间工具与评测器用同一个模型 — [arXiv 2607.26977](https://arxiv.org/html/2607.26977)；Iti-Validator：分配时间 < t_min 无效、> 2 × t_min 也无效，停留至少 2 天，访问区间不得重叠 — [arXiv 2510.24719](https://arxiv.org/html/2510.24719v1)；ROAM 按 500 m/min 估算 — [arXiv 2611.09407](https://arxiv.org/html/2611.09407)。
- 顺序与衔接：ChinaTravel 同日活动不重叠、活动不得早于到达交通的到达时刻，分钟级无容差 — [代码](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/symbol_verification/commonsense_constraint.py)。
- 到离日窗口：ChinaTravel 要求首末事件为跨城交通且时刻与沙盒一致 — [readme](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/symbol_verification/readme.md)；VeriTrip 把到达/离开时刻、交通日期、天数覆盖、午间有活动列为硬/常识约束 — [arXiv 2605.28683](https://arxiv.org/html/2605.28683)；Trip+ 把跨城时间窗、是否直达列为硬约束，把避开红眼/过早出发列为软偏好 — [arXiv 2606.21169](https://arxiv.org/html/2606.21169)。
- 用餐：ChinaTravel 三个时间窗 — [代码](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/symbol_verification/commonsense_constraint.py)；TripCraft 两餐间隔 ≥ 4h — [arXiv 2502.20508](https://arxiv.org/html/2502.20508)。
- 时长与缓冲：TP-RAG 的 Duration Underflow Ratio、Time Buffer Ratio — [arXiv 2504.08694](https://arxiv.org/html/2504.08694)；TravelEval 加排队时间模型 — [arXiv 2606.01046](https://arxiv.org/html/2606.01046)。
- 原始 LLM 行程的时间无效率很高：GPT-4o-mini 97–100%、Gemini-2.0 48–76% — [Iti-Validator](https://arxiv.org/html/2510.24719v1)。

#### (e) 预算
- TravelPlanner：按人数与容量折算的总成本 ≤ budget；找不到匹配行的项不计费 — [hard_constraint.py](https://raw.githubusercontent.com/OSU-NLP-Group/TravelPlanner/main/evaluation/hard_constraint.py)。
- ChinaTravel：分项 `price × 数量` 与 `cost` 容差 0.1，单价须与沙盒一致；总预算与单项预算用 DSL 表达 — [代码](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/symbol_verification/commonsense_constraint.py)、[arXiv v5](https://arxiv.org/html/2412.13682v5)。
- TREK：超支指数惩罚（β = 4）；budget 型不可行 = 预算低于可达成本下界；预算由评测器自己的成本模型定价 — [arXiv 2607.26977](https://arxiv.org/html/2607.26977)。
- TravelEval：Cost Calculation Deviation（LLM 自己算的费用与实际的偏差）、Budget Compliance Sign、Budget Efficiency、Cost Composition；LLM 预算合规率低于 40% — [arXiv 2606.01046](https://arxiv.org/html/2606.01046)。
- Trip+：只有用户明确说出的上限算硬预算 — [arXiv 2606.21169](https://arxiv.org/html/2606.21169)。
- HiMAP-Travel：预算在 commit 时由确定性监视器强制 — [arXiv 2603.04750](https://arxiv.org/html/2603.04750)。
- 【二手，小样本】在 8 份计划里植入占预算 60% 的费用行，LLM judge 接受了 2–8 份，确定性核查器全部拒绝 — [Stanford 综述博客（作者自测）](https://web.stanford.edu/~shuhuiq/blog/review-checking-agents.html)。

#### (f) 同行人适配（儿童、老人）
- TREK：13 个 persona（含带儿童、老年旅客、残障旅客、奢华旅客）确定性映射到必需设施；D1 对每个（persona, 资源类型, 城市）格子检查所订资源是否带必需设施；任务带 0–3 个 persona；作者审计后删除了 19 组"不兼容"persona 配对（发现偏见与刻板印象），只保留逻辑上不可能的排除；"未说出口的需求"是各模型的主要瓶颈 — [arXiv 2607.26977](https://arxiv.org/html/2607.26977)。
- Trip+：画像含同行构成（成人/儿童/老人）、行动能力、节奏、休息需求；P03 三代同堂、P04 带娃家庭、P05 慢节奏长者；规则含按节奏的每日景点上限、必须的休息块、最早出发时间（如轻松节奏 ≥ 08:00）、市内换乘时长上限、每日户外活动量；Gemini-3.1-Pro 的 pace/comfort 维度得分 0.39，是各维度最低；99% 的有效计划存在节奏负担、97% 存在疲劳 — [arXiv 2606.21169](https://arxiv.org/html/2606.21169)。
- TravelEval：Attractions Density Score 按人群类型（含老年、亲子）设每日景点数目标；Headcount Compliance / Personnel Deviation 查床位、车辆、票数是否够 — [arXiv 2606.01046](https://arxiv.org/html/2606.01046)。
- TravelPlanner：house rule 含"10 岁以下儿童不可入住"的文本匹配；按 maximum occupancy 折算房间数 — [hard_constraint.py](https://raw.githubusercontent.com/OSU-NLP-Group/TravelPlanner/main/evaluation/hard_constraint.py)。
- TripCraft：Persona Score 用 BERT 嵌入相似度，不是规则；Temporal Attraction Score 的期望时长随 adventurous / laidback 人设平移 — [arXiv 2502.20508](https://arxiv.org/html/2502.20508)。

### Inferences
针对已知三处缺口的检查器设计草案（推断，非来源原文）：

**缺口 1：雨天 → 室内，只是一句 prompt**
- 输入：每日预报（降水概率或降雨小时数）+ 每个 POI 的 indoor / outdoor / mixed 标签（由地点类型映射表确定性给出，映射不到标 unknown）。
- 规则 `WX-OUTDOOR-EXPOSURE`：雨天日户外活动总分钟数超过阈值 → conflict；介于两档之间 → warning。Trip+ 的 240 / 300 分钟分档是按高温/寒冷/全天负荷设的，雨天专用阈值它没有给出，需要自定并标注为本项目假设。
- 规则 `WX-INDOOR-BACKUP`：雨天日存在户外项但没有任何室内备选 → warning（对应 Trip+ 的 `weather_need_backup`）。
- unknown 条件：没有预报（行程日超出预报窗口）、POI 未打标签。
- 档位建议定为 warning 而非 hard block：ROAM 显示室内 POI 供给不足的城市硬套规则会让覆盖数大幅下降；Trip+ 也把它归在软偏好。（后续更新：这是论文侧的旧推断。开发者已明确"雨天 → 室内"按硬规则处理，实践来源与候选规则见第 6 节 P13，以第 6 节为准。）

**缺口 2："只改一项，其余不动"没有前后 diff**
- 把计划拍平成槽位表：键 = (day, slot_kind, 序号或时段)，值 = 实体 ID + 起止时间；住宿按 (城市, 晚) 为键（对应 Replan/Repair/Edit 的槽位键设计）。
- 从用户修改请求得到**允许变更集**：目标槽位 + 必然连带的槽位（与被改项相邻的路线段、因时长变化而顺延的同日后续起止时间）。作用域分级可沿用 TripTide 的 step / day / plan。
- 规则 `EDIT-SCOPE`：`changed_slots − allowed_slots` 非空 → conflict，并列出越界槽位。
- 规则 `EDIT-APPLIED`：目标槽位确实发生了请求的变化（对应 Trip+ 的 Request Fulfillment）。
- 规则 `EDIT-REGRESSION`：修订前通过的既往约束修订后仍通过（对应 Trip+ 的 Intent Preservation）。
- 指标：logical edits（每日景点编辑数取 max(|移除|, |新增|)）与 preserved slots %；参照值——局部修复约 1 处编辑、92% 保留，全量重规划约 6.6 处、65% 保留。
- 请求本身含糊（说不清改哪一项）时不进 diff 检查，走 clarification（Trip+ 的 `<clarification>` 触发条件）。

**缺口 3：自由文本硬需求全标"未验证"**
- 先尝试编译到闭词表的类型化约束（ChinaTravel DSL 原子、TRIP-Bench rubric 字段可作词表来源），编译成功的进规则引擎，得到 verified / conflict。
- 编译有歧义 → 不猜，向用户澄清（AWS `TRANSLATION_AMBIGUOUS`、Trip+ `<clarification>`）。
- 词表覆盖不到 → 保持 unverified，但作为警告显式展示给用户，并计入覆盖率分母（AWS 对未翻译内容的处理方式）。
- 与数据冲突到不可满足 → 类型化无解（TREK 的 entity / route / budget）。
- 可度量：`可机检覆盖率 = 成功编译的需求条数 / 用户硬需求总条数`，按需求类型分桶，覆盖不到的条目进入"新规则候选"队列。
- 防丢约束：编译前后条数必须对得上，对不上就整体退回（ChinaTravel 观察到的丢约束现象）。

### Gaps
- Trip+ 附录 B 中针对降雨量/降雨小时数的具体规则与 POI 室内外标注方法没有抓到（HTML 截断）；雨天阈值在已读到的文献里没有可直接引用的数值。
- 没有找到任何**顶会已录用**论文做"修订后未请求部分保持不变"的自动 diff 检查；唯一给出槽位级定义的是 arXiv 预印本 Replan/Repair/Edit，其表中部分模型名看起来不寻常（搜索摘要提示过），引用其数字前应回原文核对。
- 没有找到把"带婴儿车/轮椅无障碍/饮食禁忌"做成规则的顶会论文；TREK 的 13 个 persona 到设施的完整映射表没有抓到。
- 没有找到专门处理"日本场景"（定休日、最终入场时间、JR Pass 等）约束的 benchmark。

---

## 4. 规则引擎工程实践：注册表、严重度档位、规则 ID 与版本、覆盖率、误报追踪、规则集如何从失败案例长出来

### Takeaway
可直接照搬的成熟做法来自三处：Google 静态分析（有效误报率 < 10% 才准入、"Not useful" 按钮直接给规则作者开 bug、能阻断的只限零有效误报的正确性检查）、AWS Automated Reasoning（策略有 DRAFT 与不可变编号版本、每条 finding 带规则 ID 与策略版本、fidelity report 给 coverage 与 accuracy 两个分数）、Anthropic 评测指南（从 20–50 个真实失败起步、capability eval 饱和后转成 regression eval、读 transcript 区分 agent 错还是 grader 错）。
旅行 benchmark 自身贡献了两条验证规则集的办法：gold 方案在评测器下必须满分且硬门零触发（TREK），以及每条规则配"生成器 + 校验器"一对（TRIP-Bench）。

### Cited Findings

**严重度档位与准入门槛（Google，《Software Engineering at Google》第 20 章）** — [abseil.io](https://abseil.io/resources/swe-book/html/ch20.html)
- effective false positive：开发者看到后没有采取任何积极行动的告警，含看不懂的和不重要的；Tricorder 整体有效误报率略低于 5%。
- 新检查准入四条：易懂；可操作且易修（附修复建议）；有效误报 < 10%；对质量有显著影响。
- 反馈按钮："Not useful" 直接给分析器作者开 bug 并预填结果详情；"Please fix" 由 reviewer 点；团队跟踪 Not useful 相对 Please fix 的比率，高而不改进的分析器会被禁用（没有给数值阈值）。
- 量级：每天约 250 次 Not useful、数千次 Please fix、约 3,000 次自动修复被采纳、分析 5 万多次变更。
- 展示位置即严重度：默认是 code review 里的可忽略评论；presubmit 可阻断提交；**编译错误只留给零有效误报、针对正确性而非风格的机械检查**；尽量不发编译警告（要么升级为错误、要么不显示）。
- 启用新的阻断级检查前，先把存量违规全部清掉。
- 定制粒度是项目级而非用户级；可选分析器在积累信任后升级为默认开启。
- 一个例子：改清楚诊断文案后，某检查每周持续出现的 Not useful 报告就停了。

**规则 ID、版本、覆盖率（AWS Automated Reasoning checks）** — [concepts](https://docs.aws.amazon.com/bedrock/latest/userguide/automated-reasoning-checks-concepts.html)、[概览](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html)
- 策略有一个可编辑的 DRAFT 和若干不可变的编号版本；线上引用编号版本，改 DRAFT 不影响已部署。
- 每条 finding 里的 supportingRules / contradictingRules 都带规则标识符与策略版本 ARN，用于审计。
- fidelity report：coverage score（策略覆盖了源文档多少陈述）与 accuracy score（规则是否忠实于原意），两者 0.0–1.0，并把每条规则、每个变量回链到源文档的具体陈述与行号。
- 测试：用生成场景验证规则正确性，用问答测试验证自然语言到逻辑的翻译准确率；改策略时靠测试防回归。
- 规则写成 if-then 蕴含式；裸断言会变成公理，容易导致意外的 `IMPOSSIBLE`。
- 变量描述是翻译准确率的首要因素：写清单位与格式、同义说法、边界条件；删掉重复或未被任何规则引用的变量。
- 枚举没有合适取值时加 `OTHER` / `NONE`，避免翻译被迫选错。
- 每个策略聚焦单一领域；变量越多，校验延迟越高。
- 只在 detect 模式运行：返回 findings，由应用决定放行、重写还是澄清。

**运行时规则 DSL** 
- AgentSpec：规则 = trigger + predicate + enforcement，毫秒级开销 — [arXiv 2503.18666](https://arxiv.org/abs/2503.18666)。
- 【二手】护栏按速度分层：分类器几十毫秒、规则引擎约 1 毫秒、guard agent 秒级 — [Stanford 综述博客](https://web.stanford.edu/~shuhuiq/blog/review-checking-agents.html)。

**规则集如何增长与自检（Anthropic，2026-01-09）** — [Anthropic Engineering](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- 从 20–50 个来自真实失败的简单任务起步；把用户报告的失败和支持队列里的问题转成用例，按用户影响排序。
- capability eval 起始通过率应该低；通过率高了就"毕业"进 regression suite，后者应接近 100% 并持续运行。
- 能用确定性 grader 的地方就用，必要时才用 LLM grader，人工只做校准。
- 评结果而不是评路径：对步骤顺序做死板检查会惩罚合理的替代做法。
- 必须读 transcript 来区分"agent 真错"与"grader 拒绝了正确解"；举例某模型在 CORE-Bench 上从 42% 修到 95%，差距来自评分缺陷与 harness 限制。
- 多次试验通过率为 0% 通常说明任务坏了，而不是 agent 不行。
- 同时准备"应触发"和"不应触发"两类用例，避免单边优化。
- pass@k（k 次里至少一次成功）与 pass^k（k 次全成功）；面向用户的 agent 看 pass^k。

**旅行 benchmark 里的规则集验证办法**
- TREK：人工核验的 gold 方案在评测器下得 1.0；四个硬门在 800 份 gold 上零触发；不可行标签由评测器独立重算，标签对不上的样本剔除 — [arXiv 2607.26977](https://arxiv.org/html/2607.26977)。
- TRIP-Bench：每条 rubric 配生成器 G(e)（给出可行 ID 集）与校验器 V(e, i) — [arXiv 2602.01675](https://arxiv.org/html/2602.01675)。
- ChinaTravel：评测器抛异常时单独记一列 `Commonsense Evaluator Exception`，不混进正常违规 — [evaluation 代码](https://raw.githubusercontent.com/LAMDASZ-ML/ChinaTravel/main/chinatravel/evaluation/commonsense_constraint.py)。
- TRIP-Bench 的 strict / loose 双阈值把"可行性零容忍、合理性有限容忍"写进了指标 — [arXiv 2602.01675](https://arxiv.org/html/2602.01675)。
- ContextCov：违规时返回可复现的违规轨迹，供 agent 自我修正 — [arXiv 2603.00822](https://arxiv.org/abs/2603.00822)。

### Inferences
- 规则注册表每条建议带的字段：`rule_id`（稳定不复用）、`version`、`severity`（block / warn / info）、`category`（grounding / temporal / spatial / budget / party / weather / edit / user-constraint）、`applies_when`（不适用时返回 not_applicable 而不是 pass）、`unknown_when`（缺哪些数据时判 unknown）、`evidence`（命中的槽位与数值）、`fix_hint`（可行替代项）、`origin_case`（来自哪个失败案例）、`owner`。字段设计对应：AWS 的规则 ID + 策略版本、Google 的可操作性与归属、TravelPlanner 的 `None`、The Verifier Tax 提示的"要给替代项"。
- 档位准入线可借 Google 的标准：只有在 gold/人工确认的合法行程上零误报的规则才能进 block 档；新规则先以 info 档"影子运行"，积累到有效误报 < 10% 再升档。
- 该跟踪的四个比率：
  1. 可机检覆盖率 = 编译成规则的用户硬需求 / 全部硬需求（AWS coverage score、ChinaTravel NL2DSL 的思路）；
  2. unknown 率 = unknown 结果 / 全部规则执行次数，按规则分桶（数据缺口的直接信号）；
  3. 有效误报率 = 人工复核判定"规则错了"的 conflict / 全部 conflict（Google 口径）；
  4. 修复成功率与修后回归率 = 一轮修复后该规则转绿的比例、以及其他规则由绿转红的比例（VRR-Stop、The Verifier Tax 的关注点）。
- 规则集的回归测试应有两套固定样本：gold 合法行程（任何 block 规则都不该触发，对应 TREK 的做法）和每条规则各自的最小违规样例（应触发，对应 Anthropic 的 should-trigger / should-not-trigger）。
- 改规则要升版本号并在评测记录里写明规则集版本，否则不同批次的通过率不可比（AWS 的不可变版本做法）。

### Gaps
- 没有找到旅行、地图或配送公司（Booking、Expedia、Trip.com、Uber、DoorDash 等）公开描述"行程/订单校验规则引擎"严重度分档、规则版本或误报追踪的工程博客；检索只命中 Google Research 的 trip ideas 文章（没有规则治理细节）和个人项目文章（不采用）。
- 没有找到论文或工程文章给出"规则集随失败案例增长"的量化曲线（例如每新增多少失败案例新增多少规则、覆盖率如何变化）。
- Google 的 Not useful 禁用阈值没有公开数值。

---

## 5. 确定性检查 vs LLM judge 在正确性类检查上的证据（准确率、成本、延迟）

### Takeaway
正确性类判断上，现有证据一致指向"确定性检查精度高、可复现、几乎零成本，但召回受规则覆盖面限制；LLM judge 覆盖面广，但在客观对错上接近随机、易被表面线索带偏、并且会给出假阳性"——JudgeBench（ICLR 2025）里强模型只比随机略好；旅行领域 2026 的新 benchmark（TREK、TravelEval、Trip+ 的可行性部分、TRIP-Bench）都选择了全规则评测正确性，LLM judge 只留给个性化、体验这类主观维度。
成本与延迟的量化对比多数来自博客估算而非对照实验，引用时必须标注。

### Cited Findings

**LLM judge 在客观正确性上的可靠性**
- JudgeBench（ICLR 2025）：针对事实与逻辑正确性的 judge 评测，许多强模型（如 GPT-4o）只比随机猜测略好 — [arXiv 2410.12784](https://arxiv.org/pdf/2410.12784)、[ICLR 2025 proceedings PDF](https://proceedings.iclr.cc/paper_files/paper/2025/file/9e720fce64f91114c49cfd640d821da3-Paper-Conference.pdf)。
- AgentRewardBench（arXiv 2025）：1,302 条专家标注的 web agent 轨迹、12 个 LLM judge，没有一个在所有 benchmark 上都好；常用的规则评测倾向于**低估**成功率 — [arXiv 2504.08942](https://arxiv.org/abs/2504.08942)。【二手】规则评测器 precision 83.8 / recall 55.9，GPT-4o judge recall 83.1，没有 judge 的 precision 超过 70% — [Stanford 综述博客](https://web.stanford.edu/~shuhuiq/blog/review-checking-agents.html)。
- 【二手】以下数字均来自 [Stanford 综述博客（2026-10）](https://web.stanford.edu/~shuhuiq/blog/review-checking-agents.html)的转述，未回原文核对：
  - 规则型验证器 precision 超过 99%，recall 最低到 0.78；模型型验证器静态测试更准，但在 RL 训练中会被极短的输出骗过（Huang et al.，arXiv 2025）。
  - 无内容的 token 可把 judge 假阳性率推高到 80%（Zhao et al.，arXiv 2025）。
  - 只改写 agent 的思维链就能把 judge 假阳性率最多抬高 90%（Khalifa et al.，arXiv 2026）。
  - GPT-4 自我批评使图着色准确率从 16% 降到 2%；外部 sound 反馈把 Blocksworld 准确率提到 87%（Stechly et al.）。
  - GPT-4 接受了 45 个无效 Blocksworld 计划中的 38 个（Valmeekam et al.）。
  - GPT-4 judge 与人类偏好一致率超过 80%，但交换顺序后只有 65% 的配对保持原判（Zheng et al.，NeurIPS 2023 D&B）。
  - 构造的压力测试里，5 轮修复把真实有效性从 0.700 降到 0.116，55% 的实例是正确答案被修成错误（Wu et al.，即 VRR-Stop）。
- 该博客作者自测（20 个规划任务、142 条需求标签，小样本、置信区间宽）：LLM judge 与标签一致率 72–83%，确定性核查器 44%（因其对 39% 已满足的需求弃权）；但两个非推理 judge 各接受了 6 条被破坏的需求，确定性核查器一条都没误接受 — [同上](https://web.stanford.edu/~shuhuiq/blog/review-checking-agents.html)。

**旅行领域的做法**
- TREK：完全确定性评测，无 LLM judge、无嵌入、无学习阈值、无网络；gold 方案得 1.0 — [arXiv 2607.26977](https://arxiv.org/html/2607.26977)。
- TravelEval：22 个指标全部规则化；两个代码基线的预算合规率（62.73%、92.17%）远高于 LLM（< 40%）— [arXiv 2606.01046](https://arxiv.org/html/2606.01046)。
- Trip+：可行性、硬约束、软偏好用确定性规则；体验分用 4 个不同家族的 LLM judge 取中位数，并用 Spearman、Cronbach's α 与 50 例人工核验做可靠性检查 — [arXiv 2606.21169](https://arxiv.org/html/2606.21169)。
- TP-RAG：把 LLM judge 用在"时刻是否合理、POI 是否相关"上，与人工一致率 93.70–97.55%（100 份计划）— [arXiv 2504.08694](https://arxiv.org/html/2504.08694)。
- TripTailor：LLM 只做要素抽取，判定交给脚本；个性化才用 LLM judge 与 reward model — [arXiv 2508.01432](https://arxiv.org/html/2508.01432v1)。
- TravelBench：单/多轮质量用 LLM judge（1–5 分）+ meta-judge（约 3% 触发）+ 工具调用错误率的规则惩罚；Unsolvable 用规则 — [arXiv 2512.22673](https://arxiv.org/html/2512.22673)。
- ATLAS：Checker 是 LLM；作者自己把换成正式 CSP solver 列为提高稳健性的方向 — [arXiv 2509.25586](https://arxiv.org/html/2509.25586)。
- LLM-Modulo 旅行案例：增益归因于可靠的 critic；critic 子集明显弱于全集 — [arXiv 2405.20625](https://arxiv.org/html/2405.20625v1)。

**反馈来源对修复效果的影响**
- ContextCov：可执行检查反馈的约束合规 88.3%，prompt-only 67.0%，LLM reflection 50.3%，且反馈成本低 3.4 倍 — [arXiv 2603.00822](https://arxiv.org/abs/2603.00822)。
- Iti-Validator：LLM 自我修正（3 次重提示）被作者判定不可靠而弃用，确定性修正一遍就把无效率降到 0% — [arXiv 2510.24719](https://arxiv.org/html/2510.24719v1)。
- AgentLTL：用时序逻辑在轨迹上得到确定性、无 judge 的合规分 — [arXiv 2607.02599](https://arxiv.org/abs/2607.02599)。

**成本与延迟**
- ChinaTravel：ReAct one-shot + GPT-4o 每条查询 $2.43；符号搜索 + DeepSeek $0.003（这是规划成本对比，不是 judge 成本）— [arXiv v5](https://arxiv.org/html/2412.13682v5)。
- Replan/Repair/Edit：无 LLM 的经典修复 0 token、2.05s；LLM 局部编辑每例约 1.9–2.4 万 tokens、8–14s — [arXiv 2609.19654](https://arxiv.org/html/2609.19654)。
- PAJAMA（arXiv 2025）：让 LLM 合成可执行的判定程序来代替逐条 LLM 打分；搜索摘要称蒸馏后在 RewardBench 的 CHAT-HARD 子集上优于 LLM-as-a-judge，成本低三个数量级（未回原文核对）— [arXiv 2506.10403](https://arxiv.org/pdf/2506.10403)。
- Anthropic：code-based grader 快、便宜、客观、可复现、易调试，但对合法变体脆弱、缺乏细腻度；model-based grader 灵活、能处理开放输出，但非确定、更贵、需要与人工校准 — [Anthropic Engineering](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)。
- 【博客估算，非对照实验】分层评测（先确定性、后 judge）成本约低 10 倍，多数运行延迟 < 10ms，而每次 judge 调用约 2–5s — [DEV Community 文章](https://dev.to/saurav_bhattacharya/deterministic-checks-vs-model-as-judge-a-tiered-approach-to-agent-evaluation-3217)。
- AWS：自然语言翻译成逻辑这一步用多个 LLM、可能出错；逻辑校验这一步是 sound 的；按校验请求计费，不论结果类型 — [AWS 文档](https://docs.aws.amazon.com/bedrock/latest/userguide/automated-reasoning-checks-concepts.html)。

### Inferences
- "正确性只由确定性规则判定"的既定决策与 2026 旅行 benchmark 的主流做法一致（TREK、TravelEval、Trip+ 的可行性层、TRIP-Bench 的 strict/loose），并有 JudgeBench 这类通用证据支撑。
- 确定性规则的代价是**召回**：AgentRewardBench 的结论是规则评测低估成功率，Stanford 博客自测的确定性核查器对 39% 已满足需求弃权。所以对外报告通过率时应同时报 unknown 率和可机检覆盖率，否则"通过率高"可能只是"查得少"。
- LLM 在这条链路里合适的位置是**把自由文本抽成结构**（TripTailor 的要素抽取、ChinaTravel 的 NL2DSL、AWS 的翻译步骤），而不是下判定；并且抽取这一步本身要有可度量的错误率（AWS 用多模型一致率，ChinaTravel 报结构对齐率）。
- 规则判不了的主观维度（体验、个性化）若将来要评，Trip+ 的"多家族 judge 取中位数 + 人工抽检"与 TP-RAG 的"人工一致率 93–97%"给出了可参照的校准方式；这与"正确性不用 LLM"并不冲突，因为评的不是正确性。

### Gaps
- 没有找到在**行程校验**这一具体任务上，对同一批计划同时跑确定性规则与 LLM judge 并报告准确率、成本、延迟的顶会对照实验；最接近的是 TP-RAG 的 judge–人工一致率（不含规则对照）和 Stanford 博客的小样本自测。
- TimeWarp（NeurIPS 2026 E&D）被搜索摘要描述为"确定性验证器与 judge 一致率 99.87%"，但我打开的 arXiv 摘要页没有这个数字，未能核实，不应引用。
- PAJAMA 的"三个数量级"与"47.25 倍更快"两个数字都只见于搜索摘要，未回原文核对。
- AgentRewardBench、Huang et al.、Zhao et al.、Khalifa et al.、Stechly et al.、Valmeekam et al. 的具体数字均为二手转述。
- 没有找到 2026 顶会论文专门量化"确定性校验 + 有界修复循环"在旅行规划上的延迟开销。

---

## 6. 实践经验中的硬性规则

> 本节按开发者反馈补充：该建哪些规则应来自旅行从业与出行实践（产品与工程文章、对 AI 行程的测评与投诉、旅行社与官方规范、旅行者经验帖），而不是从学术 benchmark 推出。第 1–5 节是论文侧材料，本节是实践侧材料；两者不一致时以本节和开发者决定为准。
> 来源类型：【公司】做行程产品的团队写的产品/工程文章；【测评】对 AI 行程的测评、投诉与事故报道；【运营/官方】旅行社、领队、交通企业与政府机构的规范或清单；【旅行者】旅行者经验帖与旅行指南站。
> 带 † 的来源只看到搜索摘要，原页没有打开（打不开或未单独打开），计数时单列为"+n†"。
> 计数范围是本次收集到的约 60 个来源，不是系统抽样，只能说明相对频度。

### Takeaway
实践来源里被提到最多的失败是：到了发现不营业（定休日、营业时间、午休、长期停业）、点与点之间留的时间不够（真实交通、换乘、堵车）、高峰期没算进去、行李与换酒店没安排、地点不存在或已停业、需要预约却没约、一天排太满；前两类各有 14 个已打开的独立来源，都能写成确定性规则。
"雨天 → 室内"在来源里表现为"AI 默认不下雨"的投诉和"事先备好雨天方案"的从业做法，但没有任何来源给出"降水概率到多少必须改室内"的数值，只找到日本人带伞的阈值调查（30–40% 与 50–60% 两档），阈值需要产品自己定。

### Cited Findings

#### 6.1 来源台账

| ID | 类型 | 来源 | 日期 | 状态与备注 |
|---|---|---|---|---|
| [C1] | 公司 | Google Research《Optimizing LLM-based trip planning》（Search 的 AI trip ideas） | 2025-06-06 | 已打开 |
| [C2] | 公司 | NAVITIME Travel「AI会話インポート」（トラベルボイス报道） | 2026-09-16 | 已打开 |
| [C3] | 公司 | Roadanza 自驾行程规划器的校验引擎（MetaProject 博客） | 2026-10-01 | 已打开 |
| [C4] | 公司 | ValidaTrip 行程校验器作者自述（DEV Community） | 5 月 21 日，年份未显示 | 已打开 |
| [C5] | 公司 | MonkeyEatingMango《43% of AI-Planned Days Carry a Fault》 | 2026-09-08 | 已打开；厂商用自家产品的线上数据做的自评，356 份行程、2,735 个行程日 |
| [C6]† | 公司 | TripGenie 的 Google Cloud 客户案例 | — | 仅搜索摘要 |
| [C7]† | 测评 | 虎嗅对飞猪"问一问"、马蜂窝 AI 的实测 | 2025-05-07 | 仅搜索摘要 |
| [R1] | 测评 | SEO Travel 对 ChatGPT 行程的测试（Travolution 报道） | 2024-05-10 | 已打开；营销公司做的测试，ChatGPT-3.5，10 城各 10 份两日行程 |
| [R2] | 测评 | BBC《The perils of letting AI plan your next trip》（经 ZME Science 转述；另见 [R2b] AI Incident Database 条目） | BBC 2025-09-26；转述 2025-10-01 | BBC 原页抓取被拒，读的是转述 |
| [R3] | 测评 | Elliott Report《Can I trust AI to give me good travel advice?》 | 2025-09-28 | 已打开 |
| [R4] | 测评 | 央视新闻《AI生成的旅游攻略，究竟靠谱吗？记者实测》（光明网转载） | 2026-11-01 | 已打开 |
| [R5] | 测评 | 钛媒体《假期出游，我被AI坑惨了》 | 2026-05-03 | 已打开 |
| [R6] | 测评 | Coleman Concierge 汇总的 Reddit 旅行者反馈 | 未显示 | 已打开；部分为二手转述 |
| [R7] | 测评 | ハウスケアラボ《ChatGPTを旅行プランナーにする実践術》 | 2026-07/08 | 已打开；企业运营的生活媒体，数值是作者个人目安 |
| [R8]† | 测评 | 虎嗅（国庆 AI 攻略受访者反馈） | — | 打开返回 405，仅搜索摘要 |
| [R9]† | 测评 | 虎嗅（AI 推荐已倒闭餐厅） | — | 仅搜索摘要 |
| [R10]† | 测评 | Euronews（AI 生成的旅游网站把游客引到不存在的温泉） | 2026-01-30 | 仅搜索条目 |
| [R11]† | 测评 | 澎湃对四款 AI 旅行产品的横评 | — | 打开返回 403，仅搜索摘要 |
| [O1] | 运营/官方 | JNTO《Making reservations》 | — | 已打开 |
| [O2] | 运营/官方 | JR 東海 特大荷物（oversized baggage）规则 | — | 已打开 |
| [O3]† | 运营/官方 | ANA 国际线机场手续注意事项 | — | 连接被重置，仅搜索摘要 |
| [O4]† | 运营/官方 | 国土交通省 貸切バス交替運転者の配置基準 | 约 2013 | PDF 无法解析，仅搜索摘要；是否为现行版本未确认 |
| [O5]† | 运营/官方 | 環境省 熱中症警戒アラート / 暑さ指数资料 | — | 仅搜索摘要 |
| [O6] | 运营/官方 | クラブツーリズム导入 NAVITIME「行程表クラウド」（トラベルボイス，PR） | 2024-02-29 | 已打开 |
| [O7] | 运营/官方 | 旅行社与巴士公司谈巴士旅游行程表安全（トラベルボイス，PR） | 2026-07-01 | 已打开 |
| [O8] | 运营/官方 | TripToJapan.com《规划日本行程要避免的 15 个错误》（东京都登记的旅行社） | 2025-12-29 | 已打开 |
| [O9] | 运营/官方 | GoWithGuide《Japan Tour for Seniors》（导游预订平台，带推广性质） | 2026-06-21 | 已打开；步数与景点数是作者估计 |
| [O10] | 运营/官方 | LIVE JAPAN《Japan's Top Tourist Pitfalls, According to a Tour Conductor》 | 2025-05-01 | 已打开 |
| [O11] | 运营/官方 | 日本旅行《子連れ旅行ガイド》 | — | 已打开 |
| [O12] | 运营/官方 | Rezdy《The Tour Operator's Itinerary Checklist》 | 2014-05-16 | 已打开；无数值 |
| [O13]† | 运营/官方 | Softrip 行程设计建议 | — | 仅搜索摘要 |
| [O14]† | 运营/官方 | 東横INN FAQ | — | 仅搜索摘要 |
| [O15]† | 运营/官方 | Prince Hotels FAQ | — | 仅搜索摘要 |
| [O16]† | 运营/官方 | 富士登山オフィシャルサイト FAQ | 2025 季 | 仅搜索摘要 |
| [O17]† | 运营/官方 | JAL 国际线搭乘手续（最短衔接时间） | — | 仅搜索摘要 |
| [O18]† | 运营/官方 | VELTRA 金沢「雨の日編」模板行程 | — | 仅搜索摘要 |
| [O19]† | 运营/官方 | 星野リゾート「雨の日」指南栏目 | — | 仅搜索条目 |
| [O20]† | 运营/官方 | JR東海ツアーズ 某团体行程表（雨天照常、内容随天气变更） | — | 仅搜索摘要 |
| [O21]† | 运营/官方 | JRPass 博客：台风时的計画運休 | — | 仅搜索摘要；商业站点 |
| [O22]† | 运营/官方 | HIS 国内旅行文章（高龄与轮椅出行） | — | 仅搜索摘要 |
| [O23]† | 运营/官方 | 千葉県关于標準旅行業約款「旅程保証」的说明 | — | 仅搜索摘要 |
| [G1] | 旅行者 | japan-guide.com Golden Week | — | 已打开 |
| [G2] | 旅行者 | japan-guide.com New Year | — | 已打开 |
| [G3] | 旅行者 | japan-guide.com Takuhaibin | — | 已打开 |
| [G4] | 旅行者 | japan-guide.com Typhoons | — | 已打开 |
| [G5] | 旅行者 | japan-guide.com Rainy Season | — | 已打开 |
| [G6]† | 旅行者 | japan-guide.com Shinkansen | — | 仅搜索摘要 |
| [G7] | 旅行者 | tsunagu Japan《Average Opening and Closing Times of Stores in Japan》 | 2024-08-15 更新 | 已打开 |
| [G8] | 旅行者 | LIVE JAPAN《規劃日本行程的萬用清單》 | 2026-05-28 | 已打开 |
| [G9] | 旅行者 | Time Out Tokyo 热门场馆订票指南 | 2024-08-06 | 已打开 |
| [G10] | 旅行者 | FUN! JAPAN（JTB）《What To Do If You've Missed Your Last Train in Japan》 | 2019-06-17 更新 | 已打开 |
| [G11] | 旅行者 | ウェザーニュース 带伞判断基准调查 | 2024-06-13 | 已打开 |
| [G12] | 旅行者 | Oggi 转载的 LINEリサーチ 带伞调查 | 调查 2021-02 | 已打开 |
| [G13]† | 旅行者 | コトバンク「日本のおもな美術館」休馆日表记 | — | 仅搜索摘要 |
| [G14]† | 旅行者 | japan-guide.com Tateyama Kurobe Alpine Route | — | 仅搜索摘要 |
| [G15]† | 运营/官方 | 気象庁 降水確率的定义 | — | 仅搜索摘要 |
| [T1] | 旅行者 | 少数派《赴日前你需了解这些事》 | 2025-06-06 | 已打开 |
| [T2] | 旅行者 | Rexby japantrips《Common Mistakes Travelers Make in Japan》 | 未显示 | 已打开 |
| [T3]† | 旅行者 | Business Insider 首次赴日者的失误（AOL 转载） | — | 镜像 404，仅搜索摘要 |
| [T4] | 旅行者 | 聯合新聞網《旅日專家盤點 5 大後悔清單》（源自 Business Insider；200 多名外国旅客的 Facebook 社团反馈） | 2026-05-27 | 已打开 |
| [T5] | 旅行者 | HugKum《1028人に聞いた 子連れ旅行、これが困った》 | 2023-04-17 | 已打开 |
| [T6]† | 旅行者 | AZWAY 对 300 名日本国内旅行者的失败经历调查 | — | 原页 404，仅搜索摘要 |
| [T7]† | 旅行者 | Lonely Planet《Japan with kids》 | — | 仅搜索摘要 |

#### 6.2 各领域的实践证据

**营业日与营业时间**
- ChatGPT 行程里 52% 至少有一处排在营业时间之外，24% 推荐了临时或永久关闭的场所，90% 至少有一处错误 — [R1]。
- 2,735 个行程日里 22.7% 有"该时刻不营业"、16.6% 有"游览拖到闭馆之后"；672 处时刻错误中 381 处是开门前到达（中位差 60 分钟）、149 处是关门后到达、113 处是当天是定休日（其中周一 60 处）、28 处落在午间休息 — [C5]。
- 巴黎 Musée d'Orsay 被排在周一闭馆日 — [R3]；美术馆休馆日、到了店几乎都休息 — [R7]；景点开放时间与 AI 说法对不上 — [R5]。
- 乡间店铺打烊早：午餐 11:00–14:00、晚餐 17:00–20:00，平日更短；一家面包店门口写着"营业到 15:00"，名片和 Google Maps 上都没有 — [O10]。
- 日本独立餐厅常见 11:00–14:00 与 17:00–23:00 两段、中间休息，最后点餐约在关门前 30 分钟；博物馆约 10:00–18:00；水族馆与动物园约 9:00–17:00、最终入场在闭馆前 30 分钟；办公区咖啡店周末常休 — [G7]。
- 年末年始：12 月 29 日至 1 月 4 日之间许多景点、商店、餐厅、银行休一天或多天，1 月 1 日最普遍；博物馆常连休数日；寺社不休 — [G2]。
- 餐厅一周只开几天、部分景点只在特定季节营业 — [G8]；草間彌生美術館只在周四至周日与节假日开放 — [G9]。
- 日本国内旅行者的失败经历里，"当地店铺或设施定休或在营业时间外"排在前几位 — [T6]†；美术馆休馆日常写作"周一（逢节假日顺延到次日）" — [G13]†。
- 做产品的团队都把这一条写成代码检查：按行程日期核对营业时间并标记每周定休与季节性关闭 — [C4]；营业时间必须匹配、永久停业的排除 — [C3]；用实时营业时间做 grounding — [C1]；显示含营业时间的实在地点信息 — [C2]。

**地点是否真实存在、是否已停业**
- 北京西站的"护国寺小吃"分店并不存在，最近的分店步行 50 多分钟；香山索道因改造停运 — [R4]。
- 秘鲁"Sacred Canyon of Humantay"不存在，游客花近 160 美元被送到乡间公路；"北京的埃菲尔铁塔"；一条步道已关闭 18 个月 — [R2]。
- 大阪某博物馆的"1:1 复原"与"织布体验"并不存在，白坐一个多小时公交；推荐餐厅已关门 — [R5]。
- 一座正在整修的寺院、已关几个月的咖啡店、已不存在的餐厅 — [R3]。
- 13 处永久或临时关闭，包括 2024 年火灾中烧毁的輪島朝市 — [C5]；柏林 Pergamon Museum 闭馆至 2026 年仍被推荐 — [R1]。
- 12 公里的路段被算成 988 公里、Zaragoza 被解析到 New York；之后加了"解析位置偏离预期 600 公里以上即拒绝" — [C3]。
- 产品侧做法：把每个地名解析到真实场所 — [C4]；与自有地点数据自动照合 — [C2]。

**点与点之间的交通时间、换乘与堵车**
- 一段公交堵车超过 65 分钟，香山游览被压缩约三分之一，5 处景点只看了 3 处；推荐的公交不停靠指定入口，下车后还要步行约半小时 — [R4]。
- 返程被说成 200 多公里，实际约 400 公里；"没多远"实际步行约 6 公里 — [R5]。
- "离埃菲尔铁塔步行 10 分钟"的餐厅实际 20 分钟以上；日本行程里渡轮时刻错误、交通时间偏乐观 — [R3]。
- 日本滑雪行里推荐的温泉与实际巴士时刻对不上，旅客被困雪中改打车 — [R2]。
- 跨县移动被假设成 30 分钟 — [R7]；规划者低估退房、运行李、找站台、办入住的耗时 — [R6]。
- 新宿站有 200 多个出口，初到者找山手线入口花了一小时 — [T1]；同一例子也出现在 200 多名旅客的后悔清单里 — [T4]。
- 景点间实际交通时间通常比地图显示的长 — [O8]；预约之间要留足移动时间，日本城市穿城比预想久 — [O1]。
- 巴士旅游：一般地图与车载导航按小客车算路，大型巴士走不了，会低估时间并导致中途绕行；按出行日期的拥堵预测比较各段时间与回程时刻 — [O6]。
- 国庆期间实际车程比 AI 预估长一倍多 — [R8]†。
- 产品侧做法：用实时交通时间核对并给不可行的日程打 0 分 — [C1]；用时刻表、车站与高速出入口信息、各点停留时间算路 — [C2]。

**一天内的顺序与折返**
- 25% 的行程需要折返或绕路，例如迪拜为了早餐绕 12 英里 — [R1]；9.5% 的行程日存在折返，中位多走 3.4 公里，最差 40 公里 — [C5]。
- 景区观光车不在 AI 安排的第一站停靠，游览顺序走不通 — [R5]；同一下午横穿城市两次 — [C4]；LLM 把相邻景点排成需要不必要穿城的顺序，由优化步骤重排 — [C1]。
- 按区域分组，一天集中在两三个相近的地方 — [T2]；用地图核对无谓的往返 — [R7]；用巡回路径搜索算最优访问顺序 — [C2]。
- 把相距很远的景点排在同一天 — [R8]†。

**排太满与每日节奏**
- AI 攻略默认换乘无缝、路况畅通、不下雨、不排队，所以行程往往排得很满、难以完成 — [R4]（中国社科院旅游研究中心专家）。
- 同一天排 Disney 和 teamLab；同一天排宮島、広島城、縮景園 — [R6]。
- 带孩子时孩子睡着就打乱计划，受访家长的总结是留足时间 — [T5]。
- 一周内跑东京、京都、大阪、奈良甚至广岛，时间耗在交通上；每天 15,000–25,000 步 — [T4]。
- "予定を詰め込みすぎて疲れた"是日本国内旅行者第二常见的失败，最常被提到的对策是不要排太满 — [T6]†。

**预约与限时入场**
- 日本行程里推荐的限时入场博物馆已售罄、一家餐厅已改为只接受预约 — [R3]；AI 没写是否需要预约 — [R7]；限时入场景点在出发前就卖完 — [C4]。
- JNTO 列出的需预约项：新幹線与部分特急、高速巴士、東海道・山陽・九州新幹線的大件行李位、许多餐厅、teamLab Borderless、京都西芳寺等寺社、导览与体验；许多景点采用预定入场时段；部分线上预约要求提前 24–48 小时确认；餐厅用餐时间常限 2 小时左右，迟到会影响套餐上菜 — [O1]。
- 三鷹の森ジブリ美術館每月 10 日 10:00（JST）开售次月票，周末场次通常十分钟内售罄；草間彌生美術館每月 1 日 10:00 开售隔月票且不设现场售票；Tokyo Disney 不设当日窗口售票；teamLab 按半小时入场时段售票；豊洲市場金枪鱼拍卖参观约提前一个月抽签 — [G9]。
- 吉卜力公园、相扑、山崎蒸馏所也需提前订；许多饭店 90 天前不开放预订 — [G8]。
- 热门餐厅需提前数周到数月，晚 6–8 点最挤，部分只接受日语电话预订 — [O8]；非连锁餐厅多需预约 — [T1]。
- 预约了较晚的入场时段，前几个展厅看太久，没看完就闭馆，想重买时已全部订满 — [T3]†。

**酒店入住/退房与行李**
- 多数酒店 10:00 退房、一般不提供提前入住；部分传统旅馆或民宿 22:00 后不再接待入住，作者曾因到店时前台已下班而遇到麻烦 — [T1]。
- 東横INN 16:00 入住、10:00 退房 — [O14]†；Prince Hotels 15:00 起入住、11:00 前退房 — [O15]†。
- 宅急便通常次日送达，北海道、冲绳等远距离要两天以上 — [G3]；通常至少需要 24 小时 — [G8]；车站寄存柜约 300–800 日元/天，许多酒店退房后可代存 — [O8]。
- 東海道・山陽・九州・西九州新幹線：三边合计 160 cm 以内无需预约；161–250 cm 必须预约带特大行李位的座位；超过 250 cm 不能带上车；没预约带上车收 1,000 日元，满座时可能被要求改乘后面的车 — [O2]。
- 度假地退房时段（约 8:30–10:00）出租车可能全被订满 — [O10]；ChatGPT 建议在阿姆斯特丹和柏林每晚换一家酒店 — [R1]；"每天都换酒店"被列为危险信号 — [R7]。
- 拖着行李步行 15 分钟很快就累 — [O8]；古城石板路上行李箱难行，AI 没提示 — [R5]；带孩子旅行最常见的困扰是行李多 — [T5]。

**机场与车站的时间余量、末班车**
- 国际线（ANA）：柜台值机在起飞前 60 分钟截止，60 分钟前应通过安检，30 分钟前到登机口，10 分钟前未到登机口不能登机；年末年始、黄金周、盂兰盆节机场拥挤，需额外留时间 — [O3]†。
- 国内线：起飞前 45 分钟到 1 小时到机场较稳妥，托运行李 20 分钟前、安检 15 分钟前、登机口 10 分钟前 — [O11]。
- 羽田与成田之间转机至少 180 分钟 — [O17]†。
- ChatGPT 说宮島弥山的末班缆车 17:30 发车，旅客看完日落到山顶站时缆车已停运，被困山顶 — [R2]。
- 大阪摩耶山缆车工作日 17:00 停运，按 AI 行程无法下山；某县城高铁站大巴 AI 说开到 21:30，实际 18:00 停运，改打车 195 元，大巴只要 10 元 — [R5]。
- 日本没有通宵电车，从大城市出发的末班车最早 22 点就没有了，5 点恢复；市内打车回酒店约 2,000–5,000 日元，东京到埼玉一小时车程可达 40,000 日元 — [G10]。
- 旺季巴士会晚点或满员上不去；乡下打车软件可能不可用 — [O10]。

**长距离移动与每日移动量**
- 作者目安：一天总移动时间 3 小时左右，超过 4 小时是危险信号；带孩子时移动加停留每段 90–120 分钟以内 — [R7]。
- 自驾：按节奏分 250 / 400 / 600 km 的每日驾驶上限，单日驾驶 6 小时以上给提示 — [C3]。
- 东京至少 3–4 天、京都至少 3 天；从东京去富士山一日游要整整一天 — [O8]；各城市建议停留天数与各类景点参考时长（主要寺社 30–60 分钟、博物馆 2–4 小时、古城 1–3 小时、公园 1–3 小时）— [G8]。
- 巴士旅游的法定约束：一趟运行实车距离超过 400 km（采取特别安全措施并公示的为 500 km）或驾驶员一天乘务时间超过 10 小时须配交替驾驶员；一天驾驶时间上限按两天平均 9 小时 — [O4]†。
- 巴士行程延误时的处置实例：缩短午餐时间并砍掉一个停靠点，以保证按时回到终点 — [O7]。

**天气与季节**
- 专家点评 AI 攻略默认"不下雨" — [R4]；AI 建议阴雨天去高原，未提示严寒；中午去无遮阴景点，忽略午后高温；没提醒强紫外线 — [R5]。
- 梅雨平年期间：冲绳 5 月 8 日–6 月 23 日，关西 6 月 6 日–7 月 19 日，关东 6 月 8 日–7 月 20 日；东京梅雨高峰时某一天下雨的概率约 45%；寺院、庭园、温泉被列为适合雨天的去处 — [G5]。
- 带伞阈值：LINEリサーチ（2021 年，5,252 人）里"降水确率 50–60% 左右就带伞"占 31%，"30–40% 左右"占 30% — [G12]；ウェザーニュース（2024 年，10,440 名 App 用户）里以降水确率为首要判断依据的人多以 30–40% 为界 — [G11]。
- 降水確率指该时段内降水 1 mm 以上的概率 — [G15]†。
- 从业侧把雨天方案做成现成产品：金沢「雨の日編」模板行程 — [O18]†；酒店集团的"雨の日"指南栏目 — [O19]†；团体行程表写明雨天照常出发、内容随天气变更 — [O20]†。
- 台风多在 5–10 月，8–9 月最多；每年约 3 个登陆本土；强台风会让航班、列车停运、高速封闭；建议行程留机动 — [G4]；遇台风避开山区和海岸线 — [T1]。
- 暑さ指数（WBGT）31 以上为"危险"，建议尽量避免外出、移到凉爽室内；预测 33 以上时发布熱中症警戒アラート，前一天 17 点和当天 5 点各发布一次 — [O5]†。
- 夏季高温下坡道、台阶、长参道更吃力 — [T4]；长者应避开 7–8 月 — [O9]。
- 季节性开放：立山黒部アルペンルート全线约 4 月中旬至 11 月 30 日 — [G14]†；富士山吉田路线 7 月 1 日–9 月 10 日、其余三条 7 月 10 日–9 月 10 日（2025 年），通行费 4,000 日元，没有山小屋预约者 14:00 后不能通过登山口 — [O16]†。
- 樱花、红叶季的山区白天暖、夜里冷 — [O10]。

**节假日与人流**
- 黄金周由 4 月 29 日、5 月 3–5 日组成；列车、机场、景点都很挤，景区住宿会提前很久订满 — [G1]。
- 年末年始出城高峰 12 月 29–31 日、返程 1 月 2–4 日；明治神宮、伏見稲荷大社等初詣要排一小时以上 — [G2]。
- 新年、黄金周、盂兰盆期间 Nozomi 全车指定席，高峰日会提前数天售罄 — [G6]†。
- 尽量避开黄金周、盂兰盆节（8 月中旬）、年末年始 — [T1]；订票时避开黄金周与盂兰盆，樱花季为 3 月下旬到 4 月上旬 — [O1]；黄金周或樱花季的机票住宿建议提前 3–6 个月 — [G8]。
- 樱花季热门景点挤满人、住宿涨价、餐厅大排长龙 — [T4]；红叶旺季香山堵车 — [R4]。
- 通勤高峰：7:30–9:00 应避开大站 — [O9]；工作日约 7:00–9:00 与 17:00 之后 — [G7]。

**餐饮**
- 第一站早餐店不存在，记者只能空腹出发 — [R4]；三顿饭风格几乎一样 — [R5]。
- 作者目安：一天 2–3 餐、每餐留 60 分钟，行程里没写用餐时间是危险信号 — [R7]；午餐窗口 12:00–15:00、晚餐 18:00–21:00 — [C3]。
- 30% 的行程不顾花费塞进了米其林星级餐厅 — [R1]。

**同行人**
- 作者目安：带孩子或带老人一天 3 处，夫妻 4–5 处，6 处以上危险；带孩子至少安排一次连住 — [R7]。
- 长者：一天 2 处（上午、下午各一）；长者向私人团约 3,000–5,000 步/天，普通团约 15,000 步、4–5 处；活动与休息 1:1；不要早上 6 点起；酒店离车站步行 5 分钟内并确认有电梯 — [O9]。
- 带孩子：配合孩子睡觉的时段选新幹線或航班；选高峰前后人少的班次；行李先寄到住处 — [O11]。
- 婴儿车：到电梯要绕远、只有楼梯、人行道少 — [T5]；老车站没有电梯、寺社多台阶，很多家庭改用背带 — [T7]†。
- 新幹線行李架放重物对长者有风险，轮椅需事先告知尺寸与能否折叠 — [O22]†。

**预算与现金**
- 河口湖、箱根、日光、高野山许多店只收现金，便利店和 ATM 少，应在机场或城市先取好，带千元钞和硬币 — [O10]；建议带 10,000–20,000 日元现金 — [O8]；老字号与乡下依赖现金 — [G8]；部分岛屿 ATM 不支持银联取款 — [T1]。
- ChatGPT 推荐的酒店比三个街区外同评分的贵约 40% — [R3]；住宿要确认住宿税、入汤税与退改条款 — [T1]。
- "花超了/超预算"在日本国内旅行者的失败里排前三 — [T6]†。

**其他**
- 多日行程里同一地点被重复安排：5.1% 的行程日受影响，1–3 天行程 6.2%，15 天以上 56.2% — [C5]。
- 用户列为必须的项目被漏掉（阿拉斯加直升机行程）；24 小时没睡之后紧接着排自驾 — [R2]。
- 巴士旅游里上下车地点只写地名会认错，改为在地图上精确标点并与巴士公司事前确认 — [O7]；AI 指定的入口与可用公交站不匹配 — [R4]。
- 旅行社合同层面：合同书面记载的住宿机构被换成另一家时，旅行社须支付变更补偿金 — [O23]†。
- 携程 TripGenie 的云厂商案例称用 Grounding 降低搜索结果里的幻觉风险 — [C6]†；虎嗅实测称飞猪为"问一问"接入了实时报价引擎、马蜂窝提供多年积累的真实旅行数据，但攻略里仍出现已关闭的店铺，以及下午才到达却照常排满的时间安排 — [C7]†。

#### 6.3 来源给出的具体阈值（只收来源明写的数字）

| 主题 | 阈值 | 来源 | 性质 |
|---|---|---|---|
| 把哪天当"雨天" | 降水确率 50–60% 带伞 31%，30–40% 带伞 30% | [G12] | 5,252 人调查 |
| 同上 | 多以 30–40% 为带伞界线 | [G11] | 10,440 人调查的评论归纳 |
| 梅雨 | 关东 6/8–7/20、关西 6/6–7/19；东京高峰日降雨概率约 45% | [G5] | 气象厅平年值转述 |
| 高温 | WBGT ≥ 31 尽量避免外出；预测 ≥ 33 发布警戒 | [O5]† | 官方，未开页 |
| 台风 | 5–10 月，8–9 月高峰 | [G4] | 指南站 |
| 最终入场 | 水族馆、动物园在闭馆前 30 分钟 | [G7] | 指南站的一般值 |
| 最后点餐 | 约关门前 30 分钟 | [G7] | 同上 |
| 餐厅两段营业 | 11:00–14:00 与 17:00–23:00；乡下晚餐到 20:00 | [G7]、[O10] | 一般值 / 领队经验 |
| 用餐窗口 | 午 12:00–15:00、晚 18:00–21:00 | [C3] | 产品规则 |
| 每餐时长 | 60 分钟 | [R7] | 作者目安 |
| 年末年始闭馆 | 12/29–1/4 之间，1/1 最普遍 | [G2] | 指南站 |
| 黄金周 | 4/29、5/3–5/5 | [G1] | 指南站 |
| ジブリ美術館放票 | 每月 10 日 10:00 JST 售次月 | [O1]、[G9] | 官方 / 指南 |
| 餐厅用餐时限 | 约 2 小时 | [O1] | 官方 |
| 线上预约确认 | 部分须提前 24–48 小时 | [O1] | 官方 |
| 住宿开放预订 | 许多 90 天前不开放；黄金周与樱花季提前 3–6 个月 | [G8] | 指南站 |
| 退房 / 入住 | 退房多为 10:00；入住 15:00 或 16:00 | [T1]、[O14]†、[O15]† | 经验帖 / 酒店 FAQ |
| 最晚入住 | 部分旅馆民宿 22:00 后不接待 | [T1] | 经验帖 |
| 宅急便 | 次日；远距离 2 天以上；至少 24 小时 | [G3]、[G8] | 指南站 |
| 新幹線大件行李 | ≤160 cm 免预约；161–250 cm 须预约；>250 cm 不可；未预约 1,000 日元 | [O2] | 官方 |
| 国际线截止 | 值机 −60 分钟、安检 −60、登机口 −30、−10 拒绝登机 | [O3]† | 航司，未开页 |
| 国内线 | 提前 45–60 分钟到机场 | [O11] | 旅行社 |
| 羽田↔成田转机 | ≥180 分钟 | [O17]† | 航司，未开页 |
| 末班车 | 大城市出发最早 22 点结束，5 点恢复 | [G10] | 指南站（2019） |
| 夜间活动 | 21 点后只在酒店周边 | [R7] | 作者目安 |
| 每日站点数 | 2–4 个主要活动 | [O8] | 旅行社 |
| 同上 | 两三个相近地点 | [T2] | 经验帖 |
| 同上 | 带孩子 3、带老人 3、夫妻 4–5、≥6 危险 | [R7] | 作者目安 |
| 同上 | 长者 2 处；普通团 4–5 处 | [O9] | 作者估计 |
| 同上 | 剩余小时数 ÷ 1.4 h，限制在 2–8 | [C3] | 产品规则 |
| 每日总移动 | 约 3 小时，>4 小时危险 | [R7] | 作者目安 |
| 带孩子单段 | 移动加停留 90–120 分钟内 | [R7] | 作者目安 |
| 步数 | 10,000–20,000；15,000–25,000；长者 3,000–5,000 | [O8]、[T4]、[O9] | 旅行社 / 旅客反馈 / 作者估计 |
| 自驾 | 每日 250 / 400 / 600 km；≥6 小时提示 | [C3] | 产品规则 |
| 观景类时段 | 07:00–20:00 | [C3] | 产品规则 |
| 修复轮数 | 最多 2 次，失败则保留并提示用户 | [C3] | 产品规则 |
| 通勤高峰 | 7:30–9:00；7:00–9:00 与 17:00 后 | [O9]、[G7] | 作者 / 指南站 |
| 现金 | 10,000–20,000 日元 | [O8] | 旅行社 |
| 巴士（仅团队游） | 一趟实车 400 km（500 km）、乘务 10 小时、驾驶 9 小时 | [O4]† | 官方，未开页 |
| 富士登山 | 7/1（7/10）–9/10；14:00 后无山小屋预约不得通过 | [O16]† | 官方，未开页 |
| アルペンルート | 约 4 月中旬–11/30 | [G14]† | 指南站，未开页 |

### Inferences

#### 6.4 候选规则表（按已打开的独立来源数排序）

说明：规则措辞、所需数据与档位是我的建议；"防止的失败"与计数来自 6.1–6.2。档位含义：block = 按原样无法执行或会让人滞留；warn = 能执行但大概率体验差或有额外成本；note = 需要告知用户的事项。计数写作"已打开来源数 + 仅搜索摘要来源数†"。

| # | 规则（一句话） | 防止的失败（来源） | 检查器需要的数据 | 建议档位与理由 | 适用 | 来源数 |
|---|---|---|---|---|---|---|
| P01 | 每个到访时段必须落在该场所当天的营业时段内，含每周定休日、午间休息、节假日顺延与年末年始 | 到了不开门、闭馆后才到、周一休馆（[R1]、[R3]、[R5]、[R7]、[C1]、[C2]、[C3]、[C4]、[C5]、[O10]、[G2]、[G7]、[G8]、[T2]；[R8]†、[T6]†、[T3]†、[G13]†） | 按星期的营业时段、定休日与节假日顺延规则、午休、最终入场时刻、年末年始与临时休业、数据更新时间 | block：进不去就无法执行；[C5] 里它占故障天数最多 | 通用；周一休馆顺延、不定休、12/29–1/4 是日本特有 | 14 + 4† |
| P02 | 相邻两站之间留出的时间不得小于按时刻表或路网算出的实际交通时间，含步行到站与换乘 | 堵车后景点砍掉、跨县按 30 分钟算、巴士时刻对不上被困（[R2]、[R3]、[R4]、[R5]、[R6]、[R7]、[C1]、[C2]、[C3]、[O1]、[O6]、[O8]、[T1]、[T4]；[R8]†） | 带出发时刻的路线时间、换乘步行时间、大站加成、按日期的拥堵系数 | 时间不够为 block；余量小或高峰日为 warn | 通用；大站换乘是日本特有加成 | 14 + 1† |
| P03 | 行程日期落在黄金周、盂兰盆、年末年始、樱花红叶旺季时必须标出，并对交通与住宿预订给出提示 | 车程翻倍、住宿订满、指定席售罄、初詣排队一小时以上（[G1]、[G2]、[G8]、[T1]、[T4]、[O1]、[O6]、[O8]、[O9]、[O10]、[R4]；[G6]†、[O3]†、[R8]†） | 日本节假日历、各年高峰日、樱花红叶时段 | warn：能执行但时间与成本变化大；交通余量并入 P02 | 日本特有日历；机制通用 | 11 + 3† |
| P04 | 换酒店日与带大件行李的时段必须交代行李去向（寄存、宅急便、随身），寄送要满足提前量 | 拖着行李赶景点、石板路拖箱、行李没到、新幹線大件行李没预约（[G3]、[G8]、[O1]、[O2]、[O8]、[O9]、[O11]、[T2]、[T5]、[R5]） | 每晚住宿、行李件数与尺寸、寄送提前量、列车线路是否需要大件行李预约 | warn；161–250 cm 行李上相关新幹線未预约为 note 提醒 | 宅急便与 160 cm 规则是日本特有 | 10 |
| P05 | 行程里每个地点必须能在地点数据里解析到真实且仍在营业的场所，位置与所在城市相符 | 不存在的分店与景点、已倒闭的餐厅、整修中的设施（[R1]、[R2]、[R3]、[R4]、[R5]、[C2]、[C3]、[C4]、[C5]；[R9]†、[R10]†、[C6]†、[C7]†） | 地点 ID、营业状态（永久/临时关闭、整修）、坐标、数据更新时间 | block：没有这个地方就无法执行 | 通用 | 9 + 4† |
| P06 | 需要预约或限时票的项目必须带预约标记、放票规则与入场时段，并核对用户是否已预约 | 限时票售罄、餐厅只接受预约、订了太晚的时段看不完（[R3]、[R7]、[C4]、[O1]、[O8]、[G8]、[G9]、[T1]、[T2]；[T3]†、[R11]†） | reservation_required、放票日与时刻、入场时段、是否现场售票、用户预约状态 | 不预约进不去且已过放票窗口为 block；其余为 note 并给出最晚预约日 | 机制通用；名单是日本特有 | 9 + 2† |
| P07 | 每天的站点数与总时长不得超过按同行人设定的上限 | 5 处只看 3 处、孩子睡着计划全乱、旅客事后最常见的后悔（[R4]、[R6]、[R7]、[T2]、[T4]、[T5]、[O8]、[O9]、[C3]；[T6]†、[O13]†） | 各站停留时长、当日可用时间窗、同行人类型、节奏偏好 | 时长装不下为 block（算术事实）；仅站点数超过参考值为 warn | 通用 | 9 + 2† |
| P08 | 午餐与晚餐必须排在可用餐的时段，且所选餐厅在该时段营业并早于最后点餐 | 早餐店不存在空腹出发、下午 2–5 点没店开、为吃饭绕远（[R1]、[R4]、[R5]、[R7]、[C3]、[G7]、[O1]、[O8]、[O10]） | 餐厅分段营业时间、最后点餐时刻、用餐时长 | warn；餐厅该时段不营业时按 P01 升为 block | 通用；两段营业与最后点餐是日本常态 | 9 |
| P09 | 同一天内的站点应按区域成组，不出现折返 | 横穿城市两次、观光车不停第一站、远距离景点同日（[R1]、[R5]、[R7]、[C1]、[C2]、[C4]、[C5]、[T2]；[R8]†） | 站点坐标、区域归属、当日路线总长与最优顺序的差 | warn：能走完但浪费时间 | 通用 | 8 + 1† |
| P10 | 到店时间必须在酒店可入住时段之内且早于前台最晚接待时间；退房后与入住前的时段不得安排"回房" | 22 点后旅馆不接待、每晚换酒店、退房时段叫不到车（[T1]、[O8]、[O10]、[R1]、[R6]、[R7]；[O14]†、[O15]†） | 入住起始时刻、退房截止时刻、前台关闭时刻、是否可寄存行李 | 晚于最晚接待为 block；其余为 warn | 通用；10:00 退房、15–16 点入住是日本常见值 | 6 + 2† |
| P11 | 每天总移动时间与跨城次数不得超过上限，长距离移动日不再排满行程 | 一周跑五城、时间耗在路上、富士山一日游挤进半天（[R6]、[R7]、[C3]、[T4]、[O8]、[G8]；[O4]†） | 当日各段交通时间之和、城市切换次数、城市最少停留天数参考 | warn | 通用 | 6 + 1† |
| P12 | 当天最后一段回程必须早于末班车；山上、岛上、郊外项目的返程必须早于末班缆车、渡轮或巴士 | 被困弥山山顶、摩耶山下不了山、大巴 18 点停运改打车（[R2]、[R5]、[R7]、[G10]、[O10]） | 各线路末班时刻、缆车与渡轮末班、返程所需时间 | block：后果是滞留或高额打车费 | 通用；电车无通宵运行是日本特有 | 5 |
| P13 | 预报降雨的日子，户外为主的项目必须换成室内项目或附带可执行的室内替代 | AI 默认不下雨、阴雨天排高原与无遮蔽景点（直接：[R4]、[R5]、[G5]；间接：[O8] 只说按季节备雨具，[T2] 只说要有备选；[O18]†、[O19]†、[O20]†） | 分日或分时段降水确率、地点的室内/户外属性、同区域的室内替代清单、预报是否覆盖该日期 | block（开发者已定为硬规则）；预报覆盖不到的日期判 unknown；阈值来源里只有带伞调查的 30–40% 与 50–60% 两档，需产品自定 | 通用；梅雨期是日本特有背景 | 5（其中 2 个只是间接提到）+ 3† |
| P14 | 只收现金的场所与缺少 ATM 的地区要在行程里标出 | 河口湖、箱根、日光、高野山刷不了卡又取不到钱（[O8]、[O10]、[G8]、[T1]、[T2]） | cash_only 属性、所在地区 ATM 可得性 | note：不影响可行性，但要提前告知 | 日本特有程度高 | 5 |
| P15 | 推荐项的价格档位必须与用户预算一致，并把税费与可能的替代成本算进去 | 塞进米其林餐厅、贵 40% 的酒店、错过末班后的打车费（[R1]、[R3]、[R5]、[G10]、[T1]；[T6]†） | 用户预算、各项价格区间、住宿税与入汤税、退改条款 | 超出用户明示预算为 block；仅价格档偏高为 warn | 通用 | 5 + 1† |
| P16 | 高温日不在正午前后安排无遮蔽的长时间户外项目 | 午后高温去无遮阴景点、夏季台阶坡道更吃力（[R5]、[T4]、[O8]、[O9]；[O5]†） | 气温或 WBGT 预报、户外属性、是否有遮蔽、时段 | warn；达到官方"危险"级别是否升为 block 由产品定 | 通用；WBGT 警戒是日本官方口径 | 4 + 1† |
| P17 | 季节性开放的路线、登山、缆车与设施只能排在开放期内，整修停运的不能排 | 索道改造停运、步道关闭 18 个月、冬季封闭的山岳路线（[G8]、[R2]、[R4]、[C4]；[O16]†、[G14]†） | 开放季起止、整修与停运公告 | block | 通用；具体日期是日本特有 | 4 + 2† |
| P18 | 每天步行量与台阶量不得超过按同行人设定的上限 | "没多远"实际 6 公里、每天两万步脚起泡（[O8]、[O9]、[T4]、[R5]） | 各段步行距离、景点内步行与台阶估计、同行人类型 | warn | 通用 | 4 |
| P19 | 带大件行李、婴幼儿或长者的移动避开通勤高峰 | 挤不上车、带行李上满员电车（[O9]、[O11]、[T2]、[G7]；[T7]†） | 移动时段、工作日判断、同行人与行李 | note | 日本大城市特有程度高 | 4 + 1† |
| P20 | 台风季的跨城日要留机动；已发布停运或警报时不排受影响线路与山区海岸 | 航班列车停运、高速封闭（[G4]、[G8]、[T1]；[O21]†） | 台风与警报信息、计划停运公告、行程日期 | 已公告停运为 block；仅处于台风季为 note | 日本特有 | 3 + 1† |
| P21 | 看日落、夜景、徒步等项目的时段必须与日出日落一致，且返程不晚于天黑与末班 | 看完日落下不了山、把日落活动排在中午（[R2]、[C3]、[C5]） | 日出日落时刻、活动类型 | warn；与 P12 同时触发时为 block | 通用 | 3 |
| P22 | 带婴幼儿时限制每日站点数与单段时长，至少安排一次连住，并标出无电梯车站与多台阶场所 | 孩子睡着计划崩、婴儿车进不去（[R7]、[T5]、[O11]；[T7]†） | 同行人年龄、车站与场所的无障碍属性、连住情况 | warn | 通用 | 3 + 1† |
| P23 | 同一地点在整个行程里不重复安排，三餐类型不雷同 | 多日行程重复同一地点、三顿饭几乎一样（[C4]、[C5]、[R5]） | 地点 ID、餐厅类型 | 地点重复为 block；餐型雷同为 warn | 通用 | 3 |
| P24 | 入口、上下车点、购票点要具体到可用的那一个，并与所用交通衔接 | 指定入口没有公交站、入口被封、巴士上下车点认错（[R4]、[R5]、[O7]） | 入口与站点坐标、可达性 | note；入口不可达时为 warn | 通用 | 3 |
| P25 | 21 点以后的活动限制在住宿周边，乡间地区按更早的打烊时间处理 | 深夜长距离移动、乡下晚上无店可去（[R7]、[O10]、[G7]） | 活动时刻、与住宿的距离、地区类型 | warn | 通用 | 3 |
| P26 | 带长者或行动不便者时降低每日站点数与步数，酒店靠近车站并有电梯 | 多台阶寺社走不动、每天换酒店太累（[O9]、[R7]；[O22]†） | 同行人年龄与行动能力、台阶与坡道、酒店到站距离与电梯 | warn | 通用 | 2 + 1† |
| P27 | 离境日最后一个活动结束时刻加上去机场的交通时间，必须早于航司截止时间并留余量 | 误机（[O11]；[O3]†、[O17]†） | 航班时刻、航司截止分钟数、到机场交通时间、是否高峰期 | block：截止时间是硬约束；余量取值来源里没有可用数字 | 通用 | 1 + 2† |
| P28 | 长途飞行或通宵之后不紧接长距离驾驶或满日程 | 24 小时没睡后排自驾、下午才到却排满（[R2]；[C7]†） | 到达时刻、前序航段时长 | warn | 通用 | 1 + 1† |
| P29 | 用户明确要求必须包含的项目不得被漏掉 | 必选的直升机项目被漏（[R2]） | 用户硬需求清单 | block | 通用 | 1 |

#### 6.5 排序与落地说明
- 频度与严重度是两回事：P12（末班）和 P27（航班截止）来源数不高，但后果是滞留或误机，实践来源里最重的两起事故（弥山缆车、摩耶山缆车）都属于 P12，应按 block 处理而不按频度排后。
- 按任务书的描述，现有校验器已有的类别是营业时间、路线间隔与重叠、用餐时段、重复、密度、预算，对应本表的 P01、P02、P07、P08、P15、P23；其余各条任务书没有提到，是否已有需要对照现有规则清单。其余各条里建议为 block 档（含部分情形）的是 P05、P06、P10、P12、P13、P17、P27、P29。
- P01 的实践证据提示了三处容易漏的细节：按星期的定休日（[C5] 里周一占一半以上）、午间休息（[G7]、[C5]）、开门前到达（[C5] 里是时刻错误中最多的一类）。只比对"关门时间"查不出后两类。
- 地点数据本身会过期：领队文章指出 Google Maps 与指南书的营业信息可能不是最新的（[O10]），AI 测评里也反复出现"信息有时滞"（[R4]）。营业时间类规则应带数据更新时间，过旧时判 unknown 而不是 verified。
- P13 的落地建议：规则本身按 block；"雨天"的判定阈值从来源只能得到两个参照点（30–40% 与 50–60%），选哪一档是产品决定；行程日超出预报范围时只能判 unknown，梅雨期只是背景概率（东京高峰日约 45%），不能当预报用。室内替代要求"同区域且当日营业"，否则替代项自己会触发 P01 和 P09。
- 需要新增的地点属性汇总：按星期的营业时段与最终入场、定休日与节假日顺延、季节开放期、reservation_required 与放票规则、indoor/outdoor、cash_only、台阶与无电梯、末班时刻（缆车、渡轮、巴士）、酒店入住/退房/前台关闭时刻。需要新增的日历与环境数据：日本节假日与高峰期、分日降水确率与气温、台风与停运公告、日出日落。
- Roadanza 的做法可直接参照：违规转成具体问题文本回灌、保留用户锁定的片段、最多修 2 次、修不好就保留原样并把仍然勉强的地方告诉用户（[C3]）。
- 同行人与节奏类阈值（P07、P18、P22、P26）在来源里都是作者个人目安或估计，彼此也不一致（每日站点 2、3、2–4、4–5 都有），适合做成可配置的参考值并只给 warn。

### Gaps
- 没有找到 Booking.com、Expedia（Romie）、Tripadvisor、Mindtrip、Layla、Wanderlog、飞猪、美团、马蜂窝的团队公开描述行程校验规则或护栏的工程文章；携程只有媒体报道与云厂商案例，且未打开原页。公司类来源实际只有 Google、NAVITIME 与三家小产品。
- 小红书、知乎、马蜂窝的避坑帖通过搜索工具取不到；中文旅行者证据只有少数派一篇、聯合新聞網一篇和媒体实测。
- BBC 原文抓取被拒，读的是转述；虎嗅两篇、澎湃横评、AZWAY 调查、Business Insider 原文都没能打开，只有搜索摘要。
- 没有任何来源给出"降水概率达到多少就必须改室内"的数值；也没有来源说明旅行者实际在多大概率下改行程。
- 离境日"提前多久到机场"在来源里只有航司的截止时间，没有可引用的建议余量（"2–3 小时"只见于论坛与营销页，未采用）。
- 国土交通省巴士基准、環境省 WBGT、ANA、東横INN、富士登山官方、アルペンルート的数字都来自搜索摘要，原页或 PDF 未能读取，使用前需要核对现行版本。
- 京都寺院的闭门与最终入场时刻、冬季日落时刻、上高地冬季封闭日期没有找到可引用来源。
- 宅急便寄往机场的提前量只找到一份陈旧且残缺的二手 PDF 和一篇口径不同的博客摘要，未采用。
- 巴士旅游的厕所休息间隔、午餐与参观时长配比没有找到带数值的来源。
- 同行人（婴幼儿、长者、轮椅）的数值全部来自单一作者的目安或估计，没有找到行业标准或官方无障碍数据。
- [C5] 是厂商对自家产品的自评，[R1] 是 2024 年对 ChatGPT-3.5 的营销公司测试，[R6] 未标日期；这三项的比例数字只宜作量级参考。

[C1]: https://research.google/blog/optimizing-llm-based-trip-planning/
[C2]: https://www.travelvoice.jp/20260916-160522
[C3]: https://www.metaproject.pro/blog-posts/llm-guardrails-in-practice
[C4]: https://dev.to/forrestmiller/how-i-built-an-itinerary-validator-for-ai-travel-plans-36n3
[C5]: https://monkeyeatingmango.com/research/ai-itinerary-errors-data-study/
[C6]: https://cloud.google.com/customers/intl/zh-cn/tripgenie
[C7]: https://m.huxiu.com/article/4320066.html
[R1]: https://www.travolution.com/news/marketing/survey-finds-chatgpt-itineraries-to-be-riddled-with-inaccuracies/
[R2]: https://www.zmescience.com/future/why-trusting-ai-to-plan-your-vacation-could-be-a-total-disaster
[R2b]: https://incidentdatabase.ai/cite/1635/
[R3]: https://www.elliott.org/on-travel/can-i-trust-ai-to-give-me-good-travel-advice/
[R4]: https://m.gmw.cn/2026-11/01/content_1304581713.htm
[R5]: https://www.tmtpost.com/7975705.html
[R6]: https://www.colemanconcierge.com/ai-travel-planning-mistakes-real-travelers/
[R7]: https://lifestyle.assist-all.co.jp/chatgpt-travel-planner-tips-map-prompt/
[R8]: https://www.huxiu.com/article/4895221.html
[R9]: https://www.huxiu.com/article/4856404.html
[R10]: https://www.euronews.com/travel/2026/01/30/how-an-ai-generated-travel-website-sent-tourists-to-a-non-existent-hot-spring-attraction
[R11]: https://m.thepaper.cn/detail/34008490
[O1]: https://www.japan.travel/en/responsible-travel-guide/features/making-reservations/
[O2]: https://global.jr-central.co.jp/en/info/oversized-baggage
[O3]: https://ana.co.jp/en/jp/guide/prepare/airport-guide/international/caution
[O4]: https://www.mlit.go.jp/common/001000380.pdf
[O5]: https://www.env.go.jp/content/900502227.pdf
[O6]: https://www.travelvoice.jp/20240229-155179
[O7]: https://www.travelvoice.jp/20260701-160027
[O8]: https://www.triptojapan.com/zh/blog/15-mistakes-to-avoid-when-planning-your-japan-trip
[O9]: https://gowithguide.com/blog/japan-tour-for-seniors-the-truth-about-comfort-walking-and-daily-pace-6113
[O10]: https://livejapan.com/en/in-tokyo/in-pref-fuji_mountain/in-mount_fuji/article-a0005574/
[O11]: https://www.nta.co.jp/kokunai/special/family/beginner/
[O12]: https://rezdy.com/blog/the-tour-operators-itinerary-checklist/
[O13]: https://www.softrip.com/resources/blog/tour-itinerary-planning-tips/
[O14]: https://www.toyoko-inn.com/support/faq/hotel
[O15]: https://www.princehotels.co.jp/psi/en/faq/
[O16]: https://fujisan-climb.jp/en/faq-index.html
[O17]: https://www.jal.co.jp/en-gb/travel-info/boarding.html
[O18]: https://www.veltra.com/jp/yokka/article/domestic-ishikawa-kanazawa-68695/
[O19]: https://hoshinoresorts.com/guide/tag/amenohi/
[O20]: https://travel.jr-central.co.jp/contents/pdf/plan/315debuttour.pdf
[O21]: https://www.jrpass.com/blog/do-japan-s-trains-run-during-a-typhoon-what-to-expect
[O22]: https://article.his-j.com/kokunai/domestic-travel/post-36672/
[O23]: https://www.pref.chiba.lg.jp/kankou/tetsuzuki/shigoto-sangyou/shoukougyou/documents/1shukuhakushinseinituite.pdf
[G1]: https://www.japan-guide.com/e/e2282.html
[G2]: https://www.japan-guide.com/e/e2276.html
[G3]: https://www.japan-guide.com/e/e2278.html
[G4]: https://www.japan-guide.com/e/e2117.html
[G5]: https://www.japan-guide.com/e/e2277.html
[G6]: https://www.japan-guide.com/e/e2018.html
[G7]: https://tsunagujapan.com/opening-hours-japan
[G8]: https://livejapan.com/zh-tw/article-a0002586/
[G9]: https://timeout.com/tokyo/art/guide-to-booking-popular-museums-in-tokyo
[G10]: https://www.fun-japan.jp/en/articles/1385
[G11]: https://weathernews.jp/news/202406/100215/
[G12]: https://oggi.jp/6492852
[G13]: https://kotobank.jp/word/日本のおもな美術館-1616901
[G14]: https://www.japan-guide.com/e/e7550.html
[G15]: https://www.jma.go.jp/jma/kids/kids/faq/a5_46.html
[T1]: https://sspai.com/post/99797
[T2]: https://www.rexby.com/japantrips/t/common-mistakes-travelers-make-in-japan-and-how-to-avoid-them
[T3]: https://www.aol.com/visited-japan-first-time-trip-093202600.html
[T4]: https://udn.com/news/story/6812/9529299
[T5]: https://hugkum.sho.jp/478415
[T6]: https://carview.yahoo.co.jp/news/detail/1d83040dd2b20674de075780e17920a54e373c00/
[T7]: https://lonelyplanet.com/articles/japan-with-kids
