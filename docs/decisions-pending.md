# 待审阅决定

这些是 M0.1 的保守实施选择，不代表修改 plan/；可在白天审阅时调整。

| 任务 | 问题 | 本批选择 | 备选与理由 | 不同意时修改 |
| --- | --- | --- | --- | --- |
| M0.1 | 本机 uv 默认缓存不可访问 | 项目内 .cache/uv；Python 3.12 本机引导装在 .cache/python；不进 Git | 全局安装，影响其他项目且需要额外系统写入，故不选 | pyproject.toml、scripts/dev.py、README.md；本机重建 .venv |
| M0.1 | 02 目录图未列 services/adapters，执行规则已引用 | 只补同名空包以落实分层约束 | 延迟创建会让契约引用缺失模块；不增加业务接口 | backend/services、backend/adapters、pyproject.toml |
| M0.1 | 空骨架是否一次安装全部业务 SDK | 仅安装已使用的检查和测试工具；业务 SDK 在所属任务引入 | 提前安装会固定未验证接口，并扩大本批范围 | pyproject.toml、uv.lock、ADR-001 |
| M0.1 | eval-dev 在 M0.6 前应如何表现 | 保留命令入口，明确返回 unavailable 与非零码 | 输出空表会让未实现看起来已通过，故不选 | scripts/dev.py、tests/test_dev.py |
| M0.1 | HTTP SDK 规则只限制外部调用，但静态分析无法区分用途 | 在边界层外禁止导入四个指定 SDK；新包需检查来源列表 | 检查运行时调用更复杂；测试使用标准库 mock 即可 | pyproject.toml、tests/test_architecture.py |
| M0.1 | 数据库密码模板必须无值 | Compose 要求本地 .env 提供密码，默认仅监听 127.0.0.1 | 提交固定密码不符合密钥约定，故不选 | docker-compose.yml、.env.example、README.md |

验证失败计数按完整 dev check/dev test 验收轮次记录；环境下载失败、测试内故意构造的失败不算任务验收失败。
