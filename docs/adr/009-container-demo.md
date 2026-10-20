# ADR-009：独立离线容器演示

状态：accepted（2026-10-03，落实M4.1，实际构建/业务/重建验证见[M4记录](../review/M4.md)）。

采用独立Compose项目travel-agent-demo，与既有开发PG/端口/卷隔离。API、供应商共用一个Python3.12镜像和uv.lock；前端使用Node24.12.0、pnpm11.19.0与既有锁文件。工具版本与当前已测版本一致，不升级业务依赖。基础镜像及实际构建摘要随交付记录，不将可变标签当不可变digest。

启动一次迁移/现有快照导入，再启动API与供应商；复用既有模块，不重新实现演示业务。前端使用Next standalone及容器内同源代理。服务在容器监听所有接口，宿主端口仅发布127.0.0.1；保持本机演示身份与单worker范围。

专用PG密码在忽略的.cache/demo.env首次生成，重启复用；不读取/复制用户.env，不传模型密钥，不把缓存、Git、vendor或登录配置纳入构建上下文。API默认离线；容器不能产生真实模型费用。模型实测仍走现有宿主授权账本，不创建独立容器额度。停止不删卷，不提供自动清空命令。

Langfuse继续ADR000/005的Cloud替代；不安装Redis/ClickHouse/对象存储栈。Docker交付的应用启动与Langfuse页面验收分别报告，后者缺凭据保持partial。不是将Cloud凭据或API密钥写进公共镜像。

来源：[uv官方Docker集成](https://docs.astral.sh/uv/guides/integration/docker/)、[Next官方standalone输出](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)。只复用公共配置能力，未复制上游应用源码。
