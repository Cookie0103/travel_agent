"""R01/R03：真实PostgreSQL消息去重、单会话执行、取消、SSE归属与持久读取。"""

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import DeadlockDetected
from sqlalchemy import URL
from sqlalchemy.exc import OperationalError

from backend.agent.runtime import EventSink, FakeRuntime
from backend.api.app import create_app
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.persistence import runs
from backend.services.common import ServiceError
from backend.services.runs import MessageInput, RunService
from backend.services.sessions import SessionService
from backend.services.travel import TravelService
from tests.integration.test_sessions import login
from tests.integration.test_travel import evidence
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_persistence_failure_exposes_only_type_sqlstate_and_requires_recovery(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R12/R17：真实PG终态写入故障，不假报完成；诊断不输出原始SQL/参数。"""
    runner, travel, context = travel_setup
    service = RunService(
        travel.database,
        runtime_factory=lambda executor: FakeRuntime(
            RuntimeOutcome(text="完成", sdk_session_id="synthetic")
        ),
    )

    async def fail(*args: object) -> None:
        raise OperationalError(
            "private SQL", {"key": "secret-value"}, DeadlockDetected("private original message")
        )

    monkeypatch.setattr(runs, "finish", fail)

    async def exercise() -> None:
        run = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text="查询"),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        with pytest.raises(ServiceError, match="需要恢复核对"):
            await service.get(context.user_id, run.run_id)
        assert run.run_id in service.persistence_failures
        await service.close()

    runner.run(exercise())
    assert "error=ServiceError sqlstate=40P01" in caplog.text
    assert "private" not in caplog.text and "secret-value" not in caplog.text


class WaitingRuntime(FakeRuntime):
    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        self.resumed.append(sdk_session_id)
        await cancelled.wait()
        # 故意模拟模型在取消时仍返回成功，数据库裁决必须保持取消。
        return self.outcome


def test_concurrent_duplicate_message_runs_once_and_other_message_conflicts(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    runtime = WaitingRuntime(RuntimeOutcome(text="late", sdk_session_id="fake-session"))
    service = RunService(travel.database, runtime_factory=lambda executor: runtime)
    message = MessageInput(client_message_id=uuid4(), text="京都博物馆")

    async def exercise() -> None:
        first, duplicate = await asyncio.gather(
            *(service.submit(context.user_id, context.session_id, message) for _ in range(2))
        )
        assert first.run_id == duplicate.run_id
        with pytest.raises(ServiceError, match="已有执行"):
            await service.submit(
                context.user_id,
                context.session_id,
                message.model_copy(update={"client_message_id": uuid4()}),
            )
        with pytest.raises(ServiceError, match="不同内容"):
            await service.submit(
                context.user_id, context.session_id, message.model_copy(update={"text": "changed"})
            )
        await service.cancel(context.user_id, first.run_id)
        await service.close()
        assert runtime.resumed == [None]
        final = await service.get(context.user_id, first.run_id)
        assert final.status == "cancelled" and final.error_code == "cancelled"
        events = await service.events(context.user_id, first.run_id, 0)
        assert [event["kind"] for event in events] == ["started", "cancelled"]
        assert [event["sequence"] for event in events] == [1, 2]
        assert await service.cancel(context.user_id, first.run_id) == final
        assert (
            await service.submit(context.user_id, context.session_id, message)
        ).run_id == first.run_id

    runner.run(exercise())


def test_failed_runtime_persists_one_terminal_and_releases_session(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    service = RunService(
        travel.database,
        runtime_factory=lambda executor: FakeRuntime(
            RuntimeOutcome(code="unavailable", reason="fixture")
        ),
    )

    async def exercise() -> None:
        for _ in range(2):
            run = await service.submit(
                context.user_id,
                context.session_id,
                MessageInput(client_message_id=uuid4(), text="查询"),
            )
            await asyncio.gather(*tuple(service.tasks.values()))
            assert (await service.get(context.user_id, run.run_id)).status == "failed"
            events = await service.events(context.user_id, run.run_id, 0)
            assert [event["kind"] for event in events] == ["started", "failed"]

    runner.run(exercise())


def test_run_deadline_is_timeout_not_user_cancel(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, travel, context = travel_setup
    monkeypatch.setattr("backend.services.runs.RUN_TIMEOUT", 0.01)
    runtime = WaitingRuntime(RuntimeOutcome(sdk_session_id="fake"))
    service = RunService(travel.database, runtime_factory=lambda executor: runtime)

    async def exercise() -> None:
        run = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text="挂起"),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        final = await service.get(context.user_id, run.run_id)
        events = await service.events(context.user_id, run.run_id, 0)
        assert final.status == "failed" and final.error_code == "timeout"
        assert events[-1]["kind"] == "failed" and events[-1]["code"] == "timeout"

    runner.run(exercise())


def test_api_run_events_are_private_and_new_app_does_not_reexecute(postgres_url: URL) -> None:
    sessions = SessionService(postgres_url, demo_enabled=True)
    runtime = FakeRuntime(RuntimeOutcome(text="离线结果", sdk_session_id="fake"), ("离线结果",))
    service = RunService(sessions.database, runtime_factory=lambda executor: runtime)
    app = create_app(sessions, runs_service=service)
    options = {"loop_factory": asyncio.SelectorEventLoop}
    with TestClient(app, backend_options=options) as client:
        owner, other = login(client), login(client)
        session_id = client.post("/sessions", headers=owner).json()["session_id"]
        path = f"/sessions/{session_id}/messages"
        message = {"client_message_id": str(uuid4()), "text": "京都"}
        assert client.post(path, headers=other, json=message).status_code == 404
        assert client.post(path, headers=owner, json={**message, "mode": "live"}).status_code == 403
        created = client.post(path, headers=owner, json=message)
        assert created.status_code == 202
        run_path = "/runs/" + created.json()["run_id"]
        event_path = run_path + "/events"
        stream = client.get(event_path, headers=owner)
        assert stream.status_code == 200
        events = [
            json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")
        ]
        assert [event["kind"] for event in events] == ["started", "text", "completed"]
        assert client.get(run_path, headers=owner).json()["answer"] == "离线结果"
        assert client.get(run_path, headers=other).status_code == 404
        assert client.get(event_path, headers=other).status_code == 404
        assert client.post(run_path + "/cancel", headers=other).status_code == 404
        assert (
            client.get(event_path, headers={**owner, "Last-Event-ID": "invalid"}).status_code == 422
        )
        assert client.get(event_path + "?after=999", headers=owner).status_code == 422
        assert (
            client.post(path, headers=owner, json=message).json()["run_id"]
            == created.json()["run_id"]
        )
    with TestClient(create_app(SessionService(postgres_url)), backend_options=options) as restarted:
        replay = restarted.get(event_path, headers={**owner, "Last-Event-ID": "2"})
        assert "id: 3" in replay.text and "id: 1" not in replay.text
        assert restarted.get(run_path, headers=owner).json()["status"] == "completed"
    assert runtime.resumed == [None]


def test_next_turn_gets_bounded_owned_dialogue_and_valid_evidence(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from datetime import UTC, datetime, timedelta

    runner, travel, context = travel_setup
    runtime = FakeRuntime(RuntimeOutcome(text="刚才第二个景点是二条城", sdk_session_id="fake"))
    service = RunService(travel.database, runtime_factory=lambda executor: runtime)

    async def exercise() -> None:
        request = await travel.get_request(context)
        valid = evidence(request, "place")
        expired = evidence(request, "place").model_copy(
            update={
                "retrieved_at": datetime.now(UTC) - timedelta(hours=1),
                "valid_until": datetime.now(UTC) - timedelta(minutes=1),
            }
        )
        await travel.record_evidence(context, [valid])
        from backend.persistence.travel import add_evidence
        from backend.services.common import transaction

        async with transaction(travel.database) as db:
            await add_evidence(db, context, [expired])
        for index in range(3):
            await service.submit(
                context.user_id,
                context.session_id,
                MessageInput(client_message_id=uuid4(), text=f"提问{index}"),
            )
            await asyncio.gather(*tuple(service.tasks.values()))
        recalled = await travel.business_context(context)
        observed_at = datetime.fromisoformat(str(recalled["observed_at"]))
        assert valid.valid_until is not None
        assert valid.retrieved_at <= observed_at < valid.valid_until
        assert recalled["recent_dialogue"] == [
            {"user": f"提问{i}", "assistant": runtime.outcome.text, "truncated": False}
            for i in (1, 2)
        ]
        refs = recalled["evidence_references"]
        assert (
            isinstance(refs, list)
            and len(refs) == 1
            and refs[0]["evidence_id"] == str(valid.evidence_id)
        )
        with pytest.raises(ServiceError, match="会话不存在"):
            await travel.business_context(RunContext(uuid4(), context.session_id))

    runner.run(exercise())
