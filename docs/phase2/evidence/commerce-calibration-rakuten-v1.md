# C4 本机酒店快照的口味定参

VERIFIED。版本 `phase2-rakuten-calibration-2de10405`。用 C1 的六城本机快照生成检查集，按同组酒店和模板分离调参与验收。

拉丁超立方抽样 2,000 组，随机种子 20261129，平台区 1,045 组。离先验最近的一组为先验。
调参集 102/102，验收集 72/72。差值 0 个百分点。
检查集 SHA-256 为 `2de1040548e4f1b5a0cc2d496031bb3929c7daef455dfeb25630f9dafe669542`。

C5 通过的两项按 0.5 等权登记，节奏项为零。静态酒店检查集的软性参数敏感度为零，两项起点依据中文体检和既定的小量级设置。
当前政策参数沿用先验。

| 参数 | 先验 | 冻结值 | 对调参通过率的影响（百分点） |
| --- | ---: | ---: | ---: |
| `prior/price_ratio` | -0.35 | -0.35 | 7.820 |
| `prior/rating` | 0.17 | 0.17 | -3.833 |
| `family/breakfast` | 1.6 | 1.6 | 2.847 |
| `prior/rank` | -0.012 | -0.012 | 2.514 |
| `business/station_minutes` | 1.25 | 1.25 | 1.837 |
| `budget/price_ratio` | 1.6 | 1.6 | -1.045 |
| `prior/breakfast` | 0.035 | 0.035 | -0.690 |
| `prior/outside` | 7.4 | 7.4 | -0.688 |
| `soft_item/grounded_reason` | 0.5 | 0.5 | -0.514 |
| `prior/log_reviews` | 0.025 | 0.025 | -0.429 |
| `prior/station_minutes` | -0.02065 | -0.02065 | -0.286 |
| `soft_item/pace_fit` | 0 | 0 | 0.253 |
| `prior/soft` | 0.2 | 0.2 | -0.112 |
| `soft_item/stay_fit` | 0.5 | 0.5 | -0.022 |
