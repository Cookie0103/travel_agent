"""R02：应用引用隔离和终态语义；不是跨进程数据库恢复的替代测试。"""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from backend.agent.runtime import Agent, EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity, RuntimeOutcome
from tests.fakes import FakeRuntime


@pytest.mark.asyncio
async def test_known_reference_resumes_once_and_foreign_user_is_blocked() -> None:
    fake = FakeRuntime(RuntimeOutcome("京都", "sdk-one"), ("京都",))
    agent = Agent(fake)
    context = RunContext(uuid4())
    events: list[RuntimeEvent] = []
    first = await agent.run(context, "室内景点", events.append)
    assert first.reference
    foreign = replace(context, user_id=uuid4(), run_id=uuid4())
    denied = await agent.run(foreign, "继续", events.append, reference_id=first.reference.id)
    assert denied.outcome.reason == "unknown_session"
    next_context = replace(context, run_id=uuid4())
    second = await agent.run(next_context, "继续", events.append, reference_id=first.reference.id)
    assert second.reference and second.reference.context == next_context
    stale = await agent.run(context, "继续", events.append, reference_id=first.reference.id)
    assert stale.outcome.code == "blocked"
    assert fake.resumed == [None, "sdk-one"]
    assert [e.kind for e in events[:3]] == ["started", "text", "completed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["provider", "model", "sdk_version", "cli_version"])
async def test_changed_runtime_identity_starts_new_sdk_session(field: str) -> None:
    fake = FakeRuntime(RuntimeOutcome("ok", "sdk-one"))
    agent = Agent(fake)
    context = RunContext(uuid4())
    first = await agent.run(context, "问", lambda event: None)
    assert first.reference
    identity = fake.identity
    values = {
        name: getattr(identity, name)
        for name in ("provider", "model", "sdk_version", "cli_version")
    }
    values[field] = "different"
    fake.identity = RuntimeIdentity(**values)
    await agent.run(context, "再问", lambda event: None, reference_id=first.reference.id)
    assert fake.resumed == [None, None]


@pytest.mark.asyncio
async def test_unknown_session_and_blank_input_do_not_call_runtime() -> None:
    fake = FakeRuntime(RuntimeOutcome("ok", "sdk"))
    agent = Agent(fake)
    context = RunContext(uuid4())
    missing = await agent.run(context, "问", lambda event: None, reference_id=uuid4())
    blank = await agent.run(context, "  ", lambda event: None)
    assert missing.outcome.code == "blocked" and blank.outcome.code == "validation"
    assert fake.resumed == []


@pytest.mark.asyncio
async def test_cancelled_or_incomplete_run_never_creates_reference() -> None:
    fake = FakeRuntime(RuntimeOutcome("text without final SDK session"))
    agent = Agent(fake)
    events: list[RuntimeEvent] = []
    failed = await agent.run(RunContext(uuid4()), "问", events.append)
    assert failed.reference is None and events[-1].kind == "failed"
    cancel = asyncio.Event()
    cancel.set()
    cancel_events: list[RuntimeEvent] = []
    result = await agent.run(RunContext(uuid4()), "问", cancel_events.append, cancelled=cancel)
    assert result.reference is None and cancel_events[-1].kind == "cancelled"


@pytest.mark.asyncio
async def test_same_session_cannot_run_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    fake = FakeRuntime(RuntimeOutcome("ok", "sdk-one"))

    async def wait_for_release(
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        entered.set()
        await release.wait()
        return fake.outcome

    monkeypatch.setattr(fake, "execute", wait_for_release)
    agent, context = Agent(fake), RunContext(uuid4())
    first = asyncio.create_task(agent.run(context, "问", lambda e: None))
    await asyncio.wait_for(entered.wait(), 1)
    try:
        second = await agent.run(replace(context, run_id=uuid4()), "再问", lambda e: None)
        assert second.outcome.code == "conflict"
    finally:
        release.set()
        await first


@pytest.mark.asyncio
async def test_unexpected_runtime_failure_is_sanitized_and_unlocks_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRuntime(RuntimeOutcome("ok", "sdk-one"))
    agent, context = Agent(fake), RunContext(uuid4())
    initial = await agent.run(context, "问", lambda e: None)
    assert initial.reference

    async def fail(
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        raise RuntimeError("secret-error-body")

    monkeypatch.setattr(fake, "execute", fail)
    result = await agent.run(context, "再问", lambda e: None, reference_id=initial.reference.id)
    assert result.outcome.code == "provider_error" and "secret-error-body" not in str(result)
    monkeypatch.undo()
    stale = await agent.run(context, "续接", lambda e: None, reference_id=initial.reference.id)
    retry = await agent.run(context, "新会话", lambda e: None)
    assert stale.outcome.code == "blocked" and retry.outcome.code is None


@pytest.mark.asyncio
async def test_model_change_during_run_cannot_relabel_old_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    old = FakeRuntime(RuntimeOutcome("old", "old-sdk"))
    new = FakeRuntime(RuntimeOutcome("new", "new-sdk"))
    new.identity = replace(new.identity, model="new-model")
    agent, context = Agent(old), RunContext(uuid4())

    async def delayed(
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        entered.set()
        await release.wait()
        return old.outcome

    monkeypatch.setattr(old, "execute", delayed)
    task = asyncio.create_task(agent.run(context, "问", lambda e: None))
    await asyncio.wait_for(entered.wait(), 1)
    agent.runtime = new
    release.set()
    first = await task
    assert first.reference and first.reference.identity == old.identity
    second = await agent.run(context, "继续", lambda e: None, reference_id=first.reference.id)
    assert second.reference and second.reference.identity == new.identity
    assert new.resumed == [None]
