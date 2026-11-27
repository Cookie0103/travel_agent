# 真实数据库集成测试

dev db-up 后 dev test 默认也运行这里；pytest -m integration可单独验证。
conftest在已配置的本地项目PostgreSQL创建随机测试库，执行相同Alembic迁移两次和schema drift检查。
仅删除本次创建且名称匹配的测试库；开发库和已安装PostgreSQL服务中的数据不清理。
TestClient使用SelectorEventLoop，与Windows API启动一致；其他SDK测试仍保留其正常循环。

## 目录

| 目录 | 测什么 |
| --- | --- |
| api/ | 会话、Run、历史、健康检查、进程重启与恢复、输入上限 |
| travel/ | 旅行条件、问清与选择卡、目录与攻略、外部数据与重试 |
| hotels/ | 酒店搜索与恢复、预算、房型、分段选酒店、模拟下单 |
| plans/ | 行程规划、草稿与正式行程的生命周期 |
| memory/ | 确认式记忆、抽取、续接、用户画像 |
| sdk/ | 经 Claude Agent SDK 与 MCP 的端到端链路 |
| eval/ | 评测运行器对真实库：v1–v3、模拟用户 |
| schema/ | 表结构约束、迁移一致性 |

`conftest.py` 的夹具对所有子目录生效。`api_process.py`、`recovery_worker.py`、`sdk_context_worker.py` 是被测试以 `python -m tests.integration.<名>` 启动的子进程入口，留在本层不要移动。
