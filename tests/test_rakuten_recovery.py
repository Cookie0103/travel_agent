"""合成上游：两次首晚发现，后续每晚独立核价，预算档位不增加HTTP。"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend.adapters.rakuten import Candidate, Rakuten, candidates
from backend.domain.external_data import GeoPoint
from backend.domain.hotel_recovery import HotelSearchDiagnostics
from backend.domain.travel_request import TravelRequest
from tests.test_external_data import sample
from tests.test_hotel_recovery import budget_request


class Usage:
    default_profile = True
    run_limits = True
    run_caps = {"rakuten": 8}
    used: dict[str, int] = {}


class SyntheticRakuten(Rakuten):
    def __init__(self, amounts: tuple[int, int]) -> None:
        self.usage = Usage()  # type: ignore[assignment]
        self.amounts = amounts
        self.calls: list[tuple[date, str]] = []
        self.sorted_started = False
        self.competitors = False

    async def query(
        self,
        request: TravelRequest,
        day: date,
        point: GeoPoint,
        hotel_ids: tuple[int, ...] = (),
        *,
        by_plan: bool = False,
        sort: str = "standard",
    ) -> tuple[tuple[Candidate, ...], int | None]:
        self.calls.append((day, sort))
        candidate = candidates(sample())[0]
        assert candidate.charge
        self.sorted_started |= sort == "+roomCharge"
        assert request.start_date
        amount = self.amounts[self.sorted_started] + (day - request.start_date).days * 500
        candidate = candidate.model_copy(
            update={
                "charge": candidate.charge.model_copy(
                    update={"stayDate": day, "chargeFlag": 1, "rakutenCharge": Decimal(amount)}
                )
            }
        )
        if self.competitors:
            assert candidate.charge
            candidate = candidate.model_copy(
                update={
                    "charge": candidate.charge.model_copy(
                        update={
                            "rakutenCharge": Decimal(5000 if day == request.start_date else 50000)
                        }
                    )
                }
            )
            assert candidate.charge
            other = candidate.model_copy(
                update={
                    "hotel": candidate.hotel.model_copy(update={"hotelNo": 2}),
                    "charge": candidate.charge.model_copy(update={"rakutenCharge": Decimal(9000)}),
                }
            )
            return (candidate, other), 2
        return (candidate,), 30


@pytest.mark.parametrize(
    "sorted_amount,cause,tier", [(8000, "coverage", None), (12000, "budget", "1.5")]
)
def test_two_first_night_searches_and_real_nightly_verification(
    sorted_amount: int, cause: str, tier: str | None
) -> None:
    async def exercise() -> None:
        provider = SyntheticRakuten((50000, sorted_amount))
        initial = budget_request()
        assert initial.start_date
        request = initial.model_copy(
            update={"budget": None, "end_date": initial.start_date + timedelta(days=2)}
        )
        diagnosis = HotelSearchDiagnostics()
        offers = await provider.search_diagnosed(
            request,
            GeoPoint(name="京都", latitude=35, longitude=135),
            diagnosis=diagnosis,
            rescue_segments=1,
        )
        assert request.start_date
        assert len([day for day, _ in provider.calls if day == request.start_date]) == 2
        assert len(provider.calls) == 4
        assert provider.usage.run_caps["rakuten"] == 4
        assert diagnosis.cause == cause
        assert diagnosis.tier == (Decimal(tier) if tier else None)
        # 次晚实际加500，绝不首晚价格乘晚数。
        assert offers[0].total == Decimal((sorted_amount * 2 + 500) * 2)

    asyncio.run(exercise())


def test_complete_budget_filter_precedes_limit_when_nightly_prices_differ() -> None:
    async def exercise() -> None:
        provider = SyntheticRakuten((5000, 5000))
        provider.competitors = True
        request = budget_request().model_copy(update={"budget": None})
        diagnosis = HotelSearchDiagnostics()
        offers = await provider.search_diagnosed(
            request,
            GeoPoint(name="京都", latitude=35, longitude=135),
            diagnosis=diagnosis,
            limit=1,
            rescue_segments=1,
        )
        assert len(offers) == 1 and offers[0].hotel_id == "2"
        assert offers[0].total == Decimal(54000)
        assert diagnosis.tier is None and diagnosis.in_budget == 1
        assert len(provider.calls) == 3

    asyncio.run(exercise())
