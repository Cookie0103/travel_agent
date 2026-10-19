"""C2/C3/C4：输入边界返回422而非503；读接口不建行、不与写入争会话锁。"""

import asyncio
import threading
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import URL, create_engine, text

from backend.api.app import create_app
from backend.domain.choices import TRANSPORT_PACE_GROUPS
from backend.domain.execution import RunContext
from backend.domain.preferences import PreferencePatch
from backend.domain.travel_request import RequestPatch
from backend.persistence import runs
from backend.services.choices import ChoiceService
from backend.services.common import transaction
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from tests.runner import SELECTOR_OPTIONS, selector_runner

pytestmark = pytest.mark.integration


@pytest.fixture
def env(
    postgres_url: URL,
) -> Iterator[tuple[asyncio.Runner, TravelService, TestClient, dict[str, str], UUID]]:
    with selector_runner() as runner:
        sessions = SessionService(postgres_url, demo_enabled=True)
        identity = runner.run(sessions.create_demo_user(DemoLogin()))
        session = runner.run(sessions.new_session(identity.user_id))
        travel = TravelService(sessions.database)
        app = create_app(SessionService(postgres_url, demo_enabled=True))
        with TestClient(app, backend_options=SELECTOR_OPTIONS) as client:
            yield (
                runner,
                travel,
                client,
                {"Authorization": "Bearer " + identity.token},
                session.session_id,
            )
        runner.run(sessions.close())


def test_nul_in_preferences_and_request_is_422(env) -> None:  # type: ignore[no-untyped-def]
    _, _, client, headers, session_id = env
    # PATCH /preferences 已移除；偏好补丁模型仍须拒绝NUL。
    with pytest.raises(ValidationError):
        PreferencePatch.model_validate({"expected_revision": 0, "set": {"interests": ["a\u0000b"]}})
    for field in ("soft_constraints", "hard_constraints", "interests"):
        response = client.patch(
            f"/sessions/{session_id}/request",
            headers=headers,
            json={"expected_revision": 0, "set": {field: ["a\u0000b"]}},
        )
        assert response.status_code == 422, field
    assert client.request("PATCH", "/preferences", headers=headers, json={}).status_code == 405


def test_nul_in_message_is_422_not_503(env) -> None:  # type: ignore[no-untyped-def]
    _, _, client, headers, session_id = env
    response = client.post(
        f"/sessions/{session_id}/messages",
        headers=headers,
        json={"client_message_id": "00000000-0000-4000-8000-000000000001", "text": "a\u0000b"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        {"start_date": "1900-01-01", "end_date": "1900-01-03"},
        {"start_date": "2026-01-01", "end_date": "9999-12-31"},
        {"start_date": "2026-11-01", "end_date": "2027-01-15"},
        {"adults": 2, "child_ages": [], "rooms": 5},
    ],
)
def test_out_of_range_request_is_readable_422(env, fields) -> None:  # type: ignore[no-untyped-def]
    _, _, client, headers, session_id = env
    response = client.patch(
        f"/sessions/{session_id}/request",
        headers=headers,
        json={"expected_revision": 0, "set": fields},
    )
    assert response.status_code == 422
    assert "数据库" not in response.text and len(response.text) > 10
    assert client.get(f"/sessions/{session_id}/request", headers=headers).json()["revision"] == 0


def _hold_session_lock(url: URL, session_id: UUID):  # type: ignore[no-untyped-def]
    engine = create_engine(url)
    connection = engine.connect()
    connection.execute(
        text("select id from sessions where id = :s for update"), {"s": str(session_id)}
    )
    return engine, connection


def _finishes_while_locked(url: URL, session_id: UUID, call, timeout: float = 5) -> bool:  # type: ignore[no-untyped-def]
    engine, connection = _hold_session_lock(url, session_id)
    done = threading.Event()
    thread = threading.Thread(target=lambda: done.set() if call() else None, daemon=True)
    try:
        thread.start()
        return done.wait(timeout)
    finally:
        connection.rollback()
        connection.close()
        engine.dispose()
        thread.join(10)


def test_get_request_does_not_write_or_wait_for_session_lock(env, postgres_url) -> None:  # type: ignore[no-untyped-def]
    _, _, client, headers, session_id = env
    engine = create_engine(postgres_url)
    count = text("select count(*) from travel_requests where session_id = :s")
    with engine.connect() as connection:
        assert connection.execute(count, {"s": str(session_id)}).scalar() == 0
    assert _finishes_while_locked(
        postgres_url,
        session_id,
        lambda: client.get(f"/sessions/{session_id}/request", headers=headers).status_code == 200,
    ), "GET /request 被会话行锁阻塞"
    body = client.get(f"/sessions/{session_id}/request", headers=headers).json()
    assert body["revision"] == 0
    with engine.connect() as connection:
        assert connection.execute(count, {"s": str(session_id)}).scalar() == 0
    engine.dispose()


def test_get_choice_does_not_wait_for_session_lock(env, postgres_url) -> None:  # type: ignore[no-untyped-def]
    runner, travel, client, headers, session_id = env
    context = RunContext(_user_of(postgres_url, session_id), session_id)
    runner.run(
        travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 0, "set": {"city": "京都"}}),
        )
    )

    async def make() -> UUID:
        async with transaction(travel.database) as db:
            row = await runs.create(db, context.user_id, session_id, uuid4(), "先确认", "offline")
            active = RunContext(context.user_id, session_id, row.id)
        return (
            await ChoiceService(travel).create(active, "form", 1, TRANSPORT_PACE_GROUPS)
        ).choice_id

    choice_id = runner.run(make())
    assert _finishes_while_locked(
        postgres_url,
        session_id,
        lambda: (
            client.get(f"/sessions/{session_id}/choices/{choice_id}", headers=headers).status_code
            == 200
        ),
    ), "GET /choices 被会话行锁阻塞"


def _user_of(url: URL, session_id: UUID) -> UUID:
    engine = create_engine(url)
    with engine.connect() as connection:
        value = connection.execute(
            text("select user_id from sessions where id = :s"), {"s": str(session_id)}
        ).scalar()
    engine.dispose()
    return UUID(str(value))


def test_write_path_still_waits_for_session_lock(env, postgres_url) -> None:  # type: ignore[no-untyped-def]
    _, _, client, headers, session_id = env
    assert not _finishes_while_locked(
        postgres_url,
        session_id,
        lambda: (
            client.patch(
                f"/sessions/{session_id}/request",
                headers=headers,
                json={"expected_revision": 0, "set": {"city": "京都"}},
            ).status_code
            == 200
        ),
        timeout=1,
    ), "写入应等待会话行锁"
    assert client.get(f"/sessions/{session_id}/request", headers=headers).json()["revision"] == 1


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_weather_forecast", {"expected_revision": 0}),
        ("load_skill", {"name": "hotel-comparison"}),
    ],
)
def test_read_only_tools_do_not_wait_for_session_lock_or_create_rows(
    env: tuple[asyncio.Runner, TravelService, TestClient, dict[str, str], UUID],
    postgres_url: URL,
    tool: str,
    arguments: dict[str, object],
) -> None:
    runner, travel, _, _, session_id = env
    context = RunContext(_user_of(postgres_url, session_id), session_id)
    executor = TravelToolExecutor(travel)
    definition = next(d for d in DEFINITIONS if d.name == tool)

    async def call() -> bool:
        result = await execute_observed(
            executor, context, tool, arguments, lambda event: None, definition=definition
        )
        return result.code in (None, "unavailable")

    assert _finishes_while_locked(postgres_url, session_id, lambda: runner.run(call())), (
        f"{tool} 被会话行锁阻塞"
    )
    engine = create_engine(postgres_url)
    with engine.connect() as connection:
        rows = connection.execute(
            text("select count(*) from travel_requests where session_id = :s"),
            {"s": str(session_id)},
        ).scalar()
    engine.dispose()
    assert rows == 0
