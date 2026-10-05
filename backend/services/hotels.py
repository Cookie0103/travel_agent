"""酒店查询/刷新/补卡用例；不可变报价保存在已有Evidence，避免重复事实表。"""

from datetime import UTC, datetime
from uuid import UUID

from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext
from backend.domain.external_data import ExternalDataError
from backend.domain.hotels import HotelOffer, compare, quote
from backend.domain.travel_request import TravelRequest
from backend.persistence.travel import entity_evidence
from backend.providers.hotel_fixture import load_rates
from backend.services.common import ServiceError, transaction
from backend.services.travel import TravelService, require_revision


class HotelService:
    def __init__(self, travel: TravelService) -> None:
        self.travel = travel

    async def _request(self, context: RunContext, revision: int) -> TravelRequest:
        request = await self.travel.get_request(context)
        require_revision(request, revision)
        if missing := request.hotel_requirements():
            raise ServiceError(
                422, "validation", "missing_fields: " + ", ".join(missing), "hotel_missing_fields"
            )
        return request

    async def search(
        self,
        context: RunContext,
        revision: int,
        hotel_id: str | None = None,
        limit: int = 4,
    ) -> tuple[EvidenceRecord, ...]:
        request = await self._request(context, revision)
        return await self._quote(context, request, hotel_id=hotel_id, limit=limit)

    async def refresh(
        self, context: RunContext, revision: int, offer_id: UUID
    ) -> tuple[EvidenceRecord, ...]:
        # 只允许刷新本人查到过的实体；旧证据仅定位rate，不沿用旧价格/入住条件。
        old = (await self.known_quotes(context, (offer_id,)))[0]
        offer = HotelOffer.model_validate(old.value)
        request = await self._request(context, revision)
        return await self._quote(context, request, rate_id=offer.rate_id, limit=1)

    async def _quote(
        self,
        context: RunContext,
        request: TravelRequest,
        *,
        hotel_id: str | None = None,
        rate_id: str | None = None,
        limit: int,
    ) -> tuple[EvidenceRecord, ...]:
        if live := self.travel.live:
            if not live.google or not live.rakuten:
                raise ServiceError(
                    503,
                    "unavailable",
                    "乐天酒店查询暂不可用：数据API配置缺失",
                    "hotel_api_unconfigured",
                )
            assert request.city
            try:
                point = await live.google.geocode(request.city)
                offers = await live.rakuten.search(
                    request, point, hotel_id=hotel_id, rate_id=rate_id, limit=limit
                )
            except ExternalDataError as error:
                raise ServiceError(
                    422 if error.validation else 503,
                    "validation" if error.validation else "unavailable",
                    "乐天酒店查询暂不可用：" + str(error),
                    "hotel_external_validation"
                    if error.validation
                    else "hotel_external_unavailable",
                ) from None
            records = [
                EvidenceRecord(
                    entity_id=str(offer.offer_id),
                    field_path="hotel_offer",
                    value=offer.model_dump(mode="json"),
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
            if records:
                await self.travel.record_evidence(context, records)
            return tuple(records)
        try:
            rates, version = load_rates()
        except (OSError, ValueError):
            raise ServiceError(503, "unavailable", "模拟酒店目录暂不可用") from None
        records = []
        for rate in rates:
            if (hotel_id and rate.hotel_id != hotel_id) or (rate_id and rate.rate_id != rate_id):
                continue
            offer = quote(rate, request, datetime.now(UTC))
            if offer is None:
                continue
            records.append(
                EvidenceRecord(
                    entity_id=str(offer.offer_id),
                    field_path="hotel_offer",
                    value=offer.model_dump(mode="json"),
                    kind="hotel_offer",
                    request_revision=request.revision,
                    conditions=evidence_conditions(request, "hotel_offer"),
                    provider="fictional-hotels",
                    source_ref="fixture:kyoto-hotels-v1/" + rate.rate_id,
                    content_version=version,
                    retrieved_at=offer.quoted_at,
                    valid_until=offer.expires_at,
                    data_mode="fixture",
                )
            )
            if len(records) >= limit:
                break
        if records:
            await self.travel.record_evidence(context, records)
        return tuple(records)

    async def known_quotes(
        self, context: RunContext, ids: tuple[UUID, ...]
    ) -> tuple[EvidenceRecord, ...]:
        async with transaction(self.travel.database) as db:
            rows = await entity_evidence(db, context, "hotel_offer", tuple(str(id) for id in ids))
        records = {
            row.payload["entity_id"]: EvidenceRecord.model_validate(row.payload) for row in rows
        }
        if set(records) != {str(id) for id in ids} or len(rows) != len(set(ids)):
            raise ServiceError(404, "blocked", "报价ID不存在或不属于此会话", "offer_not_found")
        return tuple(records[str(id)] for id in ids)

    async def present(
        self, context: RunContext, revision: int, ids: tuple[UUID, ...]
    ) -> dict[str, object]:
        await self._request(context, revision)
        known = await self.known_quotes(context, ids)
        records = await self.travel.resolve_evidence(
            context, tuple(record.evidence_id for record in known)
        )
        offers = tuple(HotelOffer.model_validate(record.value) for record in records)
        return {
            "component": "hotel_comparison",
            "cards": cards(records),
            "comparison": compare(offers, datetime.now(UTC)),
        }


def cards(records: tuple[EvidenceRecord, ...]) -> list[dict[str, object]]:
    return [
        {
            **HotelOffer.model_validate(record.value).card(),
            "evidence_id": str(record.evidence_id),
            "source_ref": record.source_ref,
            "content_version": record.content_version,
        }
        for record in records
    ]
