"""R09–R11/R16：预订完整性——确认后崩溃补发、重复住宿拒绝、状态/排序边界。"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from backend.adapters.supplier import SupplierError
from backend.domain.booking import (
    Booking,
    HoldHotelInput,
    HoldInput,
    OrderInput,
    SupplierHold,
    SupplierOrder,
    transition,
)
from backend.domain.execution import RunContext
from backend.domain.hotels import HotelOffer, quote
from backend.domain.travel_request import RequestPatch, TravelRequest
from backend.persistence import bookings
from backend.persistence.database import Database
from backend.persistence.models import BookingRow, SupplierHoldRow, SupplierOrderRow
from backend.providers.hotel_fixture import load_rates
from backend.services.bookings import BookingService
from backend.services.common import ServiceError
from backend.services.hotels import HotelService
from backend.services.travel import TravelService
from mock_supplier.service import SupplierService
from tests.integration.test_bookings import select_offer
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration

Setup = tuple[asyncio.Runner, TravelService, RunContext]


class CrashBeforeOrder(BookingService):
    """模拟 confirmed 已提交、进程在向供应商发 order 前崩溃。"""

    async def _order(self, user_id: UUID, current: Booking) -> Booking:
        raise RuntimeError("process crash")


class CountingOrders(SupplierService):
    def __init__(self, database: Database, delay: float = 0) -> None:
        super().__init__(database)
        self.order_calls, self.delay = 0, delay

    async def order(self, body: OrderInput) -> SupplierOrder:
        self.order_calls += 1
        await asyncio.sleep(self.delay)
        return await super().order(body)


class AmbiguousOrders(CountingOrders):
    async def order(self, body: OrderInput) -> SupplierOrder:
        self.order_calls += 1
        raise SupplierError("timeout", ambiguous=True)


async def order_count(travel: TravelService, client_ref: UUID) -> int:
    async with travel.database.sessions.begin() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(SupplierOrderRow)
                .where(SupplierOrderRow.client_ref == client_ref)
            )
            or 0
        )


async def crash_after_confirm(
    travel: TravelService, context: RunContext, supplier: SupplierService
) -> tuple[BookingService, Booking]:
    crashing = CrashBeforeOrder(travel, supplier)
    held = await crashing.hold(context, await select_offer(travel, context))
    with pytest.raises(RuntimeError):
        await crashing.confirm(context.user_id, held.booking_id)
    service = BookingService(travel, supplier)
    assert (await service.get(context.user_id, held.booking_id)).status == "confirmed"
    return service, held


def test_confirmed_crash_before_order_is_reissued_while_hold_is_valid(travel_setup: Setup) -> None:
    """B1：用户已确认、hold 有效、供应商无订单 -> 同 client_ref 补发，恰好一张订单。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        supplier = CountingOrders(travel.database)
        service, held = await crash_after_confirm(travel, context, supplier)
        assert supplier.order_calls == 0
        result = await service.confirm(context.user_id, held.booking_id)
        assert result.status == "booked" and result.order_id
        assert await order_count(travel, held.client_ref) == 1
        assert await service.confirm(context.user_id, held.booking_id) == result
        assert supplier.order_calls == 1

    runner.run(exercise())


def test_confirmed_crash_with_expired_hold_fails_without_ordering(travel_setup: Setup) -> None:
    """B1 边界：hold 已过期 -> failed，且不向供应商发 order。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        supplier = CountingOrders(travel.database)
        service, held = await crash_after_confirm(travel, context, supplier)
        past = datetime.now(UTC) - timedelta(seconds=1)
        async with travel.database.sessions.begin() as db:
            await db.execute(
                update(SupplierHoldRow)
                .where(SupplierHoldRow.client_ref == held.client_ref)
                .values(expires_at=past)
            )
            row = await db.get(BookingRow, held.booking_id)
            assert row is not None
            stored = Booking.model_validate(row.payload)
            row.payload = stored.model_copy(update={"expires_at": past}).model_dump(mode="json")
        assert (await service.confirm(context.user_id, held.booking_id)).status == "failed"
        assert supplier.order_calls == 0 and await order_count(travel, held.client_ref) == 0

    runner.run(exercise())


def test_unknown_is_reconciled_by_lookup_and_never_blindly_reordered(travel_setup: Setup) -> None:
    """B1 边界：unknown 仍只对账；hold 有效且无订单时保持 unknown，不再发 order。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        supplier = AmbiguousOrders(travel.database)
        service = BookingService(travel, supplier)
        held = await service.hold(context, await select_offer(travel, context))
        assert (await service.confirm(context.user_id, held.booking_id)).status == "unknown"
        for _ in range(2):
            assert (await service.confirm(context.user_id, held.booking_id)).status == "unknown"
        assert supplier.order_calls == 1

    runner.run(exercise())


def test_concurrent_confirm_never_exposes_unknown_while_order_is_in_flight(
    travel_setup: Setup,
) -> None:
    """B4：带延迟的 order + 并发 confirm，每个调用都看到 booked，只有一张订单。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        supplier = CountingOrders(travel.database, delay=0.4)
        service = BookingService(travel, supplier)
        held = await service.hold(context, await select_offer(travel, context))
        results = await asyncio.gather(
            *(service.confirm(context.user_id, held.booking_id) for _ in range(3))
        )
        assert [item.status for item in results] == ["booked"] * 3
        assert len({item.order_id for item in results}) == 1
        assert await order_count(travel, held.client_ref) == 1

    runner.run(exercise())


@pytest.mark.parametrize("other_hotel", [False, True])
@pytest.mark.parametrize("state", ["held", "booked"])
def test_overlapping_stay_is_rejected_for_same_or_different_hotel(
    travel_setup: Setup, other_hotel: bool, state: str
) -> None:
    """B2：同会话已有 held/booked 预订时，同日期再暂留（新报价）-> 409，无第二个 hold/订单。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service = BookingService(travel, SupplierService(travel.database))
        request = await travel.read_request(context)
        search = HotelService(travel)
        first = HotelOffer.model_validate(
            (await search.search(context, request.revision, limit=1))[0].value
        )
        offers = [
            HotelOffer.model_validate(row.value)
            for row in await search.search(context, request.revision, limit=6)
        ]
        other = next(
            offer
            for offer in offers
            if offer.total is not None and (offer.hotel_id != first.hotel_id) == other_hotel
        )
        held = await service.hold(
            context, HoldHotelInput(offer_id=first.offer_id, expected_revision=request.revision)
        )
        if state == "booked":
            assert (await service.confirm(context.user_id, held.booking_id)).status == "booked"
        with pytest.raises(ServiceError) as caught:
            await service.hold(
                context,
                HoldHotelInput(offer_id=other.offer_id, expected_revision=request.revision),
            )
        assert caught.value.status == 409 and caught.value.code == "conflict"
        assert "重叠" in str(caught.value)
        # 同一报价重放仍返回同一预订。
        replay = await service.hold(
            context, HoldHotelInput(offer_id=first.offer_id, expected_revision=request.revision)
        )
        assert replay.booking_id == held.booking_id
        async with travel.database.sessions.begin() as db:
            rows = await bookings.for_session(db, context.user_id, context.session_id)
            assert [row.id for row in rows] == [held.booking_id]
            # 被拒绝的报价没有向供应商创建第二个hold。
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(SupplierHoldRow)
                    .where(
                        SupplierHoldRow.payload["offer"]["offer_id"].astext == str(other.offer_id)
                    )
                )
                == 0
            )

    runner.run(exercise())


def test_checkout_day_allows_next_stay_and_expired_hold_does_not_block(travel_setup: Setup) -> None:
    """B2 边界：[入住,退房) 半开；退房当天可订下一家；已过期暂留不占住宿段。"""
    runner, travel, context = travel_setup

    async def move(start: str, end: str) -> None:
        current = await travel.read_request(context)
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": current.revision,
                    "set": {"start_date": start, "end_date": end},
                }
            ),
        )

    async def exercise() -> None:
        service = BookingService(travel, SupplierService(travel.database))
        first = await service.hold(context, await select_offer(travel, context))
        await move("2026-11-05", "2026-11-07")
        adjacent = await service.hold(context, await select_offer(travel, context))
        assert adjacent.status == "held" and adjacent.booking_id != first.booking_id
        await move("2026-11-03", "2026-11-05")
        overlap = await select_offer(travel, context)
        with pytest.raises(ServiceError, match="重叠"):
            await service.hold(context, overlap)
        async with travel.database.sessions.begin() as db:
            row = await db.get(BookingRow, first.booking_id)
            assert row is not None
            row.payload = first.model_copy(
                update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            ).model_dump(mode="json")
        assert (await service.hold(context, overlap)).status == "held"

    runner.run(exercise())


def sample_booking() -> Booking:
    rates, _ = load_rates()
    request = TravelRequest.model_validate(
        {
            "city": "京都",
            "start_date": "2026-11-03",
            "end_date": "2026-11-05",
            "adults": 2,
            "child_ages": [],
            "rooms": 1,
            "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
        }
    )
    offer = next(o for r in rates if (o := quote(r, request, datetime.now(UTC))))
    return Booking.quoted(uuid4(), uuid4(), offer, "fixture:test", "v1")


def test_same_status_transition_keeps_new_error_code_without_new_history() -> None:
    """B3a：unknown->unknown 的新 error_code 不能被丢弃，也不重复写历史。"""
    held = transition(sample_booking(), "held", "h")
    booking = transition(transition(held, "confirmed", "c"), "unknown", "u", error_code="timeout")
    again = transition(booking, "unknown", "lookup_unavailable", error_code="unavailable")
    assert again.error_code == "unavailable"
    assert again.history == booking.history
    assert transition(again, "unknown", "x", error_code="unavailable") is again


def test_session_order_uses_real_time_not_timestamp_text(travel_setup: Setup) -> None:
    """B3e：微秒为 0 的时间戳序列化为 '...:00Z'，按字符串排会排在 '...:00.5Z' 之前。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        records = [(await HotelService(travel).search(context, 1, limit=1))[0] for _ in range(2)]
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        ids = []
        for record, moment in zip(records, (base, base + timedelta(milliseconds=500)), strict=True):
            assert record.source_ref
            quoted = Booking.quoted(
                context.session_id,
                record.evidence_id,
                HotelOffer.model_validate(record.value),
                record.source_ref,
                record.content_version,
            )
            quoted = quoted.model_copy(
                update={"history": (quoted.history[0].model_copy(update={"at": moment}),)}
            )
            ids.append(quoted.booking_id)
            async with travel.database.sessions.begin() as db:
                db.add(
                    BookingRow(
                        id=quoted.booking_id,
                        user_id=context.user_id,
                        session_id=context.session_id,
                        evidence_id=record.evidence_id,
                        payload=quoted.model_dump(mode="json"),
                    )
                )
        async with travel.database.sessions.begin() as db:
            rows = await bookings.for_session(db, context.user_id, context.session_id)
        assert [row.id for row in rows] == [ids[1], ids[0]]

    runner.run(exercise())


def test_business_context_omits_quote_past_its_validity(travel_setup: Setup) -> None:
    """B3b：未暂留的 quoted 预订超过报价有效期后不再注入模型上下文。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        record = (await HotelService(travel).search(context, 1, limit=1))[0]
        assert record.source_ref
        offer = HotelOffer.model_validate(record.value)
        fresh = Booking.quoted(
            context.session_id, record.evidence_id, offer, record.source_ref, "v1"
        )
        async with travel.database.sessions.begin() as db:
            db.add(
                BookingRow(
                    id=fresh.booking_id,
                    user_id=context.user_id,
                    session_id=context.session_id,
                    evidence_id=record.evidence_id,
                    payload=fresh.model_dump(mode="json"),
                )
            )

        async def listed() -> list[str]:
            rows = (await travel.business_context(context))["bookings"]
            assert isinstance(rows, list)
            return [str(row["booking_id"]) for row in rows]

        assert str(fresh.booking_id) in await listed()
        now = datetime.now(UTC)
        stale = offer.model_copy(
            update={
                "quoted_at": now - timedelta(minutes=10),
                "expires_at": now - timedelta(minutes=5),
            }
        )
        async with travel.database.sessions.begin() as db:
            row = await db.get(BookingRow, fresh.booking_id)
            assert row is not None
            row.payload = fresh.model_copy(update={"offer": stale}).model_dump(mode="json")
        assert str(fresh.booking_id) not in await listed()

    runner.run(exercise())


class SlowHold(SupplierService):
    async def hold(self, body: HoldInput) -> SupplierHold:
        await asyncio.sleep(0.4)
        return await super().hold(body)


def test_concurrent_overlapping_holds_leave_exactly_one_held(travel_setup: Setup) -> None:
    """R1：两个并发 hold（不同酒店、同日期）恰一个 held，另一个 409，库里无第二个 held。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        request = await travel.read_request(context)
        offers = [
            HotelOffer.model_validate(row.value)
            for row in await HotelService(travel).search(context, request.revision, limit=6)
        ]
        offers = [offer for offer in offers if offer.total is not None]
        first = offers[0]
        second = next(offer for offer in offers if offer.hotel_id != first.hotel_id)
        results = await asyncio.gather(
            *(
                BookingService(travel, SlowHold(travel.database)).hold(
                    context, HoldHotelInput(offer_id=o.offer_id, expected_revision=request.revision)
                )
                for o in (first, second)
            ),
            return_exceptions=True,
        )
        held = [r for r in results if isinstance(r, Booking) and r.status == "held"]
        errors = [r for r in results if isinstance(r, ServiceError)]
        assert len(held) == 1 and len(errors) == 1, results
        assert errors[0].status == 409 and "重叠" in str(errors[0])
        async with travel.database.sessions.begin() as db:
            rows = await bookings.for_session(db, context.user_id, context.session_id)
            statuses = sorted(Booking.model_validate(row.payload).status for row in rows)
        assert statuses == ["failed", "held"]
        # 赢家的同一报价重放仍是同一预订。
        winner = held[0]
        replay = await BookingService(travel, SupplierService(travel.database)).hold(
            context,
            HoldHotelInput(offer_id=winner.offer.offer_id, expected_revision=request.revision),
        )
        assert replay.booking_id == winner.booking_id

    runner.run(exercise())


def test_concurrent_confirm_of_reissued_order_makes_one_supplier_order(
    travel_setup: Setup,
) -> None:
    """R1(4)：confirmed 崩溃后并发 confirm 都补发 order，供应商按 client_ref 幂等只一张订单。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        supplier = CountingOrders(travel.database, delay=0.3)
        service, held = await crash_after_confirm(travel, context, supplier)
        results = await asyncio.gather(
            *(service.confirm(context.user_id, held.booking_id) for _ in range(3))
        )
        assert [item.status for item in results] == ["booked"] * 3
        assert len({item.order_id for item in results}) == 1
        assert await order_count(travel, held.client_ref) == 1
        assert (await service.get(context.user_id, held.booking_id)).status == "booked"

    runner.run(exercise())
