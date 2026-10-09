"""乐天酒店发现（P-81）：按施设每家一张最低价卡；用两份真实脱敏样本验证。"""

import asyncio
import copy
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from pydantic import JsonValue

from backend.adapters.rakuten import MIN_PERSON_NIGHT_PRICE, Rakuten, candidates
from backend.domain.external_data import ExternalDataError, GeoPoint
from backend.domain.hotels import HotelOffer
from backend.domain.travel_request import TravelRequest
from tests.test_external_data import _CountingUsage, fixture

PLAN_1 = "rakuten_naha_plan_pattern1_2026-10-11.json"  # 旧行为：按套餐，最便宜的10个
HOTEL_0 = "rakuten_naha_hotel_pattern0_2026-10-11.json"  # 新行为：按施设
POINT = GeoPoint(name="那霸", latitude=26.2124, longitude=127.6809)
PRIVATE_NONSMOKING = ("住宿：独立房间", "房型：禁烟", "床型：无要求")
Handler = Callable[[httpx.Request], httpx.Response]


def trip(nights: int = 1, constraints: tuple[str, ...] = PRIVATE_NONSMOKING) -> TravelRequest:
    start = date(2026, 10, 11)
    return TravelRequest(
        city="那霸",
        start_date=start,
        end_date=start + timedelta(days=nights),
        adults=1,
        child_ages=(),
        rooms=1,
        revision=1,
        hard_constraints=constraints,
    )


async def run(
    handler: Handler,
    request: TravelRequest | None = None,
    *,
    limit: int = 5,
    hotel_id: str | None = None,
) -> tuple[tuple[HotelOffer, ...], _CountingUsage]:
    usage = _CountingUsage({})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        found = await Rakuten("test", "test", "", "", http, usage).search(
            request or trip(),
            POINT,
            limit=limit,
            hotel_id=hotel_id,
        )
    return found, usage


def serve(payload: dict[str, JsonValue], seen: list[httpx.Request] | None = None) -> Handler:
    def handle(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        return httpx.Response(200, json=payload)

    return handle


def entries(payload: dict[str, JsonValue]) -> list[list[dict[str, Any]]]:
    return cast(list[list[dict[str, Any]]], payload["hotels"])


def room_parts(hotel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """roomInfo里的roomBasicInfo/dailyCharge字段块（样本为v2的字段数组）。"""
    return [room for part in hotel for room in part.get("roomInfo", [])]


def set_charge(payload: dict[str, JsonValue], amount: int) -> None:
    for hotel in entries(payload):
        for room in room_parts(hotel):
            if "dailyCharge" in room:
                room["dailyCharge"]["rakutenCharge"] = amount


def test_pattern1_sample_documents_old_failure_six_hotels_promo_prices() -> None:
    items = candidates(fixture(PLAN_1))
    assert len({item.hotel.hotelNo for item in items}) == 6 and len(items) == 10
    prices = sorted(item.charge.rakutenCharge for item in items if item.charge)
    assert prices[:4] == [1, 1, 1, 500]
    # 旧逻辑下独立房间过滤后只剩142912；新规则也不会把¥500当真实价，只剩¥1500的双床。
    found, _ = asyncio.run(run(serve(fixture(PLAN_1))))
    assert [(o.hotel_id, o.included_total) for o in found] == [("142912", Decimal(1500))]


def test_hotel_pattern_sample_gives_five_distinct_hotels_in_upstream_order() -> None:
    seen: list[httpx.Request] = []
    found, usage = asyncio.run(run(serve(fixture(HOTEL_0), seen)))
    assert [o.hotel_id for o in found] == ["134763", "19934", "67292", "104526", "130025"]
    assert len({o.hotel_id for o in found}) == 5 and usage.calls == 1
    assert all(o.included_total and o.included_total >= MIN_PERSON_NIGHT_PRICE for o in found)
    assert found[2].included_total == Decimal(7830)
    params = dict(seen[0].url.params)
    assert (params["searchPattern"], params["hits"], params["sort"]) == ("0", "30", "standard")
    assert params["squeezeCondition"] == "kinen" and "hotelNo" not in params
    details = found[0].display_details
    assert details is not None and details.price_basis == "乐天返回的该酒店符合条件的套餐中最低价"
    assert details.search_total_found == 187
    assert details.more_url == "https://travel.rakuten.co.jp/yado/okinawa/nahashi.html"
    assert details.more_url_scope == "destination"


@pytest.mark.parametrize("metadata", ["present", "missing", "null"])
def test_real_hotel_sample_metadata_is_parsed_or_unknown(metadata: str) -> None:
    payload = copy.deepcopy(fixture(HOTEL_0))
    if metadata != "present":
        for part in entries(payload)[0]:
            if "hotelBasicInfo" in part:
                basic = part["hotelBasicInfo"]
                for key in ("address1", "address2", "latitude", "longitude", "reviewCount"):
                    if metadata == "missing":
                        basic.pop(key, None)
                    else:
                        basic[key] = None
    found, _ = asyncio.run(run(serve(payload)))
    assert found[0].hotel_id == "134763"
    details = found[0].display_details
    assert details is not None
    actual = (details.address, details.latitude, details.longitude, details.review_count)
    if metadata == "present":
        assert actual == ("沖縄県那覇市おもろまち1-1-12", 26.22326054, 127.6953298, 1732)
    else:
        assert actual == (None, None, None, None)


def test_squeeze_condition_is_sent_only_when_nonsmoking_is_a_hard_constraint() -> None:
    seen: list[httpx.Request] = []
    anything = trip(constraints=("住宿：无要求", "房型：无要求", "床型：无要求"))
    asyncio.run(run(serve(fixture(HOTEL_0), seen), anything))
    assert "squeezeCondition" not in seen[0].url.params


def test_limit_smaller_or_larger_than_eligible_hotels() -> None:
    assert len(asyncio.run(run(serve(fixture(HOTEL_0)), limit=2))[0]) == 2
    assert len(asyncio.run(run(serve(fixture(HOTEL_0)), limit=6))[0]) == 6


def test_same_hotel_twice_is_one_card_with_cheapest_plan() -> None:
    payload = copy.deepcopy(fixture(HOTEL_0))
    twin = copy.deepcopy(entries(payload)[0])
    for room in room_parts(twin):
        if "roomBasicInfo" in room:
            room["roomBasicInfo"]["planId"] = 1
        if "dailyCharge" in room:
            room["dailyCharge"]["rakutenCharge"] = 9000
    entries(payload).insert(1, twin)
    found, _ = asyncio.run(run(serve(payload)))
    assert [o.hotel_id for o in found].count("134763") == 1
    assert found[0].rate_id.startswith("rakuten:134763:1:") and found[0].included_total == 9000


def test_promo_floor_excludes_plan_and_hotel_without_other_plan() -> None:
    payload = copy.deepcopy(fixture(HOTEL_0))
    set_charge(payload, 999)  # 地板为1000：999不可信，全部酒店跳过，不补0也不展示
    found, _ = asyncio.run(run(serve(payload)))
    assert found == ()
    set_charge(payload, 1000)
    assert len(asyncio.run(run(serve(payload)))[0]) == 5


def test_every_plan_dorm_or_capsule_leaves_no_hotel_when_private_room_required() -> None:
    payload = copy.deepcopy(fixture(HOTEL_0))
    for hotel in entries(payload):
        for room in room_parts(hotel):
            if "roomBasicInfo" in room:
                room["roomBasicInfo"]["roomName"] = "男性ドミトリー"
    assert asyncio.run(run(serve(payload)))[0] == ()
    accepting = trip(constraints=("住宿：接受宿舍", "房型：禁烟", "床型：无要求"))
    assert len(asyncio.run(run(serve(payload), accepting))[0]) == 5


def test_empty_404_and_zero_hotels_yield_no_offers() -> None:
    assert asyncio.run(run(lambda _: httpx.Response(404, json={"error": "not_found"})))[0] == ()
    assert asyncio.run(run(serve({"pagingInfo": {"recordCount": 0}, "hotels": []})))[0] == ()


@pytest.mark.parametrize("payload", [{}, {"hotels": "x"}, {"hotels": [{}]}])
def test_malformed_response_is_external_data_error(payload: dict[str, JsonValue]) -> None:
    with pytest.raises(ExternalDataError):
        asyncio.run(run(serve(payload)))


def test_unknown_total_count_and_unsafe_area_codes_are_omitted() -> None:
    payload = copy.deepcopy(fixture(HOTEL_0))
    del payload["pagingInfo"]
    for hotel in entries(payload):
        for part in hotel:
            if "hotelDetailInfo" in part:
                part["hotelDetailInfo"]["middleClassCode"] = "../evil?x=1"
    details = asyncio.run(run(serve(payload)))[0][0].display_details
    assert details is not None
    assert details.search_total_found is None and details.more_url is None
    assert details.more_url_scope is None


def test_multi_night_requeries_shown_hotels_with_same_plan_and_unknown_when_plan_missing() -> None:
    first = fixture(HOTEL_0)
    second = copy.deepcopy(first)
    set_charge(second, 10000)
    for hotel in entries(second):
        for room in room_parts(hotel):
            if "dailyCharge" in room:
                room["dailyCharge"]["stayDate"] = "2026-10-12"
    # 第二晚 134763 的套餐号变了：同计划不可得，不能用别的套餐凑总价。
    for room in room_parts(entries(second)[0]):
        if "roomBasicInfo" in room:
            room["roomBasicInfo"]["planId"] = 1
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=first if len(seen) == 1 else second)

    found, usage = asyncio.run(run(handle, trip(2)))
    assert usage.calls == 2
    again = dict(seen[1].url.params)
    assert again["hotelNo"] == "134763,19934,67292,104526,130025"
    assert (again["searchPattern"], again["squeezeCondition"]) == ("0", "kinen")
    assert found[0].included_total is None and "完整总价未知" in (found[0].total_reason or "")
    assert found[1].included_total == Decimal(12600 + 10000)


def test_single_hotel_lookup_lists_its_plans_by_plan_without_discovery_summary() -> None:
    seen: list[httpx.Request] = []
    found, _ = asyncio.run(run(serve(fixture(PLAN_1), seen), hotel_id="142912"))
    params = dict(seen[0].url.params)
    assert (params["searchPattern"], params["hotelNo"]) == ("1", "142912")
    assert {o.hotel_id for o in found} == {"142912"}
    assert all(o.included_total != 500 for o in found)  # ¥500单人房是促销价
    details = found[0].display_details
    assert details is not None and details.more_url is None and details.price_basis is None


def test_charge_per_room_is_divided_by_adults_for_the_floor() -> None:
    item = candidates(fixture(HOTEL_0))[0]
    assert item.charge
    request = trip().model_copy(update={"adults": 2})
    per_room = item.model_copy(
        update={"charge": item.charge.model_copy(update={"chargeFlag": 1, "rakutenCharge": 1800})}
    )
    assert Rakuten.price_unreliable(per_room, request)  # 1800/2人=900/人
    assert not Rakuten.price_unreliable(
        per_room.model_copy(
            update={
                "charge": per_room.charge
                and per_room.charge.model_copy(update={"rakutenCharge": 2000})
            }
        ),
        request,
    )


def test_later_night_promo_price_makes_total_unknown() -> None:
    first = fixture(HOTEL_0)
    second = copy.deepcopy(first)
    for hotel in entries(second):
        for room in room_parts(hotel):
            if "dailyCharge" in room:
                room["dailyCharge"]["stayDate"] = "2026-10-12"
                room["dailyCharge"]["rakutenCharge"] = 500
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=first if len(seen) == 1 else second)

    found, _ = asyncio.run(run(handle, trip(2)))
    assert found and all(o.included_total is None for o in found)
    assert all("完整总价未知" in (o.total_reason or "") for o in found)


def test_malformed_hotel_detail_only_drops_the_more_url() -> None:
    payload = copy.deepcopy(fixture(HOTEL_0))
    for hotel in entries(payload):
        for part in hotel:
            if "hotelDetailInfo" in part:
                part["hotelDetailInfo"] = []
    found, _ = asyncio.run(run(serve(payload)))
    details = found[0].display_details
    assert len(found) == 5 and details is not None and details.more_url is None


def test_single_hotel_plan_cap_and_limit_without_extra_nightly_calls() -> None:
    base = fixture(PLAN_1)
    hotel = entries(base)[3]  # 142912，带planId的真实套餐
    rows: list[list[dict[str, Any]]] = []
    for no, plan in [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (3, 1), (3, 2), (4, 1), (5, 1)]:
        copy_ = copy.deepcopy(hotel)
        for part in copy_:
            if "hotelBasicInfo" in part:
                part["hotelBasicInfo"]["hotelNo"] = no
        for room in room_parts(copy_):
            if "roomBasicInfo" in room:
                room["roomBasicInfo"]["planId"] = plan
                room["roomBasicInfo"]["roomName"] = "シングルルーム"
            if "dailyCharge" in room:
                room["dailyCharge"]["rakutenCharge"] = 5000
        rows.append(copy_)
    payload = cast(dict[str, JsonValue], {"hotels": rows})
    seen: list[httpx.Request] = []
    # 无hotel_id走发现模式：每家一张；有hotel_id走套餐模式：同店最多2个
    found, usage = asyncio.run(run(serve(payload, seen), limit=4))
    assert [o.hotel_id for o in found] == ["1", "2", "3", "4"] and usage.calls == 1
    found, _ = asyncio.run(run(serve(payload), hotel_id="1"))
    assert [o.hotel_id for o in found] == ["1", "1"]
