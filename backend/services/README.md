# 应用服务编排

入口：sessions.SessionService，承接API身份和会话用例。
DemoLogin契约由FastAPI复用；服务端生成身份/令牌，摘要与会话写入各自事务。
authenticate只返回有效令牌对应的服务端user_id；会话查询始终检查所属用户。
数据库异常映射安全ServiceError，服务退出时关闭连接池；不吞错误或回显连接参数。
