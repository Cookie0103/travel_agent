"""规划用例：解析本人当前证据、发布估算路段、调用纯校验器；不实现模型修复循环。"""

from datetime import UTC, datetime, timedelta

from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext
from backend.domain.itinerary import ItineraryProposal, RouteInput, ValidationReport
from backend.domain.travel_request import TravelRequest
from backend.domain.validator import validate_itinerary
from backend.providers.routes_fixture import estimate, load_routes
from backend.services.common import ServiceError
from backend.services.travel import TravelService


class PlanningService:
    def __init__(self, travel: TravelService) -> None:
        self.travel = travel

    async def current(self, context: RunContext, revision: int) -> TravelRequest:
        request = await self.travel.get_request(context)
        if request.revision != revision:
            raise ServiceError(409, "conflict", "旅行条件已变化，请读取最新revision")
        return request

    async def routes(
        self, context: RunContext, arguments: RouteInput
    ) -> tuple[EvidenceRecord, ...]:
        request = await self.current(context, arguments.expected_revision)
        if request.transport is None:
            raise ServiceError(422, "validation", "missing_fields: transport")
        ids = tuple(
            dict.fromkeys(
                id for leg in arguments.legs for id in (leg.from_evidence_id, leg.to_evidence_id)
            )
        )
        records = await self.travel.resolve_evidence(context, ids)
        if any(record.kind != "place" or record.status != "verified" for record in records):
            raise ServiceError(422, "validation", "起终点必须是有来源的当前place证据")
        places = {record.evidence_id: record.entity_id for record in records}
        try:
            rates, version = load_routes()
        except (OSError, ValueError):
            raise ServiceError(503, "unavailable", "自制路段表暂不可用") from None
        now = datetime.now(UTC)
        results = []
        for leg in arguments.legs:
            route = estimate(
                rates,
                request,
                places[leg.from_evidence_id],
                places[leg.to_evidence_id],
                leg.departure,
            )
            results.append(
                EvidenceRecord(
                    entity_id=str(route.route_id),
                    field_path="route",
                    value=route.model_dump(mode="json"),
                    kind="route",
                    request_revision=request.revision,
                    conditions=evidence_conditions(request, "route"),
                    provider="self-authored-route-table",
                    source_ref="fixture:kyoto-routes-v1",
                    content_version=version,
                    retrieved_at=now,
                    valid_until=now + timedelta(minutes=15),
                    data_mode="fixture",
                )
            )
        await self.travel.record_evidence(context, results)
        return tuple(results)

    async def validate(self, context: RunContext, proposal: ItineraryProposal) -> ValidationReport:
        request = await self.current(context, proposal.expected_revision)
        records = await self.travel.resolve_evidence(context, proposal.evidence_ids())
        try:
            return validate_itinerary(request, proposal, records, datetime.now(UTC))
        except ValueError:
            raise ServiceError(422, "validation", "行程引用的证据类型、条件或内容不一致") from None
