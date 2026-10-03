"""在项目 PostgreSQL 创建本次专用测试库；只清理本次成功创建的随机库。"""

import re
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import URL, create_engine

from backend.persistence.database import ROOT, configuration, database_url


def isolated_url(configured: URL, name: str) -> URL:
    """测试连接不能继承会覆盖 host/dbname 的 libpq 查询参数。"""
    if configured.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("测试只允许本地项目PostgreSQL，不连接远端数据库")
    return configured.set(database=name, query={})


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[URL]:
    configured = database_url(configuration())
    name = "travel_agent_test_" + uuid4().hex
    target = isolated_url(configured, name)
    try:
        admin = psycopg.connect(
            host=configured.host,
            port=configured.port,
            dbname="postgres",
            user=configured.username,
            password=configured.password,
            autocommit=True,
            connect_timeout=5,
        )
    except psycopg.OperationalError:
        pytest.fail("项目PostgreSQL不可用，请先运行dev db-up；未创建测试库", pytrace=False)
    with admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            config = Config(str(ROOT / "backend" / "persistence" / "alembic.ini"))
            engine = create_engine(target, hide_parameters=True)
            try:
                with engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.upgrade(config, "head")
                    command.upgrade(config, "head")
                    command.check(config)
            finally:
                engine.dispose()
            yield target
        finally:
            # 不变量：名称只来自本次uuid，不接受配置/用例拼接的待删除数据库名。
            assert re.fullmatch(r"travel_agent_test_[0-9a-f]{32}", name)
            assert target.database == name
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
