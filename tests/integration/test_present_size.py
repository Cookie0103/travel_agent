"""酒店对比展示整体作为工具结果：5张真实形态卡片必须首轮通过长度限制。"""

import asyncio
import copy
import json
from typing import Any, cast
from urllib.parse import quote_plus
from uuid import UUID

import httpx
import pytest
from pydantic import JsonValue

from backend.adapters.rakuten import Rakuten
from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext
from backend.domain.external_data import GeoPoint
from backend.domain.travel_request import RequestPatch
from backend.services.travel import TravelService
from backend.tools.contracts import PRESENTATION_RESULT_LIMIT, RESULT_LIMIT
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_external_data import _CountingUsage, fixture

HOTEL_0 = "rakuten_naha_hotel_pattern0_2026-10-11.json"
AFFILIATE = "1a2b3c4d.5e6f7a8b.9c0d1e2f.3a4b5c6d"  # 乐天联盟ID形态；生成长联盟链接
POINT = GeoPoint(name="那霸", latitude=26.2124, longitude=127.6809)


def real_shaped(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """脱敏样本不含链接/图片；补上真实长度的乐天联盟链接，卡片才有真实体量(约2.9k字/张)。"""
    payload = copy.deepcopy(payload)
    for hotel in cast(list[list[dict[str, Any]]], payload["hotels"]):
        number = hotel[0]["hotelBasicInfo"]["hotelNo"]
        target = quote_plus(
            f"https://img.travel.rakuten.co.jp/image/tr/api/re/{number}/?f_hotel_no={number}"
        )
        affiliate = f"https://hb.afl.rakuten.co.jp/hgc/{AFFILIATE}/?pc="
        info = hotel[0]["hotelBasicInfo"]
        info["hotelInformationUrl"] = affiliate + target
        info["planListUrl"] = affiliate + target + "&plan=list"
        info["hotelImageUrl"] = (
            f"https://img.travel.rakuten.co.jp/share/HOTEL/{number}/{number}.jpg"
        )
        for room in [r for part in hotel for r in part.get("roomInfo", [])]:
            if "roomBasicInfo" in room:
                room["roomBasicInfo"]["reserveUrl"] = affiliate + target + "&reserve=1"
    return payload


async def rakuten_quotes(
    travel: TravelService, context: RunContext, count: int
) -> list[EvidenceRecord]:
    """真实脱敏样本 -> 现有适配器 -> 与HotelService直播分支相同的证据记录。"""
    payload = real_shaped(fixture(HOTEL_0))
    # 与样本一致的单晚那霸条件，才会得到完整总价与预订/联盟链接。
    await travel.patch_request(
        context,
        RequestPatch.model_validate(
            {
                "expected_revision": 1,
                "set": {
                    "city": "那霸",
                    "adults": 1,
                    "start_date": "2026-10-11",
                    "end_date": "2026-10-12",
                    "hard_constraints": ["住宿：独立房间", "房型：禁烟", "床型：无要求"],
                },
            }
        ),
    )
    request = await travel.get_request(context)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        offers = await Rakuten("test", "test", "", AFFILIATE, http, _CountingUsage({})).search(
            request, POINT, limit=count
        )
    assert len(offers) == count
    records = [
        EvidenceRecord(
            entity_id=str(offer.offer_id),
            field_path="hotel_offer",
            value=offer.model_dump(mode="json"),
            display_details=offer.display_details,
            kind="hotel_offer",
            request_revision=request.revision,
            conditions=evidence_conditions(request, "hotel_offer"),
            provider="rakuten_travel",
            source_ref=offer.booking_url,
            content_version=offer.quoted_at.isoformat(),
            retrieved_at=offer.quoted_at,
            valid_until=offer.expires_at,
            data_mode="live",
        )
        for offer in offers
    ]
    await travel.record_evidence(context, records)
    return records


def present_args(records: list[EvidenceRecord]) -> dict[str, object]:
    return {
        "component": "hotel_comparison",
        "expected_revision": 2,
        "offer_ids": [r.entity_id for r in records],
    }


@pytest.mark.parametrize("count", [5, 6])
def test_real_shaped_hotel_cards_pass_the_first_present_call(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], count: int
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        records = await rakuten_quotes(travel, context, count)
        result = await TravelToolExecutor(travel).execute(
            context, "present_travel_result", present_args(records)
        )
        assert result.code is None, result.detail
        cards = result.data["cards"]
        assert isinstance(cards, list) and len(cards) == count
        size = len(json.dumps(result.payload(), ensure_ascii=False))
        assert RESULT_LIMIT < size <= PRESENTATION_RESULT_LIMIT  # 旧限制下会被拒绝

    runner.run(exercise())


def test_presentation_above_the_new_limit_is_still_blocked(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        records = await rakuten_quotes(travel, context, 5)
        executor = TravelToolExecutor(travel)
        original = executor.hotels.present

        async def oversized(
            context: RunContext, revision: int, ids: tuple[UUID, ...]
        ) -> dict[str, object]:
            result = await original(context, revision, ids)
            result["synthetic_large_text"] = "x" * PRESENTATION_RESULT_LIMIT
            return result

        monkeypatch.setattr(executor.hotels, "present", oversized)
        result = await executor.execute(context, "present_travel_result", present_args(records))
        assert result.code == "blocked" and "result_too_long" in result.detail

    runner.run(exercise())


def test_only_the_presentation_tool_has_the_larger_result_limit() -> None:
    larger = {d.name for d in DEFINITIONS if d.max_result_chars != RESULT_LIMIT}
    assert larger == {"present_travel_result"}
    assert next(d for d in DEFINITIONS if d.name in larger).max_result_chars == (
        PRESENTATION_RESULT_LIMIT
    )
