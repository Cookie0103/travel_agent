"""模拟供应商事务；同client_ref锁内下单，重启仍返回第一次订单。"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from backend.domain.booking import HoldInput, OrderInput, OrderLookup, SupplierHold, SupplierOrder
from backend.domain.hotels import quote
from backend.persistence.database import Database
from backend.persistence.models import SupplierHoldRow, SupplierOrderRow
from backend.providers.hotel_fixture import load_rates
from backend.services.common import ServiceError, transaction


class SupplierService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def hold(self, body: HoldInput) -> SupplierHold:
        now = datetime.now(UTC)
        async with transaction(self.database) as db:
            existing = await db.get(SupplierHoldRow, body.client_ref)
            if existing:
                result = SupplierHold.model_validate(existing.payload)
                if result.offer != body.offer:
                    raise ServiceError(409, "conflict", "client_ref已用于另一个报价")
                return result
            self.validate_offer(body, now)
            result = SupplierHold(
                **body.model_dump(), hold_id=uuid4(), expires_at=now + timedelta(minutes=15)
            )
            await db.execute(
                insert(SupplierHoldRow)
                .values(
                    client_ref=body.client_ref,
                    id=result.hold_id,
                    payload=result.model_dump(mode="json"),
                    expires_at=result.expires_at,
                )
                .on_conflict_do_nothing(index_elements=[SupplierHoldRow.client_ref])
            )
            stored = await db.get(SupplierHoldRow, body.client_ref)
            assert stored is not None
            result = SupplierHold.model_validate(stored.payload)
            if result.offer != body.offer:
                raise ServiceError(409, "conflict", "client_ref已用于另一个报价")
            return result

    @staticmethod
    def validate_offer(body: HoldInput, now: datetime) -> None:
        offer = body.offer
        if offer.total is None or not offer.quoted_at <= now < offer.expires_at:
            raise ServiceError(409, "conflict", "需要完整且有效的报价")
        try:
            rates, _ = load_rates()
        except (OSError, ValueError):
            raise ServiceError(503, "unavailable", "模拟酒店目录暂不可用") from None
        rate = next((rate for rate in rates if rate.rate_id == offer.rate_id), None)
        expected = quote(rate, offer.request, offer.quoted_at) if rate else None
        fields = {"offer_id"}
        if expected is None or expected.model_dump(exclude=fields) != offer.model_dump(
            exclude=fields
        ):
            raise ServiceError(409, "conflict", "报价与模拟供应商目录不符")

    async def order(self, body: OrderInput) -> SupplierOrder:
        async with transaction(self.database) as db:
            hold = await db.scalar(
                select(SupplierHoldRow)
                .where(
                    SupplierHoldRow.client_ref == body.client_ref,
                )
                .with_for_update()
            )
            if hold is None or hold.id != body.hold_id:
                raise ServiceError(404, "blocked", "hold不存在或不属于此client_ref")
            existing = await db.get(SupplierOrderRow, body.client_ref)
            if existing:
                return SupplierOrder.model_validate(existing.payload)
            if hold.expires_at <= datetime.now(UTC):
                raise ServiceError(409, "conflict", "hold已过期释放，请重新报价")
            result = SupplierOrder(
                **body.model_dump(), order_id=uuid4(), created_at=datetime.now(UTC)
            )
            db.add(
                SupplierOrderRow(
                    client_ref=body.client_ref,
                    id=result.order_id,
                    payload=result.model_dump(mode="json"),
                )
            )
            return result

    async def lookup(self, client_ref: UUID) -> OrderLookup:
        async with transaction(self.database) as db:
            hold = await db.scalar(
                select(SupplierHoldRow)
                .where(
                    SupplierHoldRow.client_ref == client_ref,
                )
                .with_for_update()
            )
            existing = await db.get(SupplierOrderRow, client_ref)
            return OrderLookup(
                order=SupplierOrder.model_validate(existing.payload) if existing else None,
                absence_final=bool(hold and not existing and hold.expires_at <= datetime.now(UTC)),
            )
