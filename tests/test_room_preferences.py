"""仅明确房型词可降级；价格/评级不参与排序。"""

import asyncio
from datetime import date

import httpx
import pytest

from backend.adapters.rakuten import Rakuten
from backend.agent.fixture_conditions import fixture_patch
from backend.domain.external_data import GeoPoint
from backend.domain.room_preferences import room_assessment, room_order, room_preferences_question
from backend.domain.travel_request import TravelRequest
from tests.test_external_data import _CountingUsage
from tests.test_hotels import request


@pytest.mark.parametrize(
    "name,tag",
    [
        ("女性専用ドミトリー", "宿舍"),
        ("male-only capsule", "舱房"),
        ("学生限定双床", "资格限定"),
        ("会员专用大床", "资格限定"),
    ],
)
def test_explicit_shared_or_restricted_room_has_visible_tags(name: str, tag: str) -> None:
    result = room_assessment(name, TravelRequest(hard_constraints=("住宿：独立房间",)))
    assert tag in result.room_tags
    assert result.qualification_unknown


def test_only_qualification_changes_order_and_both_partitions_are_stable() -> None:
    names = ["ドミトリー", "standard twin", "女性専用シングル", "capsule", "普通大床"]
    private = TravelRequest(hard_constraints=("住宿：独立房间",))
    assert room_order(names, private) == (1, 4, 0, 2, 3)
    assert room_order(names, TravelRequest()) == (0, 1, 3, 4, 2)
    result = room_assessment("standard twin", private)
    assert not result.qualification_unknown and not result.room_preference_mismatch
    assert "未核实全部资格" in result.room_tags


def test_missing_preferences_have_no_defaults_and_explicit_no_preference_is_answer() -> None:
    assert room_preferences_question(TravelRequest())
    complete = TravelRequest(hard_constraints=("住宿：无要求", "房型：无要求", "床型：无要求"))
    assert room_preferences_question(complete) is None
    assert room_preferences_question(
        complete.model_copy(
            update={"hard_constraints": (*complete.hard_constraints, "住宿：独立房间")}
        )
    )


def test_conversation_replaces_only_named_group_and_preserves_unrelated_constraints() -> None:
    current = TravelRequest(
        hard_constraints=("不坐飞机", "住宿：接受宿舍", "房型：禁烟", "床型：双床")
    )
    patch = fixture_patch("住宿改为独立房间", current, date(2026, 10, 8))
    assert patch["set"] == {
        "hard_constraints": ["不坐飞机", "房型：禁烟", "床型：双床", "住宿：独立房间"]
    }
    assert patch["explicit_fields"] == ["hard_constraints"]
    assert fixture_patch("独立房间，禁烟，双床", TravelRequest(), date(2026, 10, 8))["set"] == {
        "hard_constraints": ["住宿：独立房间", "房型：禁烟", "床型：双床"]
    }
    assert fixture_patch("住宿无要求，禁烟无要求，床型无要求", TravelRequest(), date(2026, 10, 8))[
        "set"
    ] == {"hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"]}
    assert fixture_patch("不要宿舍", current, date(2026, 10, 8))["set"] == {}


def test_live_selection_demotes_before_limit_without_extra_query_or_price_sort() -> None:
    async def exercise() -> None:
        usage = _CountingUsage({})
        trip = request().model_copy(
            update={"end_date": date(2026, 11, 7), "hard_constraints": ("住宿：独立房间",)}
        )

        def respond(query: httpx.Request) -> httpx.Response:
            assert "sort" not in query.url.params
            return httpx.Response(
                200,
                json={
                    "hotels": [
                        [
                            {"hotelBasicInfo": {"hotelNo": i, "hotelName": f"合成{i}"}},
                            {
                                "roomInfo": [
                                    {
                                        "roomBasicInfo": {
                                            "roomClass": str(i),
                                            "roomName": name,
                                            "planId": i,
                                        }
                                    },
                                    {
                                        "dailyCharge": {
                                            "stayDate": "2026-11-06",
                                            "rakutenCharge": amount,
                                            "chargeFlag": 0,
                                        }
                                    },
                                ]
                            },
                        ]
                        for i, name, amount in (
                            (1, "女性専用ドミトリー", 1000),
                            (2, "普通双床", 9000),
                            (3, "capsule", 1000),
                            (4, "普通大床", 5000),
                        )
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            offers = await Rakuten("test", "test", "", "", http, usage).search(
                trip, GeoPoint(name="京都", latitude=35, longitude=135), limit=2
            )
        assert [offer.hotel_id for offer in offers] == ["2", "4"]
        assert [offer.total for offer in offers] == [18000, 10000]
        assert usage.calls == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("prompt", ["不用独立房间", "无需双床", "不需要禁烟", "不要求大床"])
def test_direct_negation_does_not_save_positive_room_fact(prompt: str) -> None:
    assert fixture_patch(prompt, TravelRequest(), date(2026, 10, 8))["set"] == {}


def test_one_no_preference_answer_covers_three_dimensions() -> None:
    assert fixture_patch("房型无要求", TravelRequest(), date(2026, 10, 8))["set"] == {
        "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"]
    }


@pytest.mark.parametrize("bed", ["床型：大床房", "床型：大床优先", "大床最好"])
def test_explicit_bed_alias_is_recognized_without_losing_original_preference(bed: str) -> None:
    trip = TravelRequest(hard_constraints=("住宿：独立房间", "房型：禁烟", bed, "不接受青旅"))
    assert room_preferences_question(trip) is None
    assert "床型：大床" in trip.hard_constraints
    assert "不接受青旅" in trip.hard_constraints
    if "优先" in bed or "最好" in bed:
        assert bed in trip.hard_constraints


def test_alias_and_canonical_bed_are_same_fact_but_two_different_choices_still_clarify() -> None:
    trip = TravelRequest(
        hard_constraints=("住宿：独立房间", "房型：禁烟", "床型：大床房", "床型：大床")
    )
    assert room_preferences_question(trip) is None
    conflict = TravelRequest(hard_constraints=(*trip.hard_constraints, "床型：双床"))
    assert "床型" in (room_preferences_question(conflict) or "")
    denied = TravelRequest(hard_constraints=("住宿：独立房间", "房型：禁烟", "不要大床"))
    assert "床型" in (room_preferences_question(denied) or "")


def test_old_twenty_constraints_with_bed_preference_remain_readable_and_recognized() -> None:
    from backend.domain.room_choices import missing_room_choices
    from tests.fixtures.legacy_travel_request_v1 import TravelRequest as OldRequest

    old = OldRequest(hard_constraints=tuple(f"合成其他要求{i}" for i in range(19)) + ("大床优先",))
    current = TravelRequest.model_validate(old.model_dump())
    assert len(current.hard_constraints) <= 20 and "大床优先" in current.hard_constraints
    assert "bed" not in missing_room_choices(current.hard_constraints)
    OldRequest.model_validate(current.model_dump(exclude={"lodging_budget"}))


def test_explicit_private_room_with_exclusion_text_is_not_missing_or_conflicting() -> None:
    trip = TravelRequest(
        hard_constraints=("住宿：独立房间，不接受宿舍青旅", "房型：禁烟", "床型：无要求")
    )
    assert room_preferences_question(trip) is None
    assert "住宿：独立房间，不接受宿舍青旅" in trip.hard_constraints
    conflict = TravelRequest(
        hard_constraints=("住宿：独立房间，接受宿舍", "房型：禁烟", "床型：无要求")
    )
    assert room_preferences_question(conflict)


def test_typed_same_choice_at_twenty_constraint_limit_is_noop() -> None:
    from backend.domain.travel_request import ConversationRequestPatch, apply_request_patch

    current = TravelRequest(
        hard_constraints=tuple(f"其他要求{i}" for i in range(17))
        + ("住宿：独立房间", "房型：禁烟", "床型：无要求")
    )
    patch = ConversationRequestPatch.model_validate(
        {
            "expected_revision": 0,
            "set": {"hard_constraints": list(current.hard_constraints)},
            "room_preferences": {"bed": "any"},
        }
    )
    updated, changed = apply_request_patch(current, patch)
    assert updated == current and not changed
