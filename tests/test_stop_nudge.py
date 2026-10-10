"""Stop钩子提醒文本与运行级失败原因的持久化边界（P-98）。"""

import asyncio
from collections.abc import Iterator
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeOutcome, terminal_event
from backend.providers.claude_agent.database_tools import DatabaseTools


@pytest.fixture
def loop() -> Iterator[asyncio.AbstractEventLoop]:
    worker = asyncio.new_event_loop()
    thread = Thread(target=worker.run_forever, daemon=True)
    thread.start()
    yield worker
    worker.call_soon_threadsafe(worker.stop)
    thread.join(5)
    worker.close()


def tools(
    loop: asyncio.AbstractEventLoop,
    conversation: dict[str, object],
    *,
    stopping: bool = False,
    calls: int = 0,
) -> DatabaseTools:
    async def business_context(context: RunContext) -> dict[str, object]:
        return {"conversation": conversation}

    instance = object.__new__(DatabaseTools)
    instance.loop = loop
    instance.travel = SimpleNamespace(business_context=business_context)  # type: ignore[assignment]  # 只需business_context
    instance.executor = SimpleNamespace(stopping_error=stopping, calls=calls, max_calls=16)  # type: ignore[assignment]  # 同上
    return instance


@pytest.mark.asyncio
async def test_itinerary_nudge_names_the_concrete_tool_sequence_and_attempt(
    loop: asyncio.AbstractEventLoop,
) -> None:
    text = await tools(
        loop, {"awaiting_field": None, "ready_tasks": ["itinerary"]}
    ).continuation_reason(RunContext(uuid4()), 2)
    assert text is not None and "这是第2次提醒" in text and "不要只写总结文字就结束" in text
    order = [
        text.index(name)
        for name in (
            "estimate_routes",
            "validate_itinerary",
            "stage_plan_change",
            "present_travel_result",
        )
    ]
    assert order == sorted(order) and "component=itinerary" in text and "draft_id" in text
    assert "search_hotel_offers" not in text and "住宿预算未知允许查询" in text


@pytest.mark.asyncio
async def test_hotel_nudge_names_search_then_present(loop: asyncio.AbstractEventLoop) -> None:
    text = await tools(
        loop, {"awaiting_field": None, "ready_tasks": ["hotel_comparison"]}
    ).continuation_reason(RunContext(uuid4()), 1)
    assert text is not None and "这是第1次提醒" in text
    assert text.index("search_hotel_offers") < text.index("component=hotel_comparison")
    assert "estimate_routes" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conversation,stopping,calls",
    [
        ({"awaiting_field": "city", "ready_tasks": ["itinerary"]}, False, 0),
        ({"awaiting_field": None, "ready_tasks": []}, False, 0),
        ({"awaiting_field": None, "ready_tasks": ["itinerary"]}, True, 0),
        ({"awaiting_field": None, "ready_tasks": ["itinerary"]}, False, 16),
    ],
)
async def test_no_nudge_when_asking_user_done_errored_or_capped(
    loop: asyncio.AbstractEventLoop,
    conversation: dict[str, object],
    stopping: bool,
    calls: int,
) -> None:
    instance = tools(loop, conversation, stopping=stopping, calls=calls)
    assert await instance.continuation_reason(RunContext(uuid4()), 1) is None


@pytest.mark.parametrize(
    "reason", ["conversation_incomplete", "conversation_state_unavailable", "max_turns"]
)
def test_failed_event_persists_only_closed_run_reasons(reason: str) -> None:
    event = terminal_event(RunContext(uuid4()), RuntimeOutcome(code="blocked", reason=reason))
    assert event.kind == "failed" and event.reason == reason


@pytest.mark.parametrize(
    "outcome",
    [
        RuntimeOutcome(code="provider_error", reason="private provider text sk-secret"),
        RuntimeOutcome(code="cancelled", reason="max_turns"),
        RuntimeOutcome(),
    ],
)
def test_other_outcome_reasons_are_never_persisted(outcome: RuntimeOutcome) -> None:
    assert terminal_event(RunContext(uuid4()), outcome).reason is None
