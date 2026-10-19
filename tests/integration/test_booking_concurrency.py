"""R1：真PG上真并发的hold——住宿段重叠串行化、同报价幂等、相邻段互不阻塞；每个场景重复多轮冲刷竞态。"""

import asyncio
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import URL, func, select

from backend.domain.booking import Booking, HoldHotelInput
from backend.domain.execution import RunContext
from backend.domain.hotels import HotelOffer
from backend.domain.travel_request import RequestPatch
from backend.persistence import bookings
from backend.persistence.models import SupplierHoldRow, SupplierOrderRow
from backend.services.bookings import BookingService
from backend.services.common import ServiceError
from backend.services.hotels import HotelService
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from mock_supplier.service import SupplierService

pytestmark = pytest.mark.integration

ROUNDS = 25
BASE = {
    "city": "京都",
    "adults": 2,
    "child_ages": [],
    "rooms": 1,
    "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
    "start_date": "2026-11-03",
    "end_date": "2026-11-05",
}
SEGMENTS = [
    {"city": "京都", "arrive": "2026-11-03", "depart": "2026-11-05"},
    {"city": "京都", "arrive": "2026-11-05", "depart": "2026-11-07"},
]


class World:
    def __init__(self, runner: asyncio.Runner, sessions: SessionService) -> None:
        self.runner, self.sessions = runner, sessions
        self.travel = TravelService(sessions.database)
        self.user_id = runner.run(sessions.create_demo_user(DemoLogin())).user_id

    async def session(self, extra: dict[str, object] | None = None) -> RunContext:
        session = await self.sessions.new_session(self.user_id)
        context = RunContext(self.user_id, session.session_id)
        await self.travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 0, "set": {**BASE, **(extra or {})}}),
        )
        return context

    def service(self) -> BookingService:
        # 每个并发调用独立的服务实例，等价于多个进程/请求。
        return BookingService(self.travel, SupplierService(self.travel.database))

    async def offers(
        self, context: RunContext, arrive: date | None = None, limit: int = 6
    ) -> tuple[tuple[HotelOffer, ...], int]:
        request = await self.travel.get_request(context)
        records = await HotelService(self.travel).search(
            context, request.revision, limit=limit, segment_arrive=arrive
        )
        found = [HotelOffer.model_validate(r.value) for r in records]
        return tuple(o for o in found if o.total is not None), request.revision

    async def counts(self, context: RunContext) -> tuple[list[Booking], int, int]:
        """(本会话预订, 这些预订对应的供应商hold数, 供应商订单数)。"""
        async with self.travel.database.sessions.begin() as db:
            rows = await bookings.for_session(db, context.user_id, context.session_id)
            items = [Booking.model_validate(row.payload) for row in rows]
            refs = [item.client_ref for item in items]
            holds = await db.scalar(
                select(func.count())
                .select_from(SupplierHoldRow)
                .where(SupplierHoldRow.client_ref.in_(refs))
            )
            orders = await db.scalar(
                select(func.count())
                .select_from(SupplierOrderRow)
                .where(SupplierOrderRow.client_ref.in_(refs))
            )
        return items, int(holds or 0), int(orders or 0)


@pytest.fixture
def world(postgres_url: URL) -> Iterator[World]:
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        sessions = SessionService(postgres_url, demo_enabled=True)
        try:
            yield World(runner, sessions)
        finally:
            runner.run(sessions.close())


def body(offer: HotelOffer, revision: int) -> HoldHotelInput:
    return HoldHotelInput(offer_id=offer.offer_id, expected_revision=revision)


def test_overlapping_holds_of_different_hotels_have_exactly_one_winner(world: World) -> None:
    """不同酒店、同日期：2~3路无人为延迟的并发，恰一个held，其余409。"""

    async def exercise() -> None:
        for round_ in range(ROUNDS):
            context = await world.session()
            offers, revision = await world.offers(context)
            distinct = list({o.hotel_id: o for o in offers}.values())
            assert len(distinct) >= 3
            picked = distinct[: 2 + round_ % 2]
            results = await asyncio.gather(
                *(world.service().hold(context, body(o, revision)) for o in picked),
                return_exceptions=True,
            )
            held = [r for r in results if isinstance(r, Booking) and r.status == "held"]
            errors = [r for r in results if isinstance(r, ServiceError)]
            assert len(held) == 1 and len(errors) == len(picked) - 1, (round_, results)
            assert all(e.status == 409 for e in errors), (round_, errors)
            items, holds, orders = await world.counts(context)
            assert sorted(i.status for i in items) == ["failed"] * (len(picked) - 1) + ["held"]
            # 文档化遗留：输家的供应商hold不释放，所以hold数==进过供应商的预订数，不多不少。
            assert holds == len(picked) and orders == 0, (round_, holds, orders)
            assert len({i.booking_id for i in items}) == len(picked)

    world.runner.run(exercise())


def test_same_offer_held_concurrently_is_one_booking_one_supplier_hold(world: World) -> None:
    """同一报价多路并发：只有一行booking、一个供应商hold、无订单。"""

    async def exercise() -> None:
        for round_ in range(ROUNDS):
            context = await world.session()
            offers, revision = await world.offers(context)
            results = await asyncio.gather(
                *(world.service().hold(context, body(offers[0], revision)) for _ in range(4)),
                return_exceptions=True,
            )
            winners = {r.booking_id for r in results if isinstance(r, Booking)}
            assert len(winners) == 1, (round_, results)
            for r in results:
                assert isinstance(r, Booking) or (
                    isinstance(r, ServiceError) and r.status in {409, 503}
                ), (round_, r)
            items, holds, orders = await world.counts(context)
            assert len(items) == 1 and holds == 1 and orders == 0, (round_, items, holds, orders)
            assert items[0].status == "held"

    world.runner.run(exercise())


def test_adjacent_stays_held_concurrently_both_succeed(world: World) -> None:
    """同城相邻两段（退房日=下一段入住日）并发hold，[入住,退房)半开，两个都必须成功。"""

    async def exercise() -> None:
        for _ in range(ROUNDS):
            context = await world.session({"end_date": "2026-11-07", "segments": SEGMENTS})
            first, revision = await world.offers(context, date(2026, 11, 3), 3)
            second, _ = await world.offers(context, date(2026, 11, 5), 3)
            picked = [first[0], second[0]]
            assert picked[0].request.end_date == picked[1].request.start_date
            results = await asyncio.gather(
                *(world.service().hold(context, body(o, revision)) for o in picked),
                return_exceptions=True,
            )
            assert all(isinstance(r, Booking) and r.status == "held" for r in results), results
            items, holds, orders = await world.counts(context)
            assert sorted(i.status for i in items) == ["held", "held"]
            assert holds == 2 and orders == 0

    world.runner.run(exercise())


def test_overlap_racing_an_adjacent_hold_only_blocks_the_overlap(world: World) -> None:
    """三路并发：段A两家酒店重叠 + 相邻段B一家 -> A恰一个赢，B必赢。"""

    async def exercise() -> None:
        for _ in range(ROUNDS):
            context = await world.session({"end_date": "2026-11-07", "segments": SEGMENTS})
            first, revision = await world.offers(context, date(2026, 11, 3), 6)
            second, _ = await world.offers(context, date(2026, 11, 5), 3)
            a = list({o.hotel_id: o for o in first}.values())[:2]
            picked = [a[0], second[0], a[1]]
            results = await asyncio.gather(
                *(world.service().hold(context, body(o, revision)) for o in picked),
                return_exceptions=True,
            )
            assert isinstance(results[1], Booking) and results[1].status == "held", results
            a_held = [r for r in (results[0], results[2]) if isinstance(r, Booking)]
            a_err = [r for r in (results[0], results[2]) if isinstance(r, ServiceError)]
            assert len(a_held) == 1 and len(a_err) == 1 and a_err[0].status == 409, results
            items, holds, orders = await world.counts(context)
            assert sorted(i.status for i in items) == ["failed", "held", "held"]
            assert holds == 3 and orders == 0

    world.runner.run(exercise())
