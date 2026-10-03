# 数据库仓储、迁移与事务

入口：database.configuration/database_url/Database，sessions中的具体SQL操作。
迁移：dev db-migrate；模型定义models.py，版本在migrations/versions。
会话SQL必须同时过滤id和user_id；令牌仅存摘要与过期时间。
一事务一AsyncSession，不跨异步任务共享。API通过services访问本包。
配置错误/SQL参数不输出密钥；.env默认读取数据库相关字段，环境变量优先。
`catalog.import_catalog`在调用方事务中幂等更新，`load_catalog`返回已验证的公开快照给现有搜索函数。
`travel.owned_request`先锁住本人会话；条件revision更新与相关Evidence失效在同一事务完成。

temporary.temporary_database为测试/评测创建随机本地专用库，迁移/check共用；仅删除本次成功创建库，不接受用户删除目标。
