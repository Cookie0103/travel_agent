# 数据库仓储、迁移与事务

入口：database.configuration/database_url/Database，sessions中的具体SQL操作。
迁移：dev db-migrate；模型定义models.py，版本在migrations/versions。
会话SQL必须同时过滤id和user_id；令牌仅存摘要与过期时间。
一事务一AsyncSession，不跨异步任务共享。API通过services访问本包。
配置错误/SQL参数不输出密钥；.env默认读取数据库相关字段，环境变量优先。
