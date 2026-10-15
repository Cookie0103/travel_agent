# ADR-006：本地数据库配置和演示身份

状态：accepted，2026-10-03，落实ADR-000/M1.1。

采用已有栈FastAPI、SQLAlchemy async、psycopg、Alembic；新增直接依赖python-dotenv读取本地配置，避免手写引号/空白解析；测试直接依赖httpx（已由SDK依赖链安装）。
环境变量优先于.env，只读取明确的数据库/演示配置，不在配置对象或错误日志输出密码。DATABASE_URL可选，否则由POSTGRES_*派生，URL编码交SQLAlchemy。
开发PostgreSQL只使用项目Compose；本机默认5434避开已有5432/5433服务。测试在该容器创建随机travel_agent_test_*数据库，验证名称后仅清理本次创建的测试库。

本地演示登录每次创建新用户和随机Bearer令牌，数据库仅存SHA256摘要，令牌有24小时期限。禁止客户端传user_id登录已有用户。接口默认关闭，显式DEMO_MODE=true才打开；不是生产账号认证。
API→services→persistence；一事务一AsyncSession，不共享Session给并发任务。不添加通用仓储或CRUD生成层。

Windows下psycopg async需要SelectorEventLoop，服务启动入口显式配置；SDK继续在独立子进程的运行环境中启动，不改变SDK测试/CLI的事件循环。
依据：[SQLAlchemy并发会话](https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks)、[psycopg Windows说明](https://www.psycopg.org/psycopg3/docs/advanced/async.html)。

备选：手写.env解析会重复已成熟库；明文token/任意user_id演示登录会破坏用户隔离；全局改asyncio policy会影响SDK子进程能力。因此均不采用。
