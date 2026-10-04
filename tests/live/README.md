# 真实协议验证

- V2 数据探针：显式设置 `TRAVEL_REAL_API_PROBE=geocode|places|routes|rakuten|weather` 后，只运行 `python -m pytest -m live tests/live/test_real_apis.py -q`。一次选一个，不循环、不放CI；调用前核对授权和PG计数。缓存可能使实际HTTP为0；不录制原始供应商响应。
- V2 单城规划：`python -m scripts.smoke_live --execute --city 大阪`，可选札幌/那霸/箱根。成功后停止，不批量重复；状态、工具和费用上界写入ignored缓存，公开汇总见 [V2](../../docs/operations/product-v2.md)。
