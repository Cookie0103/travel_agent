# 真实协议验证

- test_deepseek_protocol.py 是 M0.2 入口；先运行 dev check 和 dev test。
- uv run --env-file .env python -X utf8 -m pytest -m live tests/live/test_deepseek_protocol.py -v --tb=line -p no:cacheprovider
- 首轮两个请求跑一个工具往返；成功后账本阻止重复付费。
- .cache/m02-protocol 记录请求次数、费用保守占用与脱敏响应摘要。
- 别删除账本以绕过限制；未验证项在 docs/protocol-deepseek.md 标“无法判断”。
- 本批最多两次流程/四次请求，用户授权与人民币预算仍必须满足。
- 这里不启动数据库，不向工具发送用户数据，不输出推理正文。
