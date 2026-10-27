# 真实数据库集成测试

dev db-up 后 dev test 默认也运行这里；pytest -m integration可单独验证。
conftest在已配置的本地项目PostgreSQL创建随机测试库，执行相同Alembic迁移两次和schema drift检查。
仅删除本次创建且名称匹配的测试库；开发库和已安装PostgreSQL服务中的数据不清理。
TestClient使用SelectorEventLoop，与Windows API启动一致；其他SDK测试仍保留其正常循环。
