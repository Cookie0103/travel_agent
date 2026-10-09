# 数据库迁移

入口：dev db-migrate；env.py复用数据库配置；versions按提交版本演进。
新环境运行upgrade head，应用启动不偷偷create_all。
测试在本次创建的独立测试库运行同一套迁移，不用SQLite替代PostgreSQL。
降级会删除相应表数据；开发任务不对用户已有库自动降级。
