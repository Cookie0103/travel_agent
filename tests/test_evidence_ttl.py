"""酒店报价不绑定请求revision、证据有效期与修复轮次随档位变化（DEFAULT/RELAXED行为不变）。"""

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from backend.adapters.external_api import ApiUsage
from backend.adapters.rakuten import Rakuten, candidates
from backend.domain.external_data import GeoPoint
from backend.domain.hotels import HotelOffer, quote
from backend.domain.itinerary import ItineraryProposal
from backend.domain.travel_request import TravelRequest
from backend.domain.validator import (
    HOTEL_CONDITIONS_REASON,
    HOTEL_EXPIRED_REASON,
    validate_itinerary,
)
from backend.persistence.database import Database
from backend.profile import DEFAULT, HUMAN, RELAXED
from backend.providers.claude_agent.database_tools import DatabaseTools
from backend.providers.hotel_fixture import load_rates
from backend.services.common import ServiceError
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from tests.test_external_data import sample
from tests.test_itinerary import NOW, item, place, record, request


def hotel_offer() -> HotelOffer:
    rates, _ = load_rates()
    offer = quote(rates[0], request(), NOW)
    assert offer is not None
    return offer


def validate(
    current: TravelRequest,
    offer: HotelOffer,
    now: datetime = NOW,
    *,
    trust_record_conditions: bool = False,
) -> None:
    """trust_record_conditions=True模拟证据层已放行(记录条件与当前一致)，直接命中hotel_cost。"""
    destination = record(place(), current).model_copy(
        update={"valid_until": NOW + timedelta(hours=2)}
    )
    hotel = record(offer, current if trust_record_conditions else request()).model_copy(
        update={"valid_until": offer.expires_at, "retrieved_at": offer.quoted_at}
    )
    proposal = ItineraryProposal(
        expected_revision=current.revision,
        items=(item(destination),),
        hotel_evidence_id=hotel.evidence_id,
    )
    validate_itinerary(current, proposal, (destination, hotel), now)


def test_offer_survives_revision_bump_from_unrelated_update() -> None:
    later = request().model_copy(
        update={
            "revision": 7,
            "transport": "transit",
            "budget": Decimal(99999),
            "interests": ("美食",),
        }
    )
    validate(later, hotel_offer())  # 只改交通/预算/兴趣，不应抛错


@pytest.mark.parametrize(
    "change",
    [
        {"start_date": date(2026, 11, 4)},
        {"end_date": date(2026, 11, 6)},
        {"adults": 3},
        {"child_ages": (5,)},
        {"rooms": 2},
        {"currency": "USD"},
        {"city": "大阪"},
    ],
)
def test_changed_stay_conditions_are_rejected_with_actionable_message(
    change: dict[str, Any],
) -> None:
    with pytest.raises(ValueError) as caught:
        validate(
            request().model_copy(update={**change, "revision": 2}),
            hotel_offer(),
            trust_record_conditions=True,
        )
    assert str(caught.value) == HOTEL_CONDITIONS_REASON and "重新search_hotel_offers" in str(
        caught.value
    )


@pytest.mark.parametrize("change", [{"adults": 3}, {"city": "大阪"}, {"currency": "USD"}])
def test_changed_conditions_are_also_stale_at_the_evidence_layer(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="失效"):
        validate(request().model_copy(update={**change, "revision": 2}), hotel_offer())


def test_expired_or_not_yet_valid_offer_is_rejected_with_expiry_message() -> None:
    offer = hotel_offer()
    with pytest.raises(ValueError) as caught:
        validate(request(), offer, offer.expires_at + timedelta(seconds=1))
    # 证据层(valid_until)先于报价层(expires_at)拦截时为"失效"；报价自身过期走到期文案
    assert "失效" in str(caught.value) or str(caught.value) == HOTEL_EXPIRED_REASON
    past = offer.model_copy(update={"quoted_at": NOW - timedelta(hours=2)})
    short = past.model_copy(update={"expires_at": NOW - timedelta(hours=1)})
    stale = record(short).model_copy(update={"valid_until": NOW + timedelta(minutes=5)})
    destination = record(place())
    proposal = ItineraryProposal(
        expected_revision=1, items=(item(destination),), hotel_evidence_id=stale.evidence_id
    )
    with pytest.raises(ValueError) as expired:
        validate_itinerary(request(), proposal, (destination, stale), NOW)
    assert str(expired.value) == HOTEL_EXPIRED_REASON
    assert "重新search_hotel_offers" in HOTEL_EXPIRED_REASON


def test_offer_id_mismatch_keeps_generic_message() -> None:
    offer = hotel_offer()
    destination = record(place())
    hotel = record(offer).model_copy(update={"entity_id": "other"})
    proposal = ItineraryProposal(
        expected_revision=1, items=(item(destination),), hotel_evidence_id=hotel.evidence_id
    )
    with pytest.raises(ValueError, match="住宿报价与证据不一致"):
        validate_itinerary(request(), proposal, (destination, hotel), NOW)


class _Usage:
    run_caps = {"rakuten": 8}
    default_profile = True


@pytest.mark.parametrize("profile,minutes", [("", 15), ("relaxed", 15), ("human", 30)])
def test_rakuten_offer_expiry_follows_profile(
    profile: str, minutes: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", profile)
    first = candidates(sample())

    async def query(*_: object, **__: object) -> tuple[tuple[object, ...], None]:
        return first, None

    monkeypatch.setattr(Rakuten, "query", query)

    async def run() -> tuple[HotelOffer, ...]:
        trip = request().model_copy(update={"end_date": date(2026, 11, 7)})
        async with httpx.AsyncClient() as http:
            provider = Rakuten("t", "t", "", "", http, cast(ApiUsage, _Usage()))
            point = GeoPoint(name="京都", latitude=35, longitude=135)
            return await provider.search(trip, point)

    offers = asyncio.run(run())
    assert offers
    for offer in offers:
        assert offer.expires_at - offer.quoted_at == timedelta(minutes=minutes)


def test_human_offer_valid_at_29_minutes_and_invalid_at_31() -> None:
    quoted = NOW
    offer = hotel_offer().model_copy(
        update={
            "quoted_at": quoted,
            "expires_at": quoted + timedelta(minutes=HUMAN.evidence_ttl_minutes),
        }
    )
    validate(request(), offer, quoted + timedelta(minutes=29))
    with pytest.raises(ValueError):
        validate(request(), offer, quoted + timedelta(minutes=31))


def test_default_offer_invalid_at_16_minutes_valid_at_14() -> None:
    offer = hotel_offer().model_copy(
        update={
            "quoted_at": NOW,
            "expires_at": NOW + timedelta(minutes=DEFAULT.evidence_ttl_minutes),
        }
    )
    validate(request(), offer, NOW + timedelta(minutes=14))
    with pytest.raises(ValueError):
        validate(request(), offer, NOW + timedelta(minutes=16))


def test_profile_values_table() -> None:
    assert [(p.evidence_ttl_minutes, p.max_validations) for p in (DEFAULT, RELAXED, HUMAN)] == [
        (15, 4),
        (15, 4),
        (30, 50),
    ]


def repair_executor(limit: int) -> TravelToolExecutor:
    fake = cast(TravelService, type("T", (), {"live": None, "database": None})())
    return TravelToolExecutor(fake, max_validations=limit)


@pytest.mark.parametrize("limit,label", [(4, "3轮"), (50, "49轮")])
def test_repair_rounds_follow_limit_and_message_states_actual_value(limit: int, label: str) -> None:
    tools = repair_executor(limit)
    proposal = cast(Any, object())
    for _ in range(limit):
        tools._take_validation(proposal)
    assert tools.validations == limit
    with pytest.raises(ServiceError) as caught:
        tools._take_validation(proposal)  # 第limit+1次被拦
    assert caught.value.reason == "repair_limit" and label in str(caught.value)


@pytest.mark.parametrize("bad", [0, 51, True, "4"])
def test_max_validations_outside_range_is_rejected(bad: Any) -> None:
    with pytest.raises(ValueError):
        repair_executor(bad)


@pytest.mark.parametrize("profile,rounds", [("", 4), ("relaxed", 4), ("human", 50)])
def test_live_database_tools_use_profile_repair_rounds(
    profile: str, rounds: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAVEL_PROFILE", profile)
    loop = asyncio.new_event_loop()
    try:
        tools = DatabaseTools(loop, cast(Database, object()))
    finally:
        loop.close()
    assert tools.executor.max_validations == rounds


OLD_TOOL = "检查引用证据的行程；冲突需修正，未知保留警告。首次校验后最多修复3轮，不能改写报告。"
OLD_PROMPT = (
    "展示行程前调用validate_itinerary；conflict按具体反馈修正，"
    "首次校验后最多3轮，不放宽用户硬条件。"
)
OLD_SKILL = "提出PlanPatch后校验营业时间、路段、时区和预算；冲突最多修复3轮，未知信息保留警告。"


def rendered_texts(limit: int) -> tuple[str, str, str]:
    from backend.agent.persona import travel_prompt
    from backend.tools.contracts import repair_rounds, with_repair_rounds
    from backend.tools.travel import DEFINITIONS, repair_definitions

    tool = next(
        d for d in repair_definitions(DEFINITIONS, limit) if d.name == "validate_itinerary"
    ).description
    skill_path = Path(__file__).resolve().parents[1] / "backend/tools/skills/itinerary-revision.md"
    skill = with_repair_rounds(skill_path.read_text(encoding="utf-8"), limit)
    return tool, travel_prompt(repair_rounds(limit)), skill


@pytest.mark.parametrize("limit", [1, 4])
def test_static_repair_text_is_unchanged_for_default_and_eval_variant(limit: int) -> None:
    tool, prompt, skill = rendered_texts(limit)
    assert tool == OLD_TOOL and OLD_PROMPT in prompt and OLD_SKILL in skill


def test_static_repair_text_follows_human_profile() -> None:
    tool, prompt, skill = rendered_texts(50)
    assert tool == OLD_TOOL.replace("修复3轮", "修复49轮")
    assert "首次校验后最多49轮，不放宽" in prompt and "冲突最多修复49轮" in skill
    assert not any("3轮" in text for text in (tool, prompt, skill))
