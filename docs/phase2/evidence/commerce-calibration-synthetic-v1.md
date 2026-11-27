# C4 合成酒店口味参数校准

VERIFIED。以下为合成世界上的离线算术。正式酒店快照与决策模型结果到齐后需重新定参。

`uv run python -m eval.commerce.calibrate` · 2,000 组拉丁超立方样本，另纳入精确先验。

平台区 1057 组，调参 108/108，验收 72/72。离先验最近的一组为先验本身；收缩条件未触发。

检查集 SHA-256 `ab66a1a23f7ec277a8aa4c8413edcf7fe60a83cc387e4bad4f861f163f9f4399`。

| 参数 | 先验 | 暂定值 | 上下四分位通过率差（百分点） |
| --- | ---: | ---: | ---: |
| prior/price_ratio | -0.35 | -0.35 | +8.141 |
| prior/rating | 0.17 | 0.17 | -3.178 |
| family/breakfast | 1.6 | 1.6 | +2.565 |
| prior/rank | -0.012 | -0.012 | +2.535 |
| business/station_minutes | 1.25 | 1.25 | +1.985 |
| budget/price_ratio | 1.6 | 1.6 | -1.080 |
| prior/breakfast | 0.035 | 0.035 | -0.654 |
| prior/outside | 7.4 | 7.4 | -0.652 |
| prior/log_reviews | 0.025 | 0.025 | -0.374 |
| prior/station_minutes | -0.02065 | -0.02065 | -0.226 |
| prior/soft | 0.2 | 0.2 | -0.094 |

软性分没有接纳概率输入；对应的统计差来自抽样中与其他参数的联动。离线结果保留 provisional 标记。
