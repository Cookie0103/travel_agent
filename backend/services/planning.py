"""规划用例：解析本人当前证据、发布估算路段、调用纯校验器；不实现模型修复循环。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.live_data import LiveData
from backend.domain.catalog import Place
from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext
from backend.domain.itinerary import ItineraryProposal, RouteInput, ValidationReport
from backend.domain.travel_request import TravelRequest
from backend.domain.validator import validate_itinerary
from backend.persistence import travel as requests
from backend.providers.routes_fixture import RouteRate, estimate, load_routes
from backend.services.common import ServiceError, transaction
from backend.services.travel import (
    TravelService,
    hydrate_records,
    request_from_row,
    require_revision,
    resolve_records,
)

PLACE_REF_REASON = "地点引用必须是place证据"
HOTEL_REF_REASON = "酒店引用必须是hotel_offer证据"


class PlanningService:
    def __init__(self, travel: TravelService) -> None:
        self.travel = travel

    async def current(self, context: RunContext, revision: int) -> TravelRequest:
        request = await self.travel.get_request(context)
        require_revision(request, revision)
        return request

    async def routes(
        self, context: RunContext, arguments: RouteInput
    ) -> tuple[EvidenceRecord, ...]:
        request = await self.current(context, arguments.expected_revision)
        if request.transport is None:
            raise ServiceError(
                422, "validation", "missing_fields: transport", "route_missing_transport"
            )
        ids = tuple(
            dict.fromkeys(
                id for leg in arguments.legs for id in (leg.from_evidence_id, leg.to_evidence_id)
            )
        )
        records = await self.travel.resolve_evidence(context, ids)
        if any(record.kind != "place" or record.status != "verified" for record in records):
            raise ServiceError(
                422, "validation", "起终点必须是有来源的当前place证据", "route_endpoint_not_place"
            )
        places = {record.evidence_id: record.entity_id for record in records}
        live = self.travel.live
        rates: tuple[RouteRate, ...] = ()
        version = ""
        if not live:
            try:
                rates, version = load_routes()
            except (OSError, ValueError):
                raise ServiceError(503, "unavailable", "自制路段表暂不可用") from None
        elif not live.google:
            raise ServiceError(503, "unavailable", "未配置 GOOGLE_MAPS_API_KEY")
        now = datetime.now(UTC)
        results = []
        for leg in arguments.legs:
            route = (
                await live.google.route(
                    Place.model_validate(
                        next(
                            record.value
                            for record in records
                            if record.evidence_id == leg.from_evidence_id
                        )
                    ),
                    Place.model_validate(
                        next(
                            record.value
                            for record in records
                            if record.evidence_id == leg.to_evidence_id
                        )
                    ),
                    request.transport,
                    leg.departure,
                    (request.adults or 1) + len(request.child_ages or ()),
                )
                if live and live.google
                else estimate(
                    rates,
                    request,
                    places[leg.from_evidence_id],
                    places[leg.to_evidence_id],
                    leg.departure,
                )
            )
            results.append(
                EvidenceRecord(
                    entity_id=str(route.route_id),
                    field_path="route",
                    value=route.model_dump(mode="json"),
                    kind="route",
                    request_revision=request.revision,
                    conditions=evidence_conditions(request, "route"),
                    provider="google_routes" if live else "self-authored-route-table",
                    source_ref="https://maps.google.com/" if live else "fixture:kyoto-routes-v1",
                    content_version=now.isoformat() if live else version,
                    retrieved_at=now,
                    valid_until=now + timedelta(minutes=15),
                    data_mode="live" if live else "fixture",
                )
            )
        await self.travel.record_evidence(context, results)
        return tuple(results)

    async def validate(self, context: RunContext, proposal: ItineraryProposal) -> ValidationReport:
        async with transaction(self.travel.database) as db:
            request = request_from_row(await requests.owned_request(db, context))
            return await validate_proposal(db, context, request, proposal, self.travel.live)


async def validate_proposal(
    db: AsyncSession,
    context: RunContext,
    request: TravelRequest,
    proposal: ItineraryProposal,
    live: LiveData | None = None,
) -> ValidationReport:
    require_revision(request, proposal.expected_revision)
    records = await resolve_records(
        db, context, request, proposal.evidence_ids(), datetime.now(UTC)
    )
    records = await hydrate_records(records, live)
    try:
        return validate_itinerary(request, proposal, records, datetime.now(UTC))
    except ValueError as error:
        # 校验器的ValueError是固定中文文案(无插值)，可整体作reason；pydantic错误含输入值，只记类名。
        reason = str(error) if type(error) is ValueError else "evidence_model_invalid"
        message = "行程引用的证据类型、条件或内容不一致"
        if reason == PLACE_REF_REASON:
            by_id = {record.evidence_id: record.kind for record in records}
            kinds = sorted(
                {by_id.get(item.place_evidence_id, "unknown") for item in proposal.items}
                - {"place"}
            )
            reason += ":place_ref_kind=" + ",".join(kinds)
            message += (
                "。place_evidence_id只能用search_places/get_place_facts返回的地点证据；"
                "酒店报价证据只能填hotel_evidence_id"
            )
        if reason == HOTEL_REF_REASON:
            by_id = {record.evidence_id: record.kind for record in records}
            kind = (
                by_id.get(proposal.hotel_evidence_id, "unknown")
                if proposal.hotel_evidence_id
                else "unknown"
            )
            reason += ":hotel_ref_kind=" + kind
            message += (
                "。hotel_evidence_id只能填search_hotel_offers返回的酒店卡片的evidence_id"
                "（不是offer_id，也不是地点证据）；没有酒店卡片证据就省略hotel_evidence_id"
            )
        raise ServiceError(422, "validation", message, "validator:" + reason) from None
