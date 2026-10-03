"""真实 PostgreSQL + ASGI：身份隔离、失效令牌、数据库失败和事务落盘。"""

import asyncio
import hashlib
import socket
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine, select, update

from backend.api.app import create_app
from backend.persistence.models import SessionRow, UserRow
from backend.services.sessions import SessionService

pytestmark = pytest.mark.integration


@pytest.fixture
def client(postgres_url: URL) -> Iterator[TestClient]:
    app = create_app(SessionService(postgres_url, demo_enabled=True))
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        yield client


def login(client: TestClient, name: str = "旅行者") -> dict[str, str]:
    response = client.post("/demo/login", json={"display_name": name})
    assert response.status_code == 201
    return {"Authorization": "Bearer " + str(response.json()["token"])}


def test_two_users_cannot_read_each_others_sessions(client: TestClient) -> None:
    first, second = login(client, "第一位"), login(client, "第二位")
    created = client.post("/sessions", headers=first)
    assert created.status_code == 201
    path = "/sessions/" + str(created.json()["session_id"])
    assert client.get(path, headers=first).status_code == 200
    assert client.get(path, headers=second).status_code == 404
    assert client.get(path).status_code == 401
    assert client.get("/health").json() == {"status": "ok"}


def test_token_is_hashed_and_expired_token_cannot_create_session(
    client: TestClient, postgres_url: URL
) -> None:
    headers = login(client)
    token = headers["Authorization"][7:]
    engine = create_engine(postgres_url, hide_parameters=True)
    try:
        with engine.begin() as db:
            stored = db.scalar(
                select(UserRow.token_hash).where(
                    UserRow.token_hash == hashlib.sha256(token.encode()).hexdigest()
                )
            )
            assert stored is not None and stored != token
            db.execute(
                update(UserRow)
                .where(UserRow.token_hash == stored)
                .values(token_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert client.post("/sessions", headers=headers).status_code == 401
        assert (
            client.post("/sessions", headers={"Authorization": "Bearer invalid"}).status_code == 401
        )
    finally:
        engine.dispose()


def test_demo_login_cannot_impersonate_existing_user(client: TestClient, postgres_url: URL) -> None:
    identity = client.post("/demo/login", json={}).json()
    response = client.post("/demo/login", json={"user_id": identity["user_id"]})
    assert response.status_code == 422
    app = create_app(SessionService(postgres_url, demo_enabled=False))
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as locked:
        assert locked.post("/demo/login", json={}).status_code == 403


def test_database_outage_is_safe_unavailable(postgres_url: URL) -> None:
    with socket.socket() as closed_port:
        closed_port.bind(("127.0.0.1", 0))
        app = create_app(SessionService(postgres_url.set(port=closed_port.getsockname()[1])))
        with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
            response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"code": "unavailable", "message": "数据库暂不可用"}
    assert str(postgres_url.password) not in response.text


def test_session_survives_new_application_instance(client: TestClient, postgres_url: URL) -> None:
    headers = login(client)
    session_id = str(client.post("/sessions", headers=headers).json()["session_id"])
    app = create_app(SessionService(postgres_url))
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as restarted:
        assert restarted.get("/sessions/" + session_id, headers=headers).status_code == 200
    engine = create_engine(postgres_url, hide_parameters=True)
    try:
        with engine.connect() as db:
            assert db.scalar(select(SessionRow.id).where(SessionRow.id == session_id)) is not None
    finally:
        engine.dispose()
