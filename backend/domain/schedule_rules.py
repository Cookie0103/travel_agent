"""第二阶段的行程边界与日程提醒，基于服务端条件和已核实证据。"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import asin, cos, radians, sin, sqrt
from uuid import UUID

from backend.domain.catalog import TRANSIT_STOPS, Place
from backend.domain.choices import PREFIXES, identifies_trip_boundary
from backend.domain.evidence import EvidenceRecord
from backend.domain.hotels import HotelOffer
from backend.domain.itinerary import ItineraryProposal, RouteEstimate, ValidationCheck
from backend.domain.opening_hours import TOKYO
from backend.domain.plans import stays_of
from backend.domain.room_choices import recognized_room_choices
from backend.domain.room_preferences import room_assessment
from backend.domain.travel_request import TravelRequest, same_city
from backend.domain.validation_levels import rule_status


@dataclass(frozen=True)
class ScheduleLimits:
    station_departure_minutes: int = 30
    airport_departure_minutes: int = 120
    daily_move_minutes: int = 180
    daily_city_changes: int = 1
    backtrack_leg_km: float = 5
    backtrack_return_km: float = 2
    child_max_stops: int = 4
    child_latest_end: time = time(20)
    rain_threshold: int = 60


DEFAULT_SCHEDULE_LIMITS = ScheduleLimits()
_CLOCK = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)")
_CHINESE_CLOCK = re.compile(
    r"(?<!\d)(?:(凌晨|早上|上午|中午|下午|傍晚|晚上)\s*)?"
    r"([01]?\d|2[0-3])\s*[点时時](?:(半)|([0-5]?\d)分)?"
)
_MUST_VISIT = re.compile(r"^(?:一定要去|必须去|必去)[：:\s]*(.+)$")
_ROOM_QUALIFIERS = {
    "non_smoking": re.compile(r"禁煙|禁烟|\bnon[- ]?smoking\b", re.I),
    "smoking": re.compile(r"喫煙|吸烟|\bsmoking\b", re.I),
    "twin": re.compile(r"ツイン|双床|\btwin\b", re.I),
    "double": re.compile(r"ダブル|大床|\b(?:double|queen|king)\b", re.I),
    "private": re.compile(r"個室|独立房|\bprivate\b|双床房|大床房|家庭房", re.I),
}


def condition_time(text: str, role: str) -> time | None:
    prefix = PREFIXES[role][0]
    text = text.strip()
    if role in {"arrival", "departure"}:
        if not identifies_trip_boundary(text, role):
            return None
    elif not text.startswith(prefix):
        return None
    label = text.removeprefix(prefix).strip()
    if label == "中午前":
        return time(12)
    clocks = list(_CLOCK.finditer(label))
    chinese = list(_CHINESE_CLOCK.finditer(label))
    if len(clocks) + len(chinese) != 1:
        return None
    if clocks:
        hour, minute = map(int, clocks[0].groups())
        return time(hour, minute)
    period, hours, half, minutes = chinese[0].groups()
    hour = int(hours)
    if period in {"中午", "下午", "傍晚", "晚上"} and hour < 12:
        hour += 12
    if period == "凌晨" and hour == 12:
        hour = 0
    return time(hour, 30 if half else int(minutes or 0))


def clock_constraint(request: TravelRequest, role: str) -> time | None:
    values = {
        moment
        for text in (*request.hard_constraints, *request.soft_constraints)
        if (moment := condition_time(text, role)) is not None
    }
    return next(iter(values)) if len(values) == 1 else None


def day_items(proposal: ItineraryProposal) -> dict[date, list[int]]:
    result: dict[date, list[int]] = {}
    for index, item in enumerate(proposal.items):
        result.setdefault(item.start.astimezone(TOKYO).date(), []).append(index)
    return result


def time_checks(
    request: TravelRequest, proposal: ItineraryProposal, limits: ScheduleLimits
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    arrival = clock_constraint(request, "arrival")
    depart = clock_constraint(request, "departure")
    wake = clock_constraint(request, "wake")
    evening = clock_constraint(request, "evening")
    airport = any(
        identifies_trip_boundary(text, "departure")
        and re.search(r"机场|空港|飛行機|飞机|航班", text)
        for text in (*request.hard_constraints, *request.soft_constraints)
    )
    buffer = limits.airport_departure_minutes if airport else limits.station_departure_minutes
    for day, indices in day_items(proposal).items():
        first = min(proposal.items[i].start.astimezone(TOKYO) for i in indices)
        last = max(proposal.items[i].end.astimezone(TOKYO) for i in indices)
        subject = f"day:{day.isoformat()}"
        if day == request.start_date and arrival is not None:
            checks.append(
                ValidationCheck(
                    subject=subject,
                    status=rule_status("arrival_boundary", first.time() >= arrival),
                    code="arrival_boundary",
                    message=f"首日活动应从抵达时间 {arrival:%H:%M} 起安排。",
                )
            )
        if day == request.end_date and depart is not None:
            latest = datetime.combine(day, depart, TOKYO) - timedelta(minutes=buffer)
            checks.append(
                ValidationCheck(
                    subject=subject,
                    status=rule_status("departure_boundary", last <= latest),
                    code="departure_boundary",
                    message=f"末日需预留 {buffer} 分钟前往出发点。",
                )
            )
        if (wake is not None and first < datetime.combine(day, wake, TOKYO)) or (
            evening is not None and last > datetime.combine(day, evening, TOKYO)
        ):
            checks.append(
                ValidationCheck(
                    subject=subject,
                    status="unknown",
                    code="daily_hours",
                    message="当天活动超出已确认的起床或晚上结束时段。",
                )
            )
        if request.child_ages and (
            len(indices) > limits.child_max_stops
            or last > datetime.combine(day, limits.child_latest_end, TOKYO)
        ):
            checks.append(
                ValidationCheck(
                    subject=subject,
                    status="unknown",
                    code="child_day_limits",
                    message=f"亲子行程每日建议最多 {limits.child_max_stops} 站，"
                    f"并于 {limits.child_latest_end:%H:%M} 前结束。",
                )
            )
    return checks


def required_places(text: str) -> tuple[str, ...]:
    matched = _MUST_VISIT.fullmatch(text.strip())
    if not matched or re.search(r"或者|或是|选一|[，,。；;]", matched[1]):
        return ()
    return tuple(name.strip() for name in matched[1].split("、") if name.strip())


def _site_name(value: str) -> str:
    return "".join(value.split()).casefold()


def must_visit_checks(request: TravelRequest, places: list[Place | None]) -> list[ValidationCheck]:
    names = {_site_name(name) for place in places if place for name in (place.name, *place.aliases)}
    required = dict.fromkeys(
        name for text in request.hard_constraints for name in required_places(text)
    )
    return [
        ValidationCheck(
            subject=f"required_place:{index}",
            status=rule_status("must_visit", _site_name(name) in names),
            code="must_visit",
            message=f"用户明确要求纳入的景点：{name}。",
        )
        for index, name in enumerate(required, 1)
    ]


def room_preference_checks(
    request: TravelRequest, proposal: ItineraryProposal, records: dict[UUID, EvidenceRecord]
) -> list[ValidationCheck]:
    requirements = recognized_room_choices(request.hard_constraints) & {
        "住宿：独立房间",
        "房型：禁烟",
        "床型：双床",
        "床型：大床",
    }
    if not requirements:
        return []
    hotel_ids = tuple(stay.hotel_evidence_id for stay in proposal.hotel_stays)
    if proposal.hotel_evidence_id:
        hotel_ids = (proposal.hotel_evidence_id,)
    checks: list[ValidationCheck] = []
    for index, hotel_id in enumerate(hotel_ids, 1):
        evidence = records[hotel_id]
        room = (
            HotelOffer.model_validate(evidence.value).room_type
            if evidence.status == "verified"
            else ""
        )
        qualifiers = {
            key
            for key, pattern in _ROOM_QUALIFIERS.items()
            if pattern.search(
                _ROOM_QUALIFIERS["non_smoking"].sub("", room) if key == "smoking" else room
            )
        }
        mismatch = room_assessment(room, request).room_preference_mismatch
        expected = {
            "住宿：独立房间": "private",
            "房型：禁烟": "non_smoking",
            "床型：双床": "twin",
            "床型：大床": "double",
        }
        opposite = {"房型：禁烟": "smoking", "床型：双床": "double", "床型：大床": "twin"}
        mismatch |= any(
            opposite.get(preference) in qualifiers and expected[preference] not in qualifiers
            for preference in requirements
        )
        checks.append(
            ValidationCheck(
                subject=f"hotel_room:{index}",
                status=rule_status("room_preference", False)
                if mismatch
                else "verified"
                if all(
                    expected[preference] in qualifiers
                    and opposite.get(preference) not in qualifiers
                    for preference in requirements
                )
                else "unknown",
                code="room_preference",
                message="按已选报价的房型名核对住宿、禁烟及床型要求。",
            )
        )
    return checks


def _distance_km(start: Place, end: Place) -> float:
    a_lat, b_lat = radians(start.latitude), radians(end.latitude)
    d_lat = b_lat - a_lat
    d_lon = radians(end.longitude - start.longitude)
    angle = sin(d_lat / 2) ** 2 + cos(a_lat) * cos(b_lat) * sin(d_lon / 2) ** 2
    return 12742 * asin(sqrt(min(1, angle)))


def _backtracks(a: Place, b: Place, c: Place, limits: ScheduleLimits) -> bool:
    return (
        same_city(a.city, b.city)
        and same_city(b.city, c.city)
        and _distance_km(a, b) >= limits.backtrack_leg_km
        and _distance_km(b, c) >= limits.backtrack_leg_km
        and _distance_km(a, c) <= limits.backtrack_return_km
    )


def daily_route_checks(
    proposal: ItineraryProposal,
    places: list[Place | None],
    records: dict[UUID, EvidenceRecord],
    limits: ScheduleLimits,
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    for day, indices in day_items(proposal).items():
        subject = f"day:{day.isoformat()}"
        minutes = 0
        for index in indices[1:]:
            route_id = proposal.items[index].route_evidence_id
            if route_id is not None and (record := records[route_id]).status == "verified":
                minutes += RouteEstimate.model_validate(record.value).minutes or 0
        stops = [places[i] for i in indices]
        changes = sum(
            left is not None and right is not None and not same_city(left.city, right.city)
            for left, right in zip(stops, stops[1:], strict=False)
        )
        if minutes > limits.daily_move_minutes or changes > limits.daily_city_changes:
            checks.append(
                ValidationCheck(
                    subject=subject,
                    status="unknown",
                    code="daily_movement",
                    message=f"当天已知移动 {minutes} 分钟、跨城 {changes} 次。"
                    f"建议上限 {limits.daily_move_minutes} 分钟 / {limits.daily_city_changes} 次。",
                )
            )
        if any(
            a is not None and b is not None and c is not None and _backtracks(a, b, c, limits)
            for a, b, c in zip(stops, stops[1:], stops[2:], strict=False)
        ):
            checks.append(
                ValidationCheck(
                    subject=subject,
                    status="unknown",
                    code="day_backtrack",
                    message="当天在同城长距离往返并回到起点附近，建议将邻近项目排在一起。",
                )
            )
    return checks


def hotel_return_checks(
    request: TravelRequest,
    proposal: ItineraryProposal,
    places: list[Place | None],
    records: dict[UUID, EvidenceRecord],
) -> list[ValidationCheck]:
    nights = stays_of(proposal, request)
    if not nights:
        return []
    checks: list[ValidationCheck] = []
    for day, indices in day_items(proposal).items():
        if all(
            (place := places[index]) is not None
            and place.category.strip().casefold() in TRANSIT_STOPS
            and not proposal.items[index].note
            for index in indices
        ):
            continue
        stay = next((stay for stay in nights if stay.check_in <= day < stay.check_out), None)
        if stay is None or (record := records[stay.hotel_evidence_id]).status != "verified":
            continue
        hotel = HotelOffer.model_validate(record.value)
        last = places[indices[-1]]
        if last and _site_name(hotel.hotel_name) in {
            _site_name(name) for name in (last.name, *last.aliases)
        }:
            continue
        checks.append(
            ValidationCheck(
                subject=f"day:{day.isoformat()}",
                status="unknown",
                code="hotel_return",
                message="当天有已选住宿，请在日程最后说明返回该酒店。",
            )
        )
    return checks
