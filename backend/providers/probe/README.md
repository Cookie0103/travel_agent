# DeepSeek 协议探针

- 入口：tests/live/test_deepseek_protocol.py；默认离线测试不会运行它。
- flow.run_probe → Ledger.start_flow → transport.request → SDK 流 → 合成工具结果 → 续接。
- settings 只读取环境变量；uv --env-file 在进程启动前加载 .env。
- ledger.jsonl 在网络调用前落盘计次/保守费用，写入失败就不发送。
- 两次流程、四次请求是整个本批上限，跨天/重启不清零；成功后拒绝重复实测。
- 不同币种费用分开，当前仅 DeepSeek CNY 线路可发请求。
- 异常正文、密钥、推理文本不写日志；报告只保存固定合成请求说明与结构摘要。
- probe 是实测辅助程序，不定义 M0.3 的中立消息契约。
