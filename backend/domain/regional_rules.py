"""核对预约、出行高峰与已知住宿接待时间。"""

import re
from datetime import datetime, time, timedelta
from typing import Literal
from uuid import UUID

from backend.domain.catalog import Place
from backend.domain.evidence import EvidenceRecord
from backend.domain.hotels import HotelOffer
from backend.domain.itinerary import ItineraryProposal, ValidationCheck
from backend.domain.opening_hours import TOKYO, opening_state
from backend.domain.plans import stays_of
from backend.domain.travel_request import TravelRequest, city_key

# 2026-11-28 核对主办方说明。作用是提醒用户安排预约，和库存/已经订票无关。
RESERVATIONS = (
    (
        "東京",
        ("三鷹の森ジブリ美術館", "三鹰之森吉卜力美术馆", "Ghibli Museum", "Ghibli Museum, Mitaka"),
        "入场需预约指定时段。入场前完成预约，次月票从每月 10 日 10:00（日本时间）开售。",
        "https://www.ghibli-museum.jp/en/tickets/",
    ),
    (
        "京都",
        ("桂離宮", "桂离宫", "Katsura Imperial Villa"),
        "须参加指定时段的导览。出行前优先申请，若未预约，出发前核实当日现场名额。",
        "https://sankan.kunaicho.go.jp/multilingual/lang/en/information.html",
    ),
    (
        "東京",
        ("teamLab Borderless", "森ビル デジタルアート ミュージアム", "teamLab无界"),
        "请在计划入场时段前核实余量并购票，热门时段适合提前安排。",
        "https://www.teamlab.art/e/tokyo/",
    ),
)
# 2026-11-28，JNTO 的参考高峰，樱花和红叶日期为行程提醒的固定近似窗口。
# https://www.japan.travel/en/plan/faq/
# https://www.japan.travel/en/guide/honeymoon/
# https://www.japan.travel/en/responsible-travel-guide/features/making-reservations/
PEAK_PERIODS: tuple[tuple[str, tuple[int, int], tuple[int, int], frozenset[str]], ...] = (
    ("年末年初", (12, 27), (1, 4), frozenset()),
    ("黄金周", (4, 29), (5, 5), frozenset()),
    ("盂兰盆节", (8, 13), (8, 16), frozenset()),
    ("樱花季", (3, 25), (4, 10), frozenset({"京都", "東京", "大阪", "奈良", "広島"})),
    ("红叶季", (11, 15), (11, 30), frozenset({"京都", "東京", "大阪", "奈良", "広島"})),
)
_GHIBLI_LAST_ENTRY = time(17)  # 16 点票最迟 1 小时内入场。官方 https://www.ghibli-museum.jp/ticket/
_CHECK_IN = re.compile(r"办理入住|入住|check[\s-]?in", re.I)
_CHECK_OUT = re.compile(r"回房|退房|checkout|check[\s-]?out", re.I)
_LUGGAGE = re.compile(r"寄存|寄送|托运|随身(?:带)?|携带行李|存放行李|行李箱.{0,5}携带")
_CLOCK = re.compile(r"([0-2]\d):([0-5]\d)")


def _key(name: str) -> str:
    return "".join(name.split()).casefold()


def _same_place(place: Place | None, names: tuple[str, ...]) -> bool:
    return place is not None and bool(
        {_key(name) for name in (place.name, *place.aliases)} & {_key(name) for name in names}
    )


def last_admission(place: Place) -> time | None:
    city, names, _, _ = RESERVATIONS[0]
    if city_key(place.city) == city and _same_place(place, names):
        return _GHIBLI_LAST_ENTRY
    return None


def place_opening_state(
    place: Place, start: datetime, end: datetime
) -> Literal["open", "closed", "unknown"]:
    if (latest := last_admission(place)) and start.astimezone(TOKYO).time() > latest:
        return "closed"
    return opening_state(place.opening_hours, start, end)


def context_checks(
    proposal: ItineraryProposal, places: list[Place | None]
) -> list[ValidationCheck]:
    results: list[ValidationCheck] = []
    warned: set[tuple[str, str]] = set()
    for index, (item, place) in enumerate(zip(proposal.items, places, strict=True)):
        if place is None:
            continue
        city = city_key(place.city)
        moment = item.start.astimezone(TOKYO)
        for needed_city, names, detail, source in RESERVATIONS:
            if city != needed_city or not _same_place(place, names):
                continue
            results.append(
                ValidationCheck(
                    subject=f"item:{index}",
                    status="verified",
                    code="reservation_required",
                    message=f"{detail} 参考：{source}",
                )
            )
            break
        point = moment.month, moment.day
        for label, start, end, regions in PEAK_PERIODS:
            in_period = start <= point <= end if start <= end else point >= start or point <= end
            if in_period and (not regions or city in regions) and (city, label) not in warned:
                warned.add((city, label))
                results.append(
                    ValidationCheck(
                        subject=f"item:{index}",
                        status="unknown",
                        code="travel_peak",
                        message=(
                            f"{place.city} 处于{label}客流提醒时段，建议提前核实交通和住宿余量。"
                        ),
                    )
                )
    return results


def _minutes(clock: str | None, *, overnight: bool = False) -> int | None:
    if not clock or not (value := _CLOCK.fullmatch(clock)):
        return None
    hour, minute = map(int, value.groups())
    if hour >= 24 and not overnight:
        return None
    return 60 * hour + minute


def stay_timing_checks(
    request: TravelRequest,
    proposal: ItineraryProposal,
    places: list[Place | None],
    evidence: dict[UUID, EvidenceRecord],
) -> list[ValidationCheck]:
    stays = sorted(stays_of(proposal, request), key=lambda stay: stay.check_in)
    hotels = {
        ref: HotelOffer.model_validate(evidence[ref].value)
        for ref in {stay.hotel_evidence_id for stay in stays}
        if evidence[ref].status == "verified"
    }
    results: list[ValidationCheck] = []
    for previous, current in zip(stays, stays[1:], strict=False):
        day = previous.check_out
        first = hotels.get(previous.hotel_evidence_id)
        second = hotels.get(current.hotel_evidence_id)
        if (
            day != current.check_in
            or first is None
            or second is None
            or first.hotel_id == second.hotel_id
        ):
            continue
        if any(
            item.start.astimezone(TOKYO).date() == day and _LUGGAGE.search(item.note or "")
            for item in proposal.items
        ):
            continue
        results.append(
            ValidationCheck(
                subject=f"day:{day.isoformat()}",
                status="unknown",
                code="hotel_change_luggage",
                message="当天需要换酒店，请说明行李寄存、寄送或随身携带的安排。",
            )
        )
    arrived: set[UUID] = set()
    for index, (item, place) in enumerate(zip(proposal.items, places, strict=True)):
        start = item.start.astimezone(TOKYO)
        end = item.end.astimezone(TOKYO)
        day = start.date()
        note = item.note or ""
        for stay in stays:
            hotel = hotels.get(stay.hotel_evidence_id)
            if hotel is None or not _same_place(place, (hotel.hotel_name,)):
                continue
            details = evidence[stay.hotel_evidence_id].display_details
            if details is None:
                continue
            minutes = 60 * start.hour + start.minute
            earliest = _minutes(details.checkin_time)
            latest = _minutes(details.latest_checkin_time, overnight=True)
            checkout = _minutes(details.checkout_time)
            checkin_marked = _CHECK_IN.search(note)
            too_early = (
                day == stay.check_in
                and checkin_marked
                and earliest is not None
                and minutes < earliest
            )
            since_checkin = (day - stay.check_in).days * 1440 + minutes
            arrival_slot = (
                0 <= since_checkin < 30 * 60
                and stay.hotel_evidence_id not in arrived
                and (checkin_marked or not re.search(r"寄存|寄送|经过|路过", note))
            )
            if arrival_slot:
                arrived.add(stay.hotel_evidence_id)
            too_late = (arrival_slot or (checkin_marked and day == stay.check_in)) and (
                latest is not None and since_checkin > latest
            )
            leaving = (
                datetime.combine(stay.check_out, time.min, TOKYO) + timedelta(minutes=checkout)
                if checkout is not None
                else None
            )
            after_checkout = (
                day == stay.check_out
                and _CHECK_OUT.search(note)
                and leaving
                and (end > leaving if "回房" in note else start > leaving)
            )
            if too_early or too_late or after_checkout:
                results.append(
                    ValidationCheck(
                        subject=f"item:{index}",
                        status="unknown",
                        code="hotel_stay_time",
                        message=(
                            "当天该时段超出酒店已知入住时段，请调整或提前联系酒店。"
                            if too_early or too_late
                            else "该时段已超过酒店退房时间，请安排寄存或离店后的活动。"
                        ),
                    )
                )
                break
    return results
