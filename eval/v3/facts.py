"""脚本条件和 v2 检查共用的只读服务端事实。"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.hotel_flow import HotelPick, current_picks, flow_from_details, lodging_segments
from backend.domain.plans import EVALUATION_DRAFT_SCOPE, PlanDraft, draft_request_scope
from backend.domain.travel_request import (
    TravelRequest,
    TripSegment,
    pace_of,
    same_city,
    segment_request,
)
from backend.persistence import operations, plans, travel
from backend.persistence.models import PlanDraftRow
from backend.services.common import transaction
from backend.services.hotels import cards as display_cards
from backend.services.travel import request_from_row
from eval.core.database import DatabaseEvaluation
from eval.v3.cases import RequestField, split_predicate


@dataclass(frozen=True)
class Snapshot:
    request: TravelRequest
    draft: PlanDraft | None = None
    picked: Mapping[date, dict[str, object]] = field(default_factory=dict)
    plan_saved: bool = False
    draft_scope: Mapping[str, object] | None = None


async def hotel_picks(db: AsyncSession, context: RunContext) -> dict[date, HotelPick]:
    row = await travel.read_request(db, context)
    return (
        current_picks(flow_from_details(row.request_details), request_from_row(row)) if row else {}
    )


@dataclass(frozen=True)
class PickedOffers:
    count: int
    recorded: dict[date, dict[str, object]]
    available: dict[date, dict[str, object]]


async def selected_cards(
    db: AsyncSession, context: RunContext, request: TravelRequest
) -> PickedOffers:
    picks = await hotel_picks(db, context)
    rows = (
        await travel.find_evidence(db, context, [pick.evidence_id for pick in picks.values()])
        if picks
        else []
    )
    evidence = {row.id: row for row in rows if row.kind == "hotel_offer"}
    recorded, available = {}, {}
    now = datetime.now(UTC)
    for day, pick in picks.items():
        row = evidence.get(pick.evidence_id)
        if row is not None:
            record = travel.evidence_from_row(row)
            card = display_cards((record,))[0]
            recorded[day] = card
            if not row.invalidated and record.applicable(request, now):
                available[day] = card
    return PickedOffers(len(picks), recorded, available)


async def read_snapshot(business: DatabaseEvaluation, context: RunContext) -> Snapshot:
    async with transaction(business.sessions.database) as db:
        request = request_from_row(await travel.read_request(db, context))
        expiration = PlanDraftRow.payload["expires_at"].astext
        row = await db.scalar(
            select(PlanDraftRow)
            .where(
                PlanDraftRow.user_id == context.user_id,
                PlanDraftRow.session_id == context.session_id,
            )
            .order_by(expiration.desc(), PlanDraftRow.id)
            .limit(1)
        )
        draft = PlanDraft.model_validate(row.payload) if row else None
        plan = await plans.for_session(db, context)
        scope = (
            await operations.result(
                db, context.session_id, EVALUATION_DRAFT_SCOPE, str(draft.draft_id)
            )
            if draft
            else None
        )
        picked = await selected_cards(db, context, request)
    return Snapshot(request, draft, picked.available, bool(plan and plan.current_version), scope)


def request_value(request: TravelRequest, name: RequestField) -> object:
    match name:
        case "pace":
            return pace_of(request)
        case "constraints":
            return [*request.hard_constraints, *request.soft_constraints, *request.interests]
        case "lodging_budget_upper":
            return request.lodging_budget.amount.upper if request.lodging_budget else None
        case "start_date" | "end_date":
            value = request.start_date if name == "start_date" else request.end_date
            return value.isoformat() if value is not None else None
        case "child_ages":
            return list(request.child_ages) if request.child_ages is not None else None
        case _:
            return getattr(request, name)


def hotel_presentations(events: Sequence[RuntimeEvent]) -> Iterator[dict[str, object]]:
    for event in events:
        data = event.presentation.get("data") if event.presentation else None
        if isinstance(data, dict) and data.get("component") == "hotel_comparison":
            yield data


def hotel_segments(
    data: Mapping[str, object], fallback_range: tuple[str | None, str | None] = (None, None)
) -> list[dict[str, object]]:
    raw = data.get("cards")
    cards = [card for card in raw if isinstance(card, dict)] if isinstance(raw, list) else []
    segments = data.get("segments")
    if isinstance(segments, list) and segments:
        return [
            {
                "check_in": segment.get("check_in"),
                "check_out": segment.get("check_out"),
                "cards": [
                    card
                    for card in cards
                    if card.get("evidence_id") in segment.get("evidence_ids", [])
                ],
            }
            for segment in segments
            if isinstance(segment, dict)
        ]
    return [{"check_in": fallback_range[0], "check_out": fallback_range[1], "cards": cards}]


def segment_at(request: TravelRequest, number: int) -> TripSegment | None:
    segments = lodging_segments(request)
    return segments[number] if number < len(segments) else None


def offer_city(card: Mapping[str, object], segment: TripSegment) -> bool | None:
    stay = card.get("stay")
    city = stay.get("city") if isinstance(stay, dict) else None
    return same_city(city, segment.city) if isinstance(city, str) else None


def offer_dates(card: Mapping[str, object], segment: TripSegment) -> bool | None:
    stay = card.get("stay")
    if not isinstance(stay, dict) or not (stay.get("start_date") and stay.get("end_date")):
        return None
    return (stay["start_date"], stay["end_date"]) == (
        segment.arrive.isoformat(),
        segment.depart.isoformat(),
    )


def picked_offer(snapshot: Snapshot, segment: TripSegment) -> dict[str, object] | None:
    return snapshot.picked.get(segment.arrive)


def hotel_list_current(request: TravelRequest, events: Sequence[RuntimeEvent], number: int) -> bool:
    segment = segment_at(request, number)
    presentation = next(hotel_presentations(tuple(reversed(events))), None)
    if segment is None or presentation is None:
        return False
    displayed = hotel_segments(presentation)
    if number >= len(displayed):
        return False
    cards = displayed[number]["cards"]
    if not isinstance(cards, list) or not cards:
        return False
    expected = segment_request(request, segment).model_dump(
        mode="json", include={"adults", "child_ages", "rooms"}
    )
    for card in cards:
        stay = card.get("stay")
        if (
            not isinstance(stay, dict)
            or not offer_city(card, segment)
            or not offer_dates(card, segment)
            or any(stay.get(key) != value for key, value in expected.items())
        ):
            return False
    return True


def _draft_stale(snapshot: Snapshot) -> bool:
    draft = snapshot.draft
    if draft is None:
        return False
    scope = snapshot.draft_scope
    if scope is None:
        # 旧数据没有保存完整条件，只保守采用服务端已有的修订号。
        if draft.request_revision != snapshot.request.revision:
            return True
    elif scope != draft_request_scope(snapshot.request):
        return True
    selected = {str(card["evidence_id"]) for card in snapshot.picked.values()}
    drafted = {str(stay.hotel_evidence_id) for stay in draft.content.hotel_stays}
    if draft.content.hotel_evidence_id:
        drafted.add(str(draft.content.hotel_evidence_id))
    return selected != drafted


def predicate_matches(predicate: str, facts: Snapshot, events: Sequence[RuntimeEvent]) -> bool:
    name, number = split_predicate(predicate)
    request, draft = facts.request, facts.draft
    match name:
        case "transport_unset":
            return request.transport is None
        case "pace_unset":
            return pace_of(request) is None
        case "children_unset":
            return request.child_ages is None
        case "dates_unset":
            return request.start_date is None or request.end_date is None
        case "city_unset":
            return request.city is None
        case "hotel_list_shown" | "no_hotel_list":
            shown = hotel_list_current(request, events, number or 0)
            return shown if name == "hotel_list_shown" else not shown
        case "hotel_unpicked":
            assert number is not None
            segment = segment_at(request, number)
            if segment is None:
                return True
            offer = picked_offer(facts, segment)
            if not (offer and offer_city(offer, segment) and offer_dates(offer, segment)):
                return True
            expiration = offer.get("expires_at")
            if isinstance(expiration, str):
                try:
                    stamp = datetime.fromisoformat(expiration)
                except ValueError:
                    return True
                return stamp.utcoffset() is None or stamp <= datetime.now(UTC)
            return False
        case "has_draft":
            return draft is not None
        case "no_draft":
            return draft is None
        case "draft_stale":
            return _draft_stale(facts)
        case "no_clean_draft":
            return draft is None or any(
                check.status == "conflict" for check in draft.validation.checks
            )
        case "plan_unsaved":
            return not facts.plan_saved
    raise AssertionError(name)
