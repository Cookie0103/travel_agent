"""真实PG：已确认的长期交通偏好视为已知（缺项、路线默认），不写进request；本次明说只覆盖本次。离线。"""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select

from backend.domain.conversation import ConversationState, task_missing
from backend.domain.execution import RunContext
from backend.domain.travel_request import RequestPatch, TravelRequest
from backend.persistence.models import MemoryFactRow
from backend.services.common import transaction
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_ask_and_select import KNOWN, choice_card, goals, run_of
from tests.integration.test_planning import destinations
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("fixed_today")]

Setup = tuple[asyncio.Runner, TravelService, RunContext]


async def known_without_transport(travel: TravelService, run: RunContext) -> None:
    await travel.patch_request(
        run,
        RequestPatch.model_validate(
            {
                "expected_revision": (await travel.read_request(run)).revision,
                "set": {k: v for k, v in KNOWN.items() if k != "transport"},
            }
        ),
    )


def missing_of(view: dict[str, object]) -> list[str]:
    missing = view["missing_fields"]
    assert isinstance(missing, list)
    return missing


def groups_of(view: dict[str, object]) -> set[str]:
    form = choice_card(view).form
    assert form is not None
    return {group.key for group in form.groups}


def transport_of(result: ToolResult) -> object:
    routes = result.data["routes"]
    assert isinstance(routes, list)
    return routes[0]["transport"]


async def remember(travel: TravelService, context: RunContext, value: str = "transit") -> None:
    async with transaction(travel.database) as db:
        db.add(
            MemoryFactRow(
                user_id=context.user_id,
                key="transport",
                value=value,
                scope="long_term",
                status="active",
                source="manual",
                ordinal=0,
            )
        )


def test_task_missing_uses_the_default_only_when_request_has_none() -> None:
    request = TravelRequest.model_validate({"city": "京都", "adults": 1, "child_ages": []})
    assert "transport" in task_missing(request, "itinerary")
    assert "transport" not in task_missing(request, "itinerary", transport_default="transit")
    assert ConversationState()  # 状态本身不变


def test_long_term_transport_is_not_missing_nor_asked_and_not_written_to_request(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await remember(travel, context)
        run = await run_of(travel, context)
        await known_without_transport(travel, run)
        view = await goals(travel, run, "itinerary")
        assert "transport" not in missing_of(view)
        assert view["defaults"] == {
            "transport": {"value": "transit", "label": "公共交通", "source": "long_term"}
        }
        if "choice" in view:
            assert "transport" not in groups_of(view)
        assert (await travel.read_request(run)).transport is None  # 不冒充本次用户所说
        seen = (await travel.business_context(run))["conversation"]
        assert isinstance(seen, dict) and "transport" not in missing_of(seen)
        assert seen["defaults"] == view["defaults"]

    runner.run(exercise())


def test_user_without_long_term_transport_still_gets_the_card_group_and_missing(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        run = await run_of(travel, context)
        await known_without_transport(travel, run)
        view = await goals(travel, run, "itinerary")
        assert "transport" in missing_of(view) and "defaults" not in view
        assert "transport" in groups_of(view)

    runner.run(exercise())


def test_routes_default_to_long_term_transport_and_a_trip_choice_overrides_it(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup
    executor = TravelToolExecutor(travel)

    async def legs(revision: int) -> dict[str, object]:
        first, second = await destinations(travel, context)
        return {
            "expected_revision": revision,
            "legs": [
                {
                    "from_evidence_id": str(first.evidence_id),
                    "to_evidence_id": str(second.evidence_id),
                    "departure": "2026-11-03T11:00+09:00",
                }
            ],
        }

    async def exercise() -> None:
        await remember(travel, context)
        result = await executor.execute(context, "estimate_routes", await legs(1))
        assert result.code is None
        assert transport_of(result) == "transit"
        request = await travel.read_request(context)
        assert request.transport is None
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": request.revision, "set": {"transport": "walk"}}
            ),
        )
        request = await travel.read_request(context)
        override = await executor.execute(context, "estimate_routes", await legs(request.revision))
        assert override.code is None and transport_of(override) == "walk"
        async with transaction(travel.database) as db:
            fact = await db.scalar(
                select(MemoryFactRow).where(
                    MemoryFactRow.user_id == context.user_id, MemoryFactRow.key == "transport"
                )
            )
        assert fact and (fact.value, fact.scope, fact.status) == ("transit", "long_term", "active")
        assert isinstance(UUID(str(fact.id)), UUID)

    runner.run(exercise())
