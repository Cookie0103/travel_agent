"""/health 只证明进程与连接存活；/health/ready 还要求迁移已到脚本 head。"""

import re
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import URL, create_engine, text

from backend.api.app import create_app
from backend.persistence.database import ROOT, configuration, database_url
from backend.persistence.temporary import isolated_url
from backend.services.sessions import SessionService
from tests.runner import SELECTOR_OPTIONS

pytestmark = pytest.mark.integration


@pytest.fixture
def blank_url() -> Iterator[URL]:
    """没有任何迁移的新库；只删除本用例按随机名创建的库。"""
    configured = database_url(configuration())
    name = "travel_agent_test_" + uuid4().hex
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
            yield target
        finally:
            assert re.fullmatch(r"travel_agent_test_[0-9a-f]{32}", name)
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def migrate(url: URL, revision: str) -> None:
    config = Config(str(ROOT / "backend/persistence/alembic.ini"))
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    finally:
        engine.dispose()


def client_for(url: URL) -> TestClient:
    return TestClient(create_app(SessionService(url)), backend_options=SELECTOR_OPTIONS)


def test_unmigrated_database_is_alive_but_not_ready(blank_url: URL) -> None:
    with client_for(blank_url) as client:
        assert client.get("/health").json() == {"status": "ok"}
        not_ready = client.get("/health/ready")
        assert not_ready.status_code == 503
        assert not_ready.json()["code"] == "unavailable"
        migrate(blank_url, "head")
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ok"}


def test_database_behind_head_is_not_ready(blank_url: URL) -> None:
    migrate(blank_url, "0001")
    with client_for(blank_url) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health/ready").status_code == 503


def test_migrated_database_is_ready(postgres_url: URL) -> None:
    with client_for(postgres_url) as client:
        assert client.get("/health/ready").json() == {"status": "ok"}
    engine = create_engine(postgres_url, hide_parameters=True)
    try:
        with engine.connect() as db:
            assert db.scalar(text("SELECT count(*) FROM alembic_version")) == 1
    finally:
        engine.dispose()
