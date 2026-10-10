"""真实PG：酒店三态持久展示、离线空结果与守卫，不新增写入/订单。"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.travel_request import RequestPatch
from backend.persistence.models import EvidenceRow, PlanRow, PlanVersionRow
from backend.services.common import ServiceError, transaction
from backend.services.runs import RunService
from backend.services.travel import TravelService
from backend.services.views import HotelPresentation
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from tests.integration.test_travel import travel_setup as travel_setup
from tests.integration.test_workbench import run_demo

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("state", ["success", "empty", "failure"])
def test_three_hotel_states_survive_runservice_restart_and_owner_checks(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    runner, travel, context = travel_setup
    if state == "empty":
        monkeypatch.setattr("backend.services.hotels.load_rates", lambda: ((), "synthetic-empty"))
    elif state == "failure":

        def fail() -> None:
            raise OSError("synthetic-private-path")

        monkeypatch.setattr("backend.services.hotels.load_rates", fail)

    async def exercise() -> None:
        service = RunService(travel.database)
        run = await run_demo(service, context, "演示：比较酒店")
        assert run.status == ("failed" if state == "failure" else "completed")
        assert run.error_code == ("unavailable" if state == "failure" else None)
        assert len(run.presentations) == 1
        event = run.presentations[0]
        event_context, payload = event["context"], event["presentation"]
        assert isinstance(event_context, dict) and isinstance(payload, dict)
        assert event_context["session_id"] == str(context.session_id)
        panel = HotelPresentation.model_validate(payload["data"])
        assert bool(panel.cards) == (state == "success")
        if state != "success":
            assert not panel.comparison.comparable and not panel.comparison.lowest_offer_ids
        if state == "empty":
            assert "没有找到" in run.answer
        assert "synthetic-private" not in str(run)
        restarted = RunService(travel.database)
        restored = await restarted.get(context.user_id, run.run_id)
        assert restored.presentations == run.presentations
        with pytest.raises(ServiceError):
            await restarted.get(uuid4(), run.run_id)
        async with transaction(travel.database) as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(PlanVersionRow)
                    .join(PlanRow)
                    .where(PlanRow.session_id == context.session_id)
                )
                == 0
            )
            count = await db.scalar(
                select(func.count())
                .select_from(EvidenceRow)
                .where(EvidenceRow.session_id == context.session_id)
            )
            assert (count or 0) > 0 if state == "success" else count == 0
        await service.close()
        await restarted.close()

    runner.run(exercise())


def test_failure_panel_keeps_budget_revision_and_unknown_id_guards_without_quotes(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup

    def never_query() -> None:
        pytest.fail("guard must reject before quoting")

    monkeypatch.setattr("backend.services.hotels.load_rates", never_query)

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "budget": "50000",
                        "lodging_budget": {
                            "amount": {"lower": "30000", "upper": "30000"},
                            "currency": "JPY",
                            "basis": "per_room_night",
                        },
                    },
                }
            ),
        )
        executor = TravelToolExecutor(travel)
        operations: tuple[tuple[str, dict[str, object], str], ...] = (
            ("search_hotel_offers", {"expected_revision": 1}, "conflict"),
            ("search_hotel_offers", {"expected_revision": 2}, "conflict"),
            (
                "present_travel_result",
                {
                    "component": "hotel_comparison",
                    "expected_revision": 2,
                    "offer_ids": [str(uuid4())],
                },
                "conflict",
            ),
            ("refresh_hotel_offer", {"expected_revision": 2, "offer_id": str(uuid4())}, "blocked"),
        )
        for name, args, code in operations:
            events: list[RuntimeEvent] = []
            result = await execute_observed(
                executor,
                context,
                name,
                args,
                events.append,
                definition=next(d for d in DEFINITIONS if d.name == name),
            )
            assert result.code == code and not result.data
            assert events[-1].kind == "presentation"
            assert "cards': []" in str(events[-1].presentation)
        request = await travel.get_request(context)
        assert request.revision == 2 and str(request.budget) == "50000"
        assert (
            request.lodging_budget is not None
            and str(request.lodging_budget.amount.lower) == "30000"
        )
        async with transaction(travel.database) as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(EvidenceRow)
                    .where(EvidenceRow.session_id == context.session_id)
                )
                == 0
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(PlanVersionRow)
                    .join(PlanRow)
                    .where(PlanRow.session_id == context.session_id)
                )
                == 0
            )

    runner.run(exercise())
