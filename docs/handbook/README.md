# 手册：两个阶段都要遵守的规则和系统说明

这里的内容不随阶段归档。规则变了就地修改；系统说明随实现同步更新。

| 文件 | 管什么 | 什么时候读 |
| --- | --- | --- |
| [execution/workflow.md](execution/workflow.md) | 一个任务从开始到提交的步骤、质量关卡 | 开始或恢复工作时 |
| [execution/standards.md](execution/standards.md) | 类型、格式、分层、失败路径测试、SDK 优先与简洁复用 | 写代码前 |
| [execution/layering-debt.md](execution/layering-debt.md) | 已知的分层违规清单与 backend 模块地图 | 动跨层依赖时 |
| [execution/verification.md](execution/verification.md) | 第一阶段的验收矩阵（需求→证据→缺口） | 查某个能力有没有验证过 |
| [recording.md](recording.md) | 计划写在哪、状态怎么标、过程怎么记、面试案例怎么沉淀；批次索引 | 每次记录前 |
| [guides/reuse.md](guides/reuse.md) | 项目长期方法约定（Anthropic 两篇文章的用法）与上游阅读清单 | 每个新会话开头 |
| [guides/development.md](guides/development.md) | 怎么运行、目录放什么、开发命令 | 第一次跑项目时 |
| [guides/evaluation.md](guides/evaluation.md) | v1–v3 评测的口径与命令 | 跑评测或解释指标时 |
| [guides/system-walkthrough.md](guides/system-walkthrough.md) | 架构、身份、Run、SSE、草稿、数据库字段的白话讲解 | 看不懂某个概念时 |
| [guides/FRONTEND.md](guides/FRONTEND.md)、[guides/QUALITY_SCORE.md](guides/QUALITY_SCORE.md) | 前端约定与浏览器验收；质量评分口径 | 改前端、报指标时 |
| [design/](design/README.md) | 产品长期设计 01–07：目标、架构、数据与工具、路线、校验、来源、前端风格 | 动业务设计前 |
| [adr/](adr/README.md) | 技术决策记录，只追加；新增依赖或契约先写 ADR | 引入依赖、改契约时 |
| [testing/README.md](testing/README.md) | 测试分层、命令、CI、已知的环境相关失败 | 测试红了先对照 |
| [DESIGN.md](DESIGN.md)、[RELIABILITY.md](RELIABILITY.md)、[SECURITY.md](SECURITY.md) | 设计总览、可靠性与安全不变量 | 改动涉及事务、恢复、权限时 |

第二阶段新增的设计先写在 [phase2/design.md](../phase2/design.md)；阶段结束时把确立下来的部分并入 `design/`。
