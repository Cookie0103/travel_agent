"""规则回归基于可复用的自造旅行记录，不调用供应商或语言模型。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from backend.domain.catalog import Place, Source
from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.hotel_details import StoredHotelDetails
from backend.domain.hotels import HotelOffer
from backend.domain.itinerary import HotelStay, ItineraryProposal, ProposedItem, RouteEstimate
from backend.domain.itinerary_revision import edit_scope_check
from backend.domain.opening_hours import TOKYO
from backend.domain.regional_rules import context_checks, place_opening_state, stay_timing_checks
from backend.domain.schedule_rules import (
    DEFAULT_SCHEDULE_LIMITS,
    daily_route_checks,
    hotel_return_checks,
    must_visit_checks,
    room_preference_checks,
    time_checks,
)
from backend.domain.travel_request import TravelRequest
from backend.domain.validator import (
    budget_checks,
    constraint_checks,
    sightseeing_checks,
    visit_checks,
)
from backend.domain.weather_rules import rain_checks

type Expected = Literal["none", "unknown", "conflict", "verified"]
type Mode = Literal["clear", "border", "flag"]

DEPART = date(2026, 11, 5)
FIRST = date(2026, 11, 3)
TODAY = datetime(2026, 10, 10, 0, tzinfo=TOKYO)
LIMITS = DEFAULT_SCHEDULE_LIMITS
SOURCE = Source(
    provider="synthetic",
    source_ref="synthetic:rule-facts",
    content_version="b5-v1",
    retrieved_at=TODAY,
    license="Self-authored rules example",
    license_url="#synthetic",
    attribution="合成规则题",
    data_mode="synthetic",
)


@dataclass(frozen=True)
class Rule:
    number: int
    title: str
    level: Literal["block", "warning", "note"]


RULES = (
    Rule(1, "单城节奏、空档与停留", "warning"),
    Rule(2, "纯换乘停靠的未知费用", "warning"),
    Rule(3, "逐条识别旅行条件", "warning"),
    Rule(4, "首末日时间边界", "block"),
    Rule(5, "仅修改用户点名范围", "block"),
    Rule(6, "包含明确点名的景点", "block"),
    Rule(7, "选择的房型符合硬要求", "block"),
    Rule(8, "用户确认的作息", "warning"),
    Rule(9, "同城折返与过夜返回酒店", "warning"),
    Rule(10, "每天移动时长与跨城次数", "warning"),
    Rule(11, "亲子日程容量", "warning"),
    Rule(12, "高降水概率的室内安排", "block"),
    Rule(13, "来源已知的营业时段", "block"),
    Rule(14, "预约制项目标记", "note"),
    Rule(15, "高峰客流提醒", "warning"),
    Rule(16, "换酒店日行李", "warning"),
    Rule(17, "酒店入住与退房时刻", "warning"),
)


def _when(day: date, minutes: int) -> datetime:
    return datetime.combine(day, datetime.min.time(), TOKYO) + timedelta(minutes=minutes)


def _place(index: int, **updates: object) -> Place:
    defaults: dict[str, object] = {
        "place_id": f"synthetic-{index}",
        "city": "京都",
        "name": f"合成景点{index}",
        "latitude": 35.01,
        "longitude": 135.72,
        "category": "museum",
        "coordinate_kind": "node",
        "opening_hours": "24/7",
        "source": SOURCE,
        "field_sources": {},
    }
    return Place.model_validate({**defaults, **updates})


class Trip:
    def __init__(self, **updates: object) -> None:
        base: dict[str, object] = {
            "revision": 1,
            "city": "京都",
            "start_date": FIRST,
            "end_date": DEPART,
            "adults": 2,
            "child_ages": (),
            "rooms": 1,
            "transport": "walk",
        }
        self.request = TravelRequest.model_validate({**base, **updates})
        self.items: list[ProposedItem] = []
        self.places: list[Place | None] = []
        self.evidence: dict[UUID, EvidenceRecord] = {}

    def add(
        self,
        index: int,
        day: date,
        start: int,
        length: int = 45,
        *,
        place: Place | None = None,
        note: str | None = None,
        route: int | None = None,
    ) -> None:
        place = place or _place(index)
        main = self._store(
            place.place_id, "place", UUID(int=index + 1), place.model_dump(mode="json")
        )
        previous = self.places[-1] if self.places else None
        route_id = None
        if route is not None and previous:
            estimate = RouteEstimate(
                route_id=UUID(int=100 + index),
                departure=self.items[-1].end,
                transport="walk",
                from_place_id=previous.place_id,
                to_place_id=place.place_id,
                minutes=route,
                confidence="estimate",
                fare=Decimal(0),
            )
            route_id = self._store(
                str(estimate.route_id),
                "route",
                estimate.route_id,
                estimate.model_dump(mode="json"),
            )
        self.places.append(place)
        self.items.append(
            ProposedItem(
                place_evidence_id=main,
                start=_when(day, start),
                end=_when(day, start + length),
                route_evidence_id=route_id,
                note=note,
            )
        )

    def _store(
        self,
        entity: str,
        kind: Literal["place", "route", "hotel_offer"],
        ref: UUID,
        value: object,
        details: StoredHotelDetails | None = None,
    ) -> UUID:
        self.evidence[ref] = EvidenceRecord.model_validate(
            {
                "evidence_id": ref,
                "entity_id": entity,
                "kind": kind,
                "field_path": kind,
                "value": value,
                "request_revision": self.request.revision,
                "conditions": evidence_conditions(self.request, kind),
                "provider": "synthetic",
                "source_ref": "synthetic:rule-facts",
                "content_version": "b5-v1",
                "retrieved_at": TODAY,
                "valid_until": TODAY + timedelta(days=1),
                "data_mode": "synthetic",
                "display_details": details,
            }
        )
        return ref

    def hotel(self, index: int, room: str = "禁煙ツイン個室") -> UUID:
        ref = UUID(int=200 + index)
        quote = HotelOffer(
            offer_id=ref,
            rate_id=f"rate-{index}",
            hotel_id=f"hotel-{index}",
            room_type=room,
            hotel_name=f"合成酒店{index}",
            currency="JPY",
            base_amount=Decimal(9000),
            tax_amount=Decimal(0),
            fee_amount=Decimal(0),
            breakfast=True,
            refundable=True,
            quoted_at=TODAY,
            expires_at=TODAY + timedelta(days=1),
            request=self.request,
            data_mode="synthetic",
        )
        return self._store(
            str(ref),
            "hotel_offer",
            ref,
            quote.model_dump(mode="json"),
            StoredHotelDetails(
                checkin_time="15:00", latest_checkin_time="23:00", checkout_time="10:00"
            ),
        )

    def proposal(
        self, *, hotel: UUID | None = None, stays: tuple[HotelStay, ...] = ()
    ) -> ItineraryProposal:
        return ItineraryProposal(
            expected_revision=self.request.revision,
            items=tuple(self.items),
            hotel_evidence_id=hotel,
            hotel_stays=stays,
        )

    def stays(self) -> tuple[HotelStay, ...]:
        transfer = FIRST + timedelta(days=1)
        return (
            HotelStay(check_in=FIRST, check_out=transfer, hotel_evidence_id=self.hotel(1)),
            HotelStay(check_in=transfer, check_out=DEPART, hotel_evidence_id=self.hotel(2)),
        )


def observe(rule: int, mode: Mode, variant: int) -> tuple[str, Expected]:
    """题目改变实际条件，预期由题库声明；返回实际检查的状态。"""
    flag = mode == "flag"
    minute = 8 * 60 + variant * 8
    trip = Trip()
    match rule:
        case 1:
            if variant % 3 == 0:
                trip.add(0, FIRST, minute)
                gap = {"clear": 150 + variant, "border": 180, "flag": 180 + variant}[mode]
                trip.add(1, FIRST, minute + 45 + gap)
                code = "day_gap"
            elif variant % 3 == 1:
                length = {"clear": 45 + variant, "border": 45, "flag": 45 - variant}[mode]
                trip.add(0, FIRST, minute, length=length)
                code, checks = (
                    "visit_duration_range",
                    visit_checks(trip.request, trip.proposal(), 0, trip.places[0]),
                )
                return code, next((check.status for check in checks if check.code == code), "none")
            else:
                count = {"clear": 4, "border": 5, "flag": 6}[mode]
                for i in range(count):
                    trip.add(i, FIRST, minute + 60 * i)
                code = "pace_warning"
            checks = sightseeing_checks(trip.request, trip.proposal(), trip.places)
        case 2:
            place = _place(0, category="train_station" if mode != "border" else "bus_station")
            trip.add(0, FIRST, minute, place=place, note="站内用餐" if flag else None)
            code = "other_costs"
            checks = budget_checks(
                trip.request, trip.proposal(), trip.evidence, TODAY, places=trip.places
            )[2]
        case 3:
            label = (
                "偏好没有结构的额外条件"
                if flag
                else ("节奏：标准" if mode == "border" else "住宿：无要求")
            )
            trip = Trip(hard_constraints=(label,))
            code = "free_text_constraints" if flag else "recognized_constraint"
            checks = constraint_checks(trip.request, set())
        case 4:
            if variant % 2:
                trip = Trip(hard_constraints=("第一天抵达：12:00",))
                trip.add(0, FIRST, 720 + {"clear": variant, "border": 0, "flag": -variant}[mode])
                code = "arrival_boundary"
            else:
                trip = Trip(hard_constraints=("最后一天离开：16:00",))
                trip.add(0, DEPART, 885 + {"clear": -variant, "border": 0, "flag": variant}[mode])
                code = "departure_boundary"
            checks = time_checks(trip.request, trip.proposal(), LIMITS)
        case 5:
            trip.add(0, FIRST, minute)
            trip.add(1, FIRST + timedelta(days=1), 13 * 60 + variant)
            before = trip.proposal()
            edit = 0 if flag else 1
            trip.items[edit] = trip.items[edit].model_copy(update={"note": f"换项目{variant}"})
            target = "只改第二天下午的安排" if mode == "border" else "只改第二天"
            change = edit_scope_check(
                target,
                trip.request,
                before,
                trip.proposal(),
                {
                    item.place_evidence_id: place
                    for item, place in zip(trip.items, trip.places, strict=True)
                    if place
                },
            )
            code, checks = "edit_scope", [change] if change else []
        case 6:
            trip = Trip(hard_constraints=(f"一定要去：合成景点{variant}",))
            trip.add(variant if not flag else 0, FIRST, minute)
            code, checks = "must_visit", must_visit_checks(trip.request, trip.places)
        case 7:
            trip = Trip(hard_constraints=("房型：禁烟", "床型：双床"))
            trip.add(0, FIRST, minute)
            hotel = trip.hotel(
                1,
                {"clear": "禁煙ツイン個室", "border": "Non-smoking twin", "flag": "喫煙ダブル"}[
                    mode
                ],
            )
            code = "room_preference"
            checks = room_preference_checks(trip.request, trip.proposal(hotel=hotel), trip.evidence)
        case 8:
            trip = Trip(soft_constraints=("平时起床：09:00",))
            trip.add(0, FIRST, 540 + {"clear": variant, "border": 0, "flag": -variant}[mode])
            code, checks = "daily_hours", time_checks(trip.request, trip.proposal(), LIMITS)
        case 9:
            if variant % 2:
                for i, lat in enumerate((35.0, 35.1, 35.001 if flag else 35.19)):
                    trip.add(i, FIRST, minute + i * 120, place=_place(i, latitude=lat))
                code, checks = (
                    "day_backtrack",
                    daily_route_checks(trip.proposal(), trip.places, trip.evidence, LIMITS),
                )
            else:
                name = "合成景点0" if flag else "合成酒店1"
                trip.add(0, FIRST, minute, place=_place(0, name=name))
                code = "hotel_return"
                checks = hotel_return_checks(
                    trip.request, trip.proposal(hotel=trip.hotel(1)), trip.places, trip.evidence
                )
        case 10:
            trip.add(0, FIRST, minute)
            if variant % 2:
                trip.add(1, FIRST, minute + 300, place=_place(1, city="大阪"))
                if flag:
                    trip.add(2, FIRST, minute + 420, place=_place(2, city="奈良"))
            else:
                travel = {"clear": 180 - variant, "border": 180, "flag": 180 + variant}[mode]
                trip.add(1, FIRST, minute + 300, route=travel)
            code, checks = (
                "daily_movement",
                daily_route_checks(trip.proposal(), trip.places, trip.evidence, LIMITS),
            )
        case 11:
            trip = Trip(child_ages=(variant + 2,))
            count = {"clear": 3, "border": 4, "flag": 5}[mode]
            for i in range(count):
                trip.add(i, FIRST, minute + i * 60)
            code, checks = "child_day_limits", time_checks(trip.request, trip.proposal(), LIMITS)
        case 12:
            trip.add(0, FIRST, minute, place=_place(0, category="park"))
            probability = {"clear": 40 + variant, "border": 59, "flag": 60 + variant - 1}[mode]
            code, checks = (
                "rain_plan",
                rain_checks(
                    trip.proposal(),
                    trip.places,
                    trip.evidence,
                    {("京都", FIRST): probability},
                    LIMITS.rain_threshold,
                ),
            )
        case 13:
            place = _place(0, opening_hours="Mo-Su 09:00-12:00,13:00-17:00; Dec 29-Jan 3 off")
            day = date(2026, 12, 29) if flag and variant % 2 else FIRST
            start = 735 if flag else 780 + (0 if mode == "border" else variant)
            status = place_opening_state(place, _when(day, start), _when(day, start + 30))
            opening: Expected = (
                "verified" if status == "open" else "conflict" if status == "closed" else "unknown"
            )
            return "opening_hours", opening
        case 14:
            name = "桂离宫" if flag else "合成京都景点"
            trip.add(0, FIRST, minute, place=_place(0, name=name))
            code, checks = "reservation_required", context_checks(trip.proposal(), trip.places)
        case 15:
            day = (
                date(2027, 4, 29)
                if flag
                else date(2027, 4, 28 if mode == "border" else 19 + variant)
            )
            trip.add(0, day, minute)
            code, checks = "travel_peak", context_checks(trip.proposal(), trip.places)
        case 16:
            transfer = FIRST + timedelta(days=1)
            trip.add(0, transfer, minute, note=None if flag else "先把行李寄存")
            code = "hotel_change_luggage"
            checks = stay_timing_checks(
                trip.request, trip.proposal(stays=trip.stays()), trip.places, trip.evidence
            )
        case 17:
            when = {"clear": 1380 - variant, "border": 1380, "flag": 1380 + variant}[mode]
            trip.add(0, FIRST, when, note="回酒店休息", place=_place(0, name="合成酒店1"))
            code = "hotel_stay_time"
            checks = stay_timing_checks(
                trip.request, trip.proposal(hotel=trip.hotel(1)), trip.places, trip.evidence
            )
        case _:
            raise ValueError(f"规则 {rule} 不在本阶段")
    return code, next((check.status for check in checks if check.code == code), "none")
