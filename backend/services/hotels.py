"""酒店查询/刷新/补卡用例；不可变报价保存在已有Evidence，避免重复事实表。"""

from datetime import UTC, datetime
from uuid import UUID

from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext
from backend.domain.external_data import ExternalDataError
from backend.domain.hotel_details import HotelDisplayDetails
from backend.domain.hotel_selection import hotel_rate_indices
from backend.domain.hotels import HotelOffer, compare, quote
from backend.domain.room_preferences import room_assessment, room_order, room_preferences_question
from backend.domain.travel_request import (
    TravelRequest,
    hotel_search_location_required,
    lodging_budget_relation,
)
from backend.persistence.travel import (
    entity_evidence,
    evidence_from_row,
    find_evidence,
    hotel_offer_elsewhere,
)
from backend.providers.hotel_fixture import load_rates
from backend.services.common import ServiceError, transaction
from backend.services.travel import TravelService, require_revision


class HotelService:
    def __init__(self, travel: TravelService) -> None:
        self.travel = travel

    async def _request(self, context: RunContext, revision: int) -> TravelRequest:
        request = await self.travel.get_request(context)
        require_revision(request, revision)
        relation = lodging_budget_relation(request)
        if relation.status == "conflict":
            raise ServiceError(409, "conflict", relation.message, "lodging_budget_conflict")
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
        if question := room_preferences_question(request):
            raise ServiceError(422, "validation", question, "hotel_room_preferences_missing")
        if live := self.travel.live:
            if hotel_search_location_required(request):
                raise ServiceError(
                    422,
                    "validation",
                    "目的地范围较大，请在对话中指定具体住宿城市或地点；原目的地和住宿条件已保留。",
                    "hotel_search_location_required",
                )
            if not live.google or not live.rakuten:
                raise ServiceError(
                    503,
                    "unavailable",
                    "乐天酒店查询暂不可用：数据API配置缺失",
                    "hotel_api_unconfigured",
                )
            assert request.city
            try:
                point = await live.google.geocode(request.hotel_search_location or request.city)
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
            if records:
                await self.travel.record_evidence(context, records)
            return tuple(records)
        try:
            rates, version = load_rates()
        except (OSError, ValueError):
            raise ServiceError(503, "unavailable", "模拟酒店目录暂不可用") from None
        records = []
        rate_keys: list[tuple[str, str]] = []
        for rate in rates:
            if (hotel_id and rate.hotel_id != hotel_id) or (rate_id and rate.rate_id != rate_id):
                continue
            offer = quote(rate, request, datetime.now(UTC))
            if offer is None:
                continue
            rate_keys.append((offer.hotel_id, offer.rate_id))
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
        ordered = room_order(
            [HotelOffer.model_validate(record.value).room_type for record in records], request
        )
        records = [records[index] for index in ordered]
        rate_keys = [rate_keys[index] for index in ordered]
        records = [records[index] for index in hotel_rate_indices(rate_keys, limit)]
        if records:
            await self.travel.record_evidence(context, records)
        return tuple(records)

    async def known_quotes(
        self, context: RunContext, ids: tuple[UUID, ...]
    ) -> tuple[EvidenceRecord, ...]:
        wanted = tuple(str(id) for id in ids)
        async with transaction(self.travel.database) as db:
            rows = await entity_evidence(db, context, "hotel_offer", wanted)
            by_offer = {row.payload["entity_id"]: row for row in rows}
            # 卡片同时含offer_id与evidence_id，模型常把后者当offer_id传入；同会话内按证据ID也认。
            missing = [id for id in ids if str(id) not in by_offer]
            by_evidence = {
                row.id: row
                for row in await find_evidence(db, context, missing)
                if row.kind == "hotel_offer"
            }
            if any(id not in by_evidence for id in missing):
                other = await hotel_offer_elsewhere(db, wanted)
                raise ServiceError(
                    404,
                    "blocked",
                    "报价ID不存在或不属于此会话",
                    "offer_other_session" if other else "offer_unknown_id",
                )
        picked = [by_offer[str(id)] if str(id) in by_offer else by_evidence[id] for id in ids]
        records = {row.id: evidence_from_row(row) for row in picked}  # 同一报价的两种ID合并
        return tuple(records.values())

    async def present(
        self, context: RunContext, revision: int, ids: tuple[UUID, ...]
    ) -> dict[str, object]:
        request = await self._request(context, revision)
        known = await self.known_quotes(context, ids)
        records = await self.travel.resolve_evidence(
            context, tuple(record.evidence_id for record in known)
        )
        request = await self._request(context, revision)
        offers = tuple(HotelOffer.model_validate(record.value) for record in records)
        return {
            "component": "hotel_comparison",
            "cards": cards(records, request),
            "comparison": {
                **compare(offers, datetime.now(UTC)),
                "budget_relation": lodging_budget_relation(request).model_dump(mode="json"),
                "room_preferences_question": room_preferences_question(request),
            },
        }


def cards(
    records: tuple[EvidenceRecord, ...], request: TravelRequest | None = None
) -> list[dict[str, object]]:
    return [
        {
            **HotelOffer.model_validate(record.value).card(request),
            **(record.display_details or HotelDisplayDetails()).model_dump(mode="json"),
            **room_assessment(
                HotelOffer.model_validate(record.value).room_type, request
            ).model_dump(mode="json"),
            "evidence_id": str(record.evidence_id),
            "source_ref": record.source_ref,
            "content_version": record.content_version,
        }
        for record in (
            records[index]
            for index in room_order(
                [HotelOffer.model_validate(record.value).room_type for record in records], request
            )
        )
    ]
