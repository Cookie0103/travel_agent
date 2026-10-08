"""预订用例：持久hold、独立用户确认、有界429重试和不明结果对账。"""

import asyncio
import math
import time
from datetime import UTC, datetime
from uuid import UUID

from backend.adapters.supplier import SupplierClient, SupplierError, SupplierGateway
from backend.domain.booking import (
    TRANSITIONS,
    Booking,
    BookingStatus,
    HoldHotelInput,
    HoldInput,
    OrderInput,
    transition,
)
from backend.domain.execution import RunContext
from backend.domain.hotels import HotelOffer
from backend.persistence import bookings, travel
from backend.persistence.models import BookingRow
from backend.services.common import ServiceError, transaction
from backend.services.hotels import HotelService
from backend.services.travel import (
    TravelService,
    request_from_row,
    require_revision,
    resolve_records,
)

__all__ = ["Booking", "HoldHotelInput", "BookingService"]


def value(row: BookingRow | None) -> Booking:
    if row is None:
        raise ServiceError(404, "blocked", "预订不存在")
    return Booking.model_validate(row.payload)


class BookingService:
    def __init__(
        self, travel_service: TravelService, supplier: SupplierGateway | None = None
    ) -> None:
        self.travel = travel_service
        self.supplier = supplier or SupplierClient()

    async def hold(self, context: RunContext, body: HoldHotelInput) -> Booking:
        known = (await HotelService(self.travel).known_quotes(context, (body.offer_id,)))[0]
        if known.data_mode == "live":
            raise ServiceError(422, "blocked", "实时酒店只能前往乐天查看，不提供模拟暂留")
        async with transaction(self.travel.database) as db:
            request = request_from_row(await travel.owned_request(db, context))
            require_revision(request, body.expected_revision)
            previous = await bookings.for_quote(db, context.session_id, known.evidence_id)
            if previous:
                result = value(previous)
                require_revision(request, result.offer.request.revision)
                if result.hold_expired(datetime.now(UTC)):
                    result = transition(result, "expired", "hold_expired")
                    previous.payload = result.model_dump(mode="json")
                if result.status != "quoted":
                    return result
            else:
                record = (
                    await resolve_records(
                        db, context, request, (known.evidence_id,), datetime.now(UTC)
                    )
                )[0]
                offer = HotelOffer.model_validate(record.value)
                if offer.total is None:
                    raise ServiceError(422, "validation", "税费缺失，不能暂留或确认预订")
                if not record.source_ref or not record.content_version:
                    raise ServiceError(422, "validation", "报价来源不完整，不能暂留预订")
                result = Booking.quoted(
                    context.session_id,
                    record.evidence_id,
                    offer,
                    record.source_ref,
                    record.content_version,
                )
                db.add(
                    BookingRow(
                        id=result.booking_id,
                        user_id=context.user_id,
                        session_id=context.session_id,
                        evidence_id=result.evidence_id,
                        payload=result.model_dump(mode="json"),
                    )
                )
        try:
            held = await self.supplier.hold(
                HoldInput(client_ref=result.client_ref, offer=result.offer)
            )
        except SupplierError as error:
            if error.ambiguous:
                # 同稳定client_ref可以恢复hold；尚未用户确认，不可能下单。
                raise ServiceError(
                    503, error.code, "暂留结果未确定，请读取后按同一报价重试"
                ) from None
            return await self._update(
                context.user_id, result.booking_id, "failed", "hold_rejected", error_code=error.code
            )
        return await self._update(
            context.user_id,
            result.booking_id,
            "held",
            "hold_created",
            hold_id=held.hold_id,
            expires_at=held.expires_at,
        )

    async def get(self, user_id: UUID, booking_id: UUID) -> Booking:
        async with transaction(self.travel.database) as db:
            result = value(await bookings.owned(db, user_id, booking_id))
        if result.hold_expired(datetime.now(UTC)):
            return await self._update(user_id, booking_id, "expired", "hold_expired")
        return result

    async def list(self, context: RunContext) -> tuple[Booking, ...]:
        await self.travel.get_request(context)
        async with transaction(self.travel.database) as db:
            ids = [
                row.id
                for row in await bookings.for_session(db, context.user_id, context.session_id)
            ]
        return tuple([await self.get(context.user_id, identity) for identity in ids])

    async def _update(
        self, user_id: UUID, booking_id: UUID, status: BookingStatus, reason: str, **changes: object
    ) -> Booking:
        async with transaction(self.travel.database) as db:
            row = await bookings.owned(db, user_id, booking_id)
            current = value(row)
            context = RunContext(user_id, current.session_id)
            request = request_from_row(await travel.owned_request(db, context))
            assert row is not None
            await db.refresh(row)
            current = value(row)
            if current.status in {"booked", "failed", "expired"}:
                return current
            if status != current.status and status not in TRANSITIONS[current.status]:
                # 另一确认/到期裁决已经推进状态，迟到的hold或GET不能回退。
                return current
            if status == "held" and current.status != "quoted":
                return current
            if status == "held" and current.offer.request.revision != request.revision:
                status, reason = "expired", "conditions_changed_during_hold"
            updated = transition(current, status, reason, **changes)
            row.payload = updated.model_dump(mode="json")
            return updated

    async def confirm(self, user_id: UUID, booking_id: UUID) -> Booking:
        async with transaction(self.travel.database) as db:
            row = await bookings.owned(db, user_id, booking_id)
            current = value(row)
            request = request_from_row(
                await travel.owned_request(db, RunContext(user_id, current.session_id))
            )
            assert row is not None
            await db.refresh(row)
            current = value(row)
            if current.status in {"booked", "failed", "expired"}:
                return current
            reconciling = current.status in {"confirmed", "unknown"}
            if not reconciling:
                if current.status != "held":
                    raise ServiceError(409, "conflict", "请先完成酒店暂留")
                if current.hold_expired(datetime.now(UTC)):
                    updated = transition(current, "expired", "hold_expired")
                    row.payload = updated.model_dump(mode="json")
                    return updated
                require_revision(request, current.offer.request.revision)
                current = transition(current, "confirmed", "user_confirmed")
                row.payload = current.model_dump(mode="json")
        if reconciling:
            return await self.reconcile(user_id, booking_id)
        return await self._order(user_id, current)

    async def _order(self, user_id: UUID, current: Booking) -> Booking:
        assert current.hold_id is not None
        deadline = time.monotonic() + 5
        for attempt in range(3):
            try:
                async with asyncio.timeout(max(0, deadline - time.monotonic())):
                    order = await self.supplier.order(
                        OrderInput(client_ref=current.client_ref, hold_id=current.hold_id)
                    )
                return await self._update(
                    user_id,
                    current.booking_id,
                    "booked",
                    "supplier_booked",
                    order_id=order.order_id,
                    error_code=None,
                )
            except TimeoutError:
                return await self._update(
                    user_id, current.booking_id, "unknown", "order_deadline", error_code="timeout"
                )
            except SupplierError as error:
                wait = error.retry_after if error.retry_after is not None else 1
                if (
                    error.code == "rate_limited"
                    and attempt < 2
                    and math.isfinite(wait)
                    and 0 <= wait <= 2
                    and time.monotonic() + wait < deadline
                ):
                    await asyncio.sleep(wait)
                    continue
                return await self._update(
                    user_id,
                    current.booking_id,
                    "unknown" if error.ambiguous else "failed",
                    "order_response_unknown" if error.ambiguous else "order_rejected",
                    error_code=error.code,
                )
        raise AssertionError("bounded order loop must return")

    async def reconcile(self, user_id: UUID, booking_id: UUID) -> Booking:
        current = await self.get(user_id, booking_id)
        if current.status not in {"confirmed", "unknown"}:
            return current
        try:
            result = await self.supplier.lookup(current.client_ref)
        except SupplierError as error:
            return await self._update(
                user_id, booking_id, "unknown", "lookup_unavailable", error_code=error.code
            )
        if result.order:
            if result.order.hold_id != current.hold_id:
                return await self._update(
                    user_id, booking_id, "unknown", "lookup_mismatch", error_code="provider_error"
                )
            return await self._update(
                user_id,
                booking_id,
                "booked",
                "reconciled_order",
                order_id=result.order.order_id,
                error_code=None,
            )
        return await self._update(
            user_id,
            booking_id,
            "failed" if result.absence_final else "unknown",
            "reconciled_absence" if result.absence_final else "order_still_uncertain",
        )
