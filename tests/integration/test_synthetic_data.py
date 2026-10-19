"""F3真实PG：假供应商经过实际适配器仍明确synthetic，价格计算不退化。"""

import asyncio
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import URL, func, select

from backend.domain.booking import HoldHotelInput
from backend.persistence.models import BookingRow
from backend.persistence.temporary import temporary_database
from backend.services.bookings import BookingService
from backend.services.common import ServiceError
from backend.tools.travel import TravelToolExecutor
from eval.cases import Case
from eval.database import database_evaluation

pytestmark = pytest.mark.integration


def test_eval_hotel_result_and_evidence_are_synthetic_without_losing_verified_total(
    postgres_url: URL,
) -> None:
    async def exercise(url: URL) -> None:
        async with database_evaluation(url) as business:
            case = Case(
                case_id="source-marker",
                source="synthetic source control",
                adaptation="not real travel data",
                input="比较酒店",
                allowed_tools=["search_hotel_offers"],
                required_tools=["search_hotel_offers"],
                should_have_results=True,
                external_fault="coverage",
                initial_state={
                    "request": {
                        "city": "京都",
                        "start_date": "2026-11-03",
                        "end_date": "2026-11-04",
                        "adults": 2,
                        "child_ages": [],
                        "rooms": 1,
                        "currency": "JPY",
                        "lodging_budget": {
                            "amount": {"upper": "10000"},
                            "basis": "per_room_night",
                            "currency": "JPY",
                        },
                        "hard_constraints": ["住宿：独立房间", "房型：禁烟", "床型：无要求"],
                    }
                },
            )
            context = await business.prepare(case)
            revision = (await business.travel.get_request(context)).revision
            result = await TravelToolExecutor(business.travel).execute(
                context, "search_hotel_offers", {"expected_revision": revision}
            )
            assert result.code is None and result.data_mode == "synthetic"
            assert result.payload()["source_label"] == "合成评测数据"
            assert all("实时查询" not in warning for warning in result.warnings)
            assert result.data["offers"]
            offers = result.data["offers"]
            assert isinstance(offers, list)
            for offer in offers:
                assert isinstance(offer, dict)
                assert offer["data_mode"] == "synthetic" and Decimal(
                    str(offer["total"])
                ) <= Decimal(10000)
            records = await business.travel.resolve_evidence(
                context, tuple(UUID(s) for s in result.evidence_ids)
            )
            assert all(r.data_mode == "synthetic" for r in records)
            with patch(
                "backend.services.bookings.SupplierClient.hold",
                side_effect=AssertionError("不应调用供应商"),
            ) as supplier:
                with pytest.raises(ServiceError) as blocked:
                    await BookingService(business.travel).hold(
                        context,
                        HoldHotelInput(
                            expected_revision=revision, offer_id=UUID(str(offers[0]["offer_id"]))
                        ),
                    )
                assert blocked.value.status == 403
                supplier.assert_not_called()
            async with business.travel.database.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(BookingRow)) == 0

    with (
        temporary_database(postgres_url, "eval") as url,
        asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner,
    ):
        runner.run(exercise(url))
