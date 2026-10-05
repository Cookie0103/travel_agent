"""测试/评测共用专用本地数据库；仅清理本次成功创建的随机库，不接受删除目标。"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal
from uuid import uuid4

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import URL, create_engine

from backend.persistence.database import ROOT


def isolated_url(configured: URL, name: str) -> URL:
    if configured.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("测试/评测只允许本地项目PostgreSQL，不连接远端数据库")
    return configured.set(database=name, query={})


@contextmanager
def temporary_database(configured: URL, purpose: Literal["test", "eval"]) -> Iterator[URL]:
    if purpose not in {"test", "eval"}:
        raise ValueError("临时数据库用途无效")
    name = f"travel_agent_{purpose}_" + uuid4().hex
    target = isolated_url(configured, name)
    with psycopg.connect(
        host=configured.host,
        port=configured.port,
        dbname="postgres",
        user=configured.username,
        password=configured.password,
        autocommit=True,
        connect_timeout=5,
    ) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            config = Config(str(ROOT / "backend/persistence/alembic.ini"))
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
            # 不变量：名称只来自本次uuid，不接受配置/用例提供的待删除数据库名。
            assert re.fullmatch(r"travel_agent_(test|eval)_[0-9a-f]{32}", name)
            assert target.database == name
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
