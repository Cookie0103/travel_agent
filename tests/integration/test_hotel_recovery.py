"""真实PG：预算放宽须点选；接受/保持、重放、报价有效性共用原消息事务。"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from backend.adapters.external_api import ApiUsage
from backend.adapters.rakuten import Rakuten
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.external_data import GeoPoint
from backend.domain.hotel_recovery import HotelSearchDiagnostics
from backend.domain.travel_request import RequestPatch
from backend.persistence import runs
from backend.services.choices import ChoiceService
from backend.services.common import ServiceError
from backend.services.hotels import HotelService, cards
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_external_data import sample
from tests.test_hotel_recovery import budget_request

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("option", ["accept", "keep"])
def test_budget_choice_requires_click_and_preserves_quotes(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    option: str,
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        patch = RequestPatch.model_validate(
            {
                "expected_revision": 1,
                "set": {
                    "lodging_budget": {
                        "amount": {"upper": "5000"},
                        "currency": "JPY",
                        "basis": "per_room_night",
                    },
                },
            }
        )
        changed = await travel.patch_request(original, patch, source="user_form")
        request = changed.request
        async with travel.database.sessions.begin() as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "合成酒店请求", "offline"
            )
            context = RunContext(original.user_id, original.session_id, row.id)
        records, diagnosis, card = await HotelService(travel).search_result(
            context, request.revision
        )
        assert records and isinstance(diagnosis, HotelSearchDiagnostics) and card
        before = await travel.get_request(context)
        assert before.lodging_budget and before.lodging_budget.amount.upper == Decimal(5000)
        assert diagnosis.applied_upper and diagnosis.applied_upper > Decimal(5000)
        assert card.expires_at == min(r.valid_until for r in records if r.valid_until)
        with pytest.raises(ServiceError) as refused:
            await travel.patch_request(
                context,
                RequestPatch.model_validate(
                    {
                        "expected_revision": before.revision,
                        "set": {
                            "lodging_budget": {
                                "amount": {"upper": "30000"},
                                "currency": "JPY",
                                "basis": "per_room_night",
                            }
                        },
                    }
                ),
                source="conversation",
                explicit_fields=("lodging_budget",),
            )
        assert refused.value.reason == "hotel_budget_requires_selection"
        async with travel.database.sessions.begin() as db:
            await runs.finish(db, context, RuntimeOutcome(text="请接受或保持预算"))
        service = RunService(travel.database)
        message = MessageInput.model_validate(
            {
                "client_message_id": str(uuid4()),
                "text": "合成预算选择",
                "expected_revision": before.revision,
                "selection": {"choice_id": str(card.choice_id), "option_id": option},
            }
        )
        submitted = await service.submit(original.user_id, original.session_id, message)
        assert (
            await service.submit(original.user_id, original.session_id, message)
        ).run_id == submitted.run_id
        await asyncio.gather(*tuple(service.tasks.values()))
        after = await travel.get_request(context)
        assert after.lodging_budget
        assert after.lodging_budget.amount.upper == (
            diagnosis.applied_upper if option == "accept" else Decimal(5000)
        )
        assert after.revision == before.revision + (option == "accept")
        assert all(
            r.status == "verified"
            for r in await travel.resolve_evidence(context, tuple(r.evidence_id for r in records))
        )
        restored_cards = cards(
            await travel.resolve_evidence(context, tuple(r.evidence_id for r in records)), after
        )
        assert all(c["request_revision"] == after.revision for c in restored_cards)
        assert (
            await ChoiceService(travel).get(original.user_id, original.session_id, card.choice_id)
        ).answered_option_id == option

    runner.run(exercise())


def test_price_sorted_requery_preserves_s0_when_daily_quota_is_exhausted(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, _ = travel_setup

    async def exercise() -> None:
        request = budget_request("4000")
        assert request.start_date
        request = request.model_copy(update={"end_date": request.start_date + timedelta(days=1)})
        async with travel.database.sessions() as db:
            existing_calls = (
                await db.scalar(
                    text("SELECT calls FROM external_api_usage WHERE day=:day AND api='rakuten'"),
                    {"day": datetime.now(UTC).date()},
                )
                or 0
            )
        usage = ApiUsage(
            travel.database,
            {"RAKUTEN_DAILY_CAP": str(existing_calls + 1), "RAKUTEN_MIN_INTERVAL_SECONDS": "0"},
        )
        calls = 0

        def respond(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=sample())

        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
                diagnosis = HotelSearchDiagnostics()
                offers = await Rakuten("test", "test", "", "", http, usage).search_diagnosed(
                    request,
                    GeoPoint(name="京都", latitude=35, longitude=135),
                    diagnosis=diagnosis,
                    rescue_segments=1,
                )
        finally:
            async with travel.database.sessions.begin() as db:
                await db.execute(
                    text(
                        "UPDATE external_api_usage SET calls=calls-:delta "
                        "WHERE day=:day AND api='rakuten'"
                    ),
                    {"day": datetime.now(UTC).date(), "delta": usage.used.get("rakuten", 0)},
                )
        assert calls == 1 and offers and offers[0].total is not None
        assert diagnosis.skipped == "quota" and diagnosis.tier is None
        assert diagnosis.original_upper == Decimal(4000)

    runner.run(exercise())


def test_different_segment_tiers_have_distinct_bound_choices(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        changed = await travel.patch_request(
            original,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "lodging_budget": {
                            "amount": {"upper": "5000"},
                            "currency": "JPY",
                            "basis": "per_room_night",
                        }
                    },
                }
            ),
        )
        async with travel.database.sessions.begin() as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "多段预算", "offline"
            )
            context = RunContext(original.user_id, original.session_id, row.id)
        service = ChoiceService(travel)
        first = await service.propose_budget(
            context,
            changed.request,
            HotelSearchDiagnostics(
                original_upper=Decimal(5000), applied_upper=Decimal(7500), tier=Decimal("1.5")
            ),
        )
        second = await service.propose_budget(
            context,
            changed.request,
            HotelSearchDiagnostics(
                original_upper=Decimal(5000), applied_upper=Decimal(10000), tier=Decimal(2)
            ),
        )
        assert first.choice_id != second.choice_id
        assert "10000" in second.options[0].label
        assert (
            await service.create(context, "budget_relaxation", changed.request.revision)
        ).choice_id == second.choice_id
        from backend.domain.choices import ChoiceSelection
        from backend.services.choices import owned_card

        async with travel.database.sessions.begin() as db:
            stored = await owned_card(db, original.user_id, original.session_id, second.choice_id)
            await service.accept(
                db,
                context,
                stored,
                ChoiceSelection(choice_id=second.choice_id, option_id="accept"),
                2,
            )
        current = await travel.get_request(context)
        assert current.lodging_budget and current.lodging_budget.amount.upper == Decimal(10000)

    runner.run(exercise())


@pytest.mark.parametrize("bypass", ["unrelated_revision", "keep"])
def test_budget_guard_survives_unrelated_revision_and_keep(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    bypass: str,
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            original,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "lodging_budget": {
                            "amount": {"upper": "5000"},
                            "currency": "JPY",
                            "basis": "per_room_night",
                        }
                    },
                }
            ),
        )
        async with travel.database.sessions.begin() as db:
            row = await runs.create(
                db, original.user_id, original.session_id, uuid4(), "预算确认", "offline"
            )
            context = RunContext(original.user_id, original.session_id, row.id)
        _, _, card = await HotelService(travel).search_result(context, 2)
        assert card
        if bypass == "unrelated_revision":
            await travel.patch_request(
                context,
                RequestPatch.model_validate(
                    {"expected_revision": 2, "set": {"interests": ["寺院"]}}
                ),
            )
        else:
            from backend.domain.choices import ChoiceSelection
            from backend.services.choices import owned_card

            async with travel.database.sessions.begin() as db:
                stored = await owned_card(db, original.user_id, original.session_id, card.choice_id)
                await ChoiceService(travel).accept(
                    db,
                    context,
                    stored,
                    ChoiceSelection(choice_id=card.choice_id, option_id="keep"),
                    2,
                )
        request = await travel.get_request(context)
        with pytest.raises(ServiceError) as rejected:
            await travel.patch_request(
                context,
                RequestPatch.model_validate(
                    {
                        "expected_revision": request.revision,
                        "set": {"lodging_budget_unlimited": True},
                        "clear": ["lodging_budget"],
                    }
                ),
                source="conversation",
                explicit_fields=("lodging_budget", "lodging_budget_unlimited"),
            )
        assert rejected.value.reason == "hotel_budget_requires_selection"

    runner.run(exercise())
