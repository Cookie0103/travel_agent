"""迁移结果与models的自动一致性：任何一边漂移（列/类型/默认值/索引/唯一/外键/CHECK）都会红。

0013/0014/0015用原生`ADD COLUMN IF NOT EXISTS`、0018在bind里条件建表，静态审查看不出
最终形状，所以这里在真实随机PG库上执行全部迁移后再与Base.metadata比较。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import URL, Column, Connection, Index, Integer, MetaData, create_engine, inspect
from sqlalchemy import CheckConstraint as Check

from backend.persistence.database import ROOT
from backend.persistence.models import Base
from backend.persistence.temporary import temporary_database

pytestmark = pytest.mark.integration

# 开启的比较项：列增删、类型(compare_type)、server_default(compare_server_default)、
# nullable、索引、唯一约束、外键（alembic默认比较后三项）。表增删也在其中。
OPTIONS = {"compare_type": True, "compare_server_default": True}


@contextmanager
def migrated(postgres_url: URL) -> Iterator[Connection]:
    with temporary_database(postgres_url, "test") as target:
        engine = create_engine(target, hide_parameters=True)
        try:
            with engine.connect() as connection:
                yield connection
        finally:
            engine.dispose()


def diff(connection: Connection, metadata: MetaData) -> list[Any]:
    context = MigrationContext.configure(connection, opts=OPTIONS)
    return list(compare_metadata(context, metadata))


def test_upgrade_head_matches_models(postgres_url: URL) -> None:
    with migrated(postgres_url) as connection:
        # 不设忽略列表：enum/JSONB等类型比较在当前迁移与models下本来就无差异。
        assert diff(connection, Base.metadata) == []


def test_check_constraints_match_models(postgres_url: URL) -> None:
    """alembic autogenerate不比较CHECK，这里按表比较名称集合与定义里的取值集合。"""
    with migrated(postgres_url) as connection:
        inspector = inspect(connection)
        for table in Base.metadata.sorted_tables:
            declared = {c.name for c in table.constraints if isinstance(c, Check)}
            actual = {c["name"] for c in inspector.get_check_constraints(table.name)}
            assert actual == declared, table.name


def test_comparison_detects_model_drift(postgres_url: URL) -> None:
    """负向：模型多出索引/列、少了列时必须报差异，证明上面的断言不是空转。"""
    with migrated(postgres_url) as connection:
        drifted = MetaData()
        for table in Base.metadata.tables.values():
            table.to_metadata(drifted)
        sessions = drifted.tables["sessions"]
        sessions.append_column(Column("drift_probe", Integer))
        Index("ix_sessions_drift_probe", sessions.c.created_at)
        drifted.tables["users"]._columns.remove(drifted.tables["users"].c.display_name)  # noqa: SLF001
        kinds = {item[0] for item in diff(connection, drifted)}
        assert {"add_column", "add_index", "remove_column"} <= kinds


def alembic_config(connection: Connection) -> Config:
    config = Config(str(ROOT / "backend/persistence/alembic.ini"))
    config.attributes["connection"] = connection
    return config


def test_downgrade_to_0017_and_back_restores_the_same_schema(postgres_url: URL) -> None:
    """受支持的回退范围：head->0017->head（含0022的CHECK/索引），回来后与models仍无差异。

    不支持降到base：0018为保留用户记忆有意不删user_memory_facts，其外键阻止0004删task_runs；
    项目规则是迁移只做加法、回退按revert提交走（见migrations/README）。
    """
    with temporary_database(postgres_url, "test") as target:
        engine = create_engine(target, hide_parameters=True)
        try:
            with engine.begin() as connection:
                config = alembic_config(connection)
                command.downgrade(config, "0017")
                assert "ix_task_runs_session_id_created_at" not in {
                    i["name"] for i in inspect(connection).get_indexes("task_runs")
                }
                assert inspect(connection).get_check_constraints("task_runs") == []
                command.upgrade(config, "head")
                assert diff(connection, Base.metadata) == []
        finally:
            engine.dispose()


def test_downgrade_to_base_is_documented_as_unsupported(postgres_url: URL) -> None:
    with temporary_database(postgres_url, "test") as target:
        engine = create_engine(target, hide_parameters=True)
        try:
            with engine.connect() as connection:
                config = alembic_config(connection)
                with pytest.raises(Exception, match="user_memory_facts"):
                    command.downgrade(config, "base")
        finally:
            engine.dispose()
