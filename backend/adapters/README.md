# 外部服务适配边界

隔离外部服务协议；不在导入时联网。

入口：tracing.trace_report 接收私有运行报告，导出 OTel spans。
关键流程：真实事件时间 → SDK 内存 spans → 本地 JSONL → 显式可选 OTLP HTTP。
不变量：不导出正文/密钥；不虚构缺失时间/usage；导出故障保留业务结果。
