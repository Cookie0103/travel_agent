# SDK 接入实验

`run_probe` 启动回环请求守卫与隔离 Python 工作进程。
`worker` 使用 Claude Agent SDK 注册一个合成只读 MCP 工具。
`guard` 只转发固定 DeepSeek Messages 请求，真实密钥不进入 SDK 子进程。
`budget` 在联网前持久计数并预占人民币费用；完整 usage 才结算，失败保留预占。
`http` 限制请求总时长，`process` 在超时后回收 CLI 和工作进程。
默认测试使用本地脚本化响应；真实实验必须通过 live 入口。
这不是旅行业务或第二套 runtime；SDK 仍负责模型与工具往返。
