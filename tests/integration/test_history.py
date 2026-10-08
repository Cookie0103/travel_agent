"""R01/R03：历史接口真实PG分页、归属、空结果与只读恢复；不执行模型。"""

import asyncio
import base64
import json
import socket
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine, insert, select, update

from backend.api.app import create_app
from backend.persistence.models import (
    PlanRow,
    PlanVersionRow,
    RunEventRow,
    SessionRow,
    TaskRunRow,
)
from backend.services.sessions import SessionService
from tests.integration.test_sessions import client as client
from tests.integration.test_sessions import login

pytestmark = pytest.mark.integration
STAMP = datetime(2026, 10, 8, 1, tzinfo=UTC)


def new_session(client: TestClient, headers: dict[str, str]) -> str:
    return str(client.post("/sessions", headers=headers).json()["session_id"])


def test_history_empty_owned_and_unauthorized_are_distinct(client: TestClient) -> None:
    owner, other = login(client), login(client)
    session_id = new_session(client, owner)
    empty = client.get("/sessions", headers=other)
    assert empty.status_code == 200 and empty.json() == {"items": [], "next_cursor": None}
    path = f"/sessions/{session_id}/runs"
    empty = client.get(path, headers=owner)
    assert empty.status_code == 200 and empty.json() == {"items": [], "next_before": None}
    for hidden in (session_id, str(uuid4())):
        result = client.get(f"/sessions/{hidden}/runs", headers=other)
        assert result.status_code == 404 and result.json()["message"] == "会话不存在"
    assert client.get("/sessions").status_code == 401
    assert client.get(path).status_code == 401
    assert client.get("/sessions", headers=other).json()["items"] == []


def test_session_pages_use_immutable_creation_key_and_only_formal_plan_metadata(
    client: TestClient, postgres_url: URL
) -> None:
    owner = login(client)
    session_ids = [new_session(client, owner) for _ in range(3)]
    engine = create_engine(postgres_url, hide_parameters=True)
    try:
        with engine.begin() as db:
            db.execute(
                update(SessionRow).where(SessionRow.id.in_(session_ids)).values(created_at=STAMP)
            )
            user_id = db.scalar(select(SessionRow.user_id).where(SessionRow.id == session_ids[0]))
            plan_id = uuid4()
            db.execute(
                insert(PlanRow).values(
                    id=plan_id, user_id=user_id, session_id=session_ids[0], current_version=1
                )
            )
            db.execute(
                insert(PlanVersionRow).values(
                    plan_id=plan_id,
                    version=1,
                    payload={"saved_at": (STAMP + timedelta(hours=1)).isoformat()},
                )
            )
            db.execute(
                insert(PlanRow).values(
                    id=uuid4(), user_id=user_id, session_id=session_ids[1], current_version=0
                )
            )
        assert (
            client.patch(
                f"/sessions/{session_ids[0]}/request",
                headers=owner,
                json={
                    "expected_revision": 0,
                    "set": {"city": "京都", "start_date": "2026-11-03", "end_date": "2026-11-05"},
                },
            ).status_code
            == 200
        )
        page = client.get("/sessions?limit=2", headers=owner)
        assert page.status_code == 200
        first = page.json()
        assert [item["session_id"] for item in first["items"]] == sorted(session_ids, reverse=True)[
            :2
        ]
        assert first["next_cursor"]
        new_id = new_session(
            client, owner
        )  # A later creation must not shift the old page boundary.
        with engine.begin() as db:
            db.execute(
                update(SessionRow)
                .where(SessionRow.id == new_id)
                .values(created_at=STAMP + timedelta(hours=4))
            )
            # A parent counter without its immutable version is not a saved plan.
            db.execute(
                insert(PlanRow).values(
                    id=uuid4(), user_id=user_id, session_id=new_id, current_version=3
                )
            )
            db.execute(
                insert(TaskRunRow).values(
                    id=uuid4(),
                    user_id=user_id,
                    session_id=session_ids[2],
                    client_message_id=uuid4(),
                    prompt="后来的对话",
                    mode="offline",
                    status="completed",
                    answer="离线",
                    created_at=STAMP + timedelta(hours=2),
                    finished_at=STAMP + timedelta(hours=3),
                )
            )
        second = client.get(
            "/sessions", params={"limit": 2, "cursor": first["next_cursor"]}, headers=owner
        ).json()
        assert [item["session_id"] for item in second["items"]] == sorted(
            session_ids, reverse=True
        )[2:]
        assert second["next_cursor"] is None
        summaries = {
            item["session_id"]: item
            for item in client.get("/sessions", headers=owner).json()["items"]
        }
        assert summaries[new_id]["plan_id"] is None and summaries[new_id]["current_version"] is None
        saved = summaries[session_ids[0]]
        assert saved["plan_id"] == str(plan_id) and saved["current_version"] == 1
        assert saved["city"] == "京都" and saved["start_date"] == "2026-11-03"
        assert datetime.fromisoformat(saved["last_activity_at"]) == STAMP + timedelta(hours=1)
        draft_only = summaries[session_ids[1]]
        assert draft_only["plan_id"] is None and draft_only["current_version"] is None
        assert draft_only["city"] is None and draft_only["end_date"] is None
        assert datetime.fromisoformat(
            summaries[session_ids[2]]["last_activity_at"]
        ) == STAMP + timedelta(hours=3)
    finally:
        engine.dispose()


def test_run_pages_include_all_statuses_and_per_run_cards_without_new_execution(
    client: TestClient, postgres_url: URL
) -> None:
    owner, other = login(client), login(client)
    session_id, other_session = new_session(client, owner), new_session(client, other)
    ids = sorted((uuid4() for _ in range(5)), reverse=True)
    draft_id = uuid4()
    engine = create_engine(postgres_url, hide_parameters=True)
    try:
        with engine.begin() as db:
            user_id = db.scalar(select(SessionRow.user_id).where(SessionRow.id == session_id))
            for index, status in enumerate(
                ("completed", "failed", "cancelled", "running", "partial")
            ):
                db.execute(
                    insert(TaskRunRow).values(
                        id=ids[index],
                        user_id=user_id,
                        session_id=session_id,
                        client_message_id=uuid4(),
                        prompt=f"消息{index}",
                        mode="offline",
                        status=status,
                        answer=f"答复{index}",
                        error_code="timeout" if status == "failed" else None,
                        last_sequence=6,
                        created_at=STAMP,
                    )
                )
            # Only the newest four presentation events are exposed, in chronological order.
            for sequence in range(1, 7):
                db.execute(
                    insert(RunEventRow).values(
                        run_id=ids[0],
                        sequence=sequence,
                        payload={
                            "kind": "presentation",
                            "sequence": sequence,
                            "presentation": {"data": {"draft_id": str(draft_id)}},
                        },
                    )
                )
        path = f"/sessions/{session_id}/runs"
        first = client.get(path, params={"limit": 2}, headers=owner)
        assert first.status_code == 200
        page = first.json()
        assert [item["run_id"] for item in page["items"]] == [str(ids[1]), str(ids[0])]
        assert page["items"][1]["prompt"] == "消息0"
        assert page["items"][0]["error_code"] == "timeout"
        assert page["items"][1]["draft_id"] == str(draft_id)
        assert [event["sequence"] for event in page["items"][1]["presentations"]] == [3, 4, 5, 6]
        seen = {item["run_id"] for item in page["items"]}
        cursor = page["next_before"]
        new_run_id = uuid4()
        with engine.begin() as db:
            db.execute(
                insert(TaskRunRow).values(
                    id=new_run_id,
                    user_id=user_id,
                    session_id=session_id,
                    client_message_id=uuid4(),
                    prompt="新增",
                    mode="offline",
                    status="completed",
                    answer="新增答复",
                    created_at=STAMP + timedelta(minutes=1),
                )
            )
        while cursor:
            page = client.get(path, params={"limit": 2, "before": cursor}, headers=owner).json()
            assert not seen.intersection(item["run_id"] for item in page["items"])
            assert all(item["draft_id"] is None for item in page["items"])
            seen.update(item["run_id"] for item in page["items"])
            cursor = page["next_before"]
        assert seen == {str(key) for key in ids}
        assert client.get(f"/sessions/{other_session}/runs", headers=owner).status_code == 404
        assert client.get(path, headers=other).status_code == 404
        with engine.connect() as db:
            stored = db.execute(
                select(TaskRunRow.id, TaskRunRow.status).where(TaskRunRow.session_id == session_id)
            ).all()
            assert {str(row[0]) for row in stored} == seen | {str(new_run_id)}
            assert {row[1] for row in stored} == {
                "completed",
                "failed",
                "cancelled",
                "running",
                "partial",
            }
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 51},
        {"limit": "x"},
        {"cursor": "bad"},
        {"cursor": "a" * 257},
        {"cursor": "eyJ2IjoyfQ"},
    ],
)
def test_session_history_rejects_invalid_paging(
    client: TestClient, query: dict[str, str | int]
) -> None:
    assert client.get("/sessions", params=query, headers=login(client)).status_code == 422


@pytest.mark.parametrize("query", [{"limit": -1}, {"before": "bad"}, {"before": "a" * 257}])
def test_run_history_rejects_invalid_paging(
    client: TestClient, query: dict[str, str | int]
) -> None:
    owner = login(client)
    path = f"/sessions/{new_session(client, owner)}/runs"
    assert client.get(path, params=query, headers=owner).status_code == 422


@pytest.mark.parametrize(
    "data",
    [
        None,
        [2, "2026-10-08T00:00:00+00:00", str(uuid4())],
        [True, "2026-10-08T00:00:00+00:00", str(uuid4())],
        [1, "2026-10-08", str(uuid4())],
        [1, "bad-time", str(uuid4())],
        [1, "2026-10-08T00:00:00+00:00", "bad-uuid"],
    ],
)
def test_history_rejects_invalid_cursor_payloads(client: TestClient, data: object) -> None:
    owner = login(client)
    encoded = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    assert client.get("/sessions", params={"cursor": encoded}, headers=owner).status_code == 422
    path = f"/sessions/{new_session(client, owner)}/runs"
    assert client.get(path, params={"before": encoded}, headers=owner).status_code == 422


def test_history_database_outage_is_unavailable_instead_of_empty(postgres_url: URL) -> None:
    with socket.socket() as closed_port:
        closed_port.bind(("127.0.0.1", 0))
        app = create_app(SessionService(postgres_url.set(port=closed_port.getsockname()[1])))
        with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
            for path in ("/sessions", f"/sessions/{uuid4()}/runs"):
                result = client.get(path, headers={"Authorization": "Bearer synthetic-unavailable"})
                assert result.status_code == 503
                assert result.json() == {"code": "unavailable", "message": "数据库暂不可用"}
                assert str(postgres_url.password) not in result.text
