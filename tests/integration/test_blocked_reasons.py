"""blocked的原因码：可达路径逐条复现，原因码随tool_finished事件持久化，旧事件无该字段仍可读取。"""

import asyncio
from uuid import UUID, uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from backend.persistence import runs
from backend.services.common import transaction
from backend.services.travel import TravelService
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration

VALIDATE = next(d for d in DEFINITIONS if d.name == "validate_itinerary")


async def observed(
    executor: TravelToolExecutor, context: RunContext, arguments: dict[str, object]
) -> RuntimeEvent:
    events: list[RuntimeEvent] = []
    await execute_observed(
        executor, context, "validate_itinerary", arguments, events.append, definition=VALIDATE
    )
    return next(e for e in events if e.kind == "tool_finished")


def test_validate_blocked_paths_record_closed_reason_codes(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        first, _ = await destinations(travel, context)
        good = proposal(first).model_dump(mode="json")
        # 路径1：证据不存在/不属于本人(模型编造或沿用别的会话的evidence_id)。
        forged = {**good, "items": [{**good["items"][0], "place_evidence_id": str(uuid4())}]}
        executor = TravelToolExecutor(travel)
        event = await observed(executor, context, forged)
        assert (event.code, event.reason) == ("blocked", "evidence_missing")
        # 该路径在_dispatch里先占用一次修复轮次(既有设计：被拒绝的校验也计数)。
        assert executor.validations == 1
        # 路径2：身份/会话不一致的上下文，拿不到旅行条件 -> not_found。
        stranger = RunContext(uuid4(), context.session_id)
        event = await observed(TravelToolExecutor(travel), stranger, good)
        assert (event.code, event.reason) == ("blocked", "not_found")
        # 路径3：修复轮次用尽。
        limited = TravelToolExecutor(travel, max_validations=1)
        assert (await observed(limited, context, good)).reason is None
        event = await observed(limited, context, {**good, "items": good["items"]})
        assert (event.code, event.reason) == ("blocked", "repair_limit")
        # 路径4：调用次数上限；路径5：未注册工具由单测覆盖。
        capped = TravelToolExecutor(travel, max_calls=0)
        event = await observed(capped, context, good)
        assert (event.code, event.reason) == ("blocked", "tool_call_cap")

    runner.run(exercise())


def test_repeat_guard_skips_budget_until_another_call_succeeds(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        first, _ = await destinations(travel, context)
        good = proposal(first).model_dump(mode="json")
        forged = {**good, "items": [{**good["items"][0], "place_evidence_id": str(uuid4())}]}
        executor = TravelToolExecutor(travel)
        one = await executor.execute(context, "validate_itinerary", forged)
        calls, rounds = executor.calls, executor.validations
        again = await executor.execute(context, "validate_itinerary", forged)
        assert "evidence_missing" in one.detail and again.detail[0] == "repeat_blocked"
        assert again.code == "blocked" and "修改输入" in again.suggestion
        assert (executor.calls, executor.validations) == (calls, rounds)
        ok = await executor.execute(context, "search_places", {"city": "京都", "limit": 1})
        assert ok.code is None
        retried = await executor.execute(context, "validate_itinerary", forged)
        assert "evidence_missing" in retried.detail and "repeat_blocked" not in retried.detail

    runner.run(exercise())


def test_reason_is_persisted_and_legacy_event_without_it_still_loads(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, context.user_id, context.session_id, uuid4(), "p", "fixture"
            )
            run = RunContext(context.user_id, context.session_id, row.id)
            await runs.append_event(
                db,
                RuntimeEvent(
                    run, "tool_finished", tool_name="x", code="blocked", reason="repair_limit"
                ),
            )
            await runs.append_event(db, RuntimeEvent(run, "tool_finished", tool_name="y"))
            legacy = {
                k: v
                for k, v in (await runs.events(db, row.id, 0))[1].payload.items()
                if k != "reason"
            }
            rows = await runs.events(db, row.id, 0)
            rows[1].payload = legacy
            await db.flush()
        async with transaction(travel.database) as db:
            payloads = [r.payload for r in await runs.events(db, UUID(str(row.id)), 0)]
        assert payloads[0]["reason"] == "repair_limit"
        assert "reason" not in payloads[1]

    runner.run(exercise())
