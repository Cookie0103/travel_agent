# 独立离线演示镜像

入口：`uv run python scripts/dev.py stack-up`；专用端口3100/8100/8101/5544，仅本机。
backend共用锁文件与业务模块；web使用Next standalone。
构建上下文排除.env/cache/vendor；不打包模型密钥和SDK私有会话。
运行默认离线，宿主模型实测另走既有授权账本；不创建第二份容器额度。
服务/卷属于独立travel-agent-demo项目；stack-down不删卷。
Langfuse依ADR005使用可选Cloud导出，页面凭据/验收仍缺。
