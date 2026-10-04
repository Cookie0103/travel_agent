# 真实协议验证

- V2 数据探针：显式设置 `TRAVEL_REAL_API_PROBE=geocode|places|routes|rakuten|weather` 后，只运行 `python -m pytest -m live tests/live/test_real_apis.py -q`。一次选一个，不循环、不放CI；调用前核对授权和PG计数。缓存可能使实际HTTP为0；不录制原始供应商响应。
- V2 单城规划：`python -m scripts.smoke_live --execute --city 大阪`，可选札幌/那霸/箱根。成功后停止，不批量重复；状态、工具和费用上界写入ignored缓存，公开汇总见 [V2](../../docs/operations/product-v2.md)。

以下为原协议批次规则，不代表 V2 的额外调用授权。

- test_deepseek_protocol.py 是 M0.2 入口；先运行 dev check 和 dev test。
- uv run --env-file .env python -X utf8 -m pytest -m live tests/live/test_deepseek_protocol.py -v --tb=line -p no:cacheprovider
- 首轮两个请求跑一个工具往返；成功后账本阻止重复付费。
- .cache/m02-protocol 记录请求次数、费用保守占用与脱敏响应摘要。
- 别删除账本以绕过限制；未验证项在 docs/protocols/protocol-deepseek.md 标“无法判断”。
- 本批最多两次流程/四次请求，用户授权与人民币预算仍必须满足。
- 这里不启动数据库，不向工具发送用户数据，不输出推理正文。
