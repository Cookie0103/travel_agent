"""用前一版行程的已核实地点与时段检查用户明确限定的改动范围。"""

import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from uuid import UUID

from backend.domain.catalog import Place
from backend.domain.itinerary import ItineraryProposal, ProposedItem, ValidationCheck
from backend.domain.opening_hours import TOKYO
from backend.domain.plans import stays_of
from backend.domain.travel_request import TravelRequest
from backend.domain.validation_levels import rule_status

_ONLY_CHANGE = re.compile(
    r"(?:只|仅)(?:想|需要)?(?:把|修改|调整|替换|改|换|删除|删)\s*"
    r"(.{1,80}?)(?:换成|改成|替换为|[，。,!！；;]|$)"
)
_PART = r"(上午|下午|晚上|全天)?(?:的?(?:安排|行程|活动))?"
_ORDINAL = re.compile(r"第(\d{1,2}|[一二三四五六七八九十])天" + _PART)
_MONTH_DAY = re.compile(r"(\d{1,2})月(\d{1,2})[日号]" + _PART)
_DAY_PARTS = {
    "上午": (timedelta(), timedelta(hours=12)),
    "下午": (timedelta(hours=12), timedelta(hours=18)),
    "晚上": (timedelta(hours=18), timedelta(days=1)),
}
_CHINESE_ORDINAL = dict(zip("一二三四五六七八九十", range(1, 11), strict=True))
type Slot = tuple[str, datetime, datetime, str | None, str | None]


def limited_edit_target(text: str) -> str | None:
    return match[1].strip() if (match := _ONLY_CHANGE.search(text)) else None


def _scope_window(target: str, request: TravelRequest) -> tuple[datetime, datetime] | None:
    if request.start_date is None or request.end_date is None:
        return None
    day = None
    part = None
    if ordinal := _ORDINAL.fullmatch(target):
        value, part = ordinal.groups()
        index = int(value) if value.isdecimal() else _CHINESE_ORDINAL[value]
        length = (request.end_date - request.start_date).days
        if 1 <= index <= length + 1:
            day = request.start_date + timedelta(days=index - 1)
    elif calendar := _MONTH_DAY.fullmatch(target):
        part = calendar[3]
        for year in {request.start_date.year, request.end_date.year}:
            try:
                candidate = date(year, int(calendar[1]), int(calendar[2]))
            except ValueError:
                continue
            if request.start_date <= candidate <= request.end_date:
                day = candidate
                break
    if day is None:
        return None
    midnight = datetime.combine(day, time.min, TOKYO)
    start, end = _DAY_PARTS.get(part or "", (timedelta(), timedelta(days=1)))
    return midnight + start, midnight + end


def _name(value: str) -> str:
    return "".join(value.split()).casefold()


def _slot(item: ProposedItem, identities: dict[UUID, str]) -> Slot:
    identity = identities.get(item.place_evidence_id, str(item.place_evidence_id))
    backup = item.rain_alternative_place_evidence_id
    return (
        identity,
        item.start.astimezone(TOKYO),
        item.end.astimezone(TOKYO),
        item.note,
        identities.get(backup, str(backup)) if backup else None,
    )


def edit_scope_check(
    text: str,
    request: TravelRequest,
    before: ItineraryProposal,
    after: ItineraryProposal,
    places: dict[UUID, Place],
    *,
    historical_places: dict[UUID, str] | None = None,
    hotels: dict[UUID, tuple[str, str]] | None = None,
) -> ValidationCheck | None:
    target = limited_edit_target(text)
    if not target:
        return None
    place_ids = {
        **(historical_places or {}),
        **{ref: place.place_id for ref, place in places.items()},
    }
    old = [_slot(item, place_ids) for item in before.items]
    new = [_slot(item, place_ids) for item in after.items]
    identities = hotels or {}
    old_stays = {
        (stay.check_in, stay.check_out): identities.get(
            stay.hotel_evidence_id, stay.hotel_evidence_id
        )
        for stay in stays_of(before, request)
    }
    new_stays = {
        (stay.check_in, stay.check_out): identities.get(
            stay.hotel_evidence_id, stay.hotel_evidence_id
        )
        for stay in stays_of(after, request)
    }
    if target in {"酒店", "住宿"}:
        changes = sum(
            old_stays.get(k) != new_stays.get(k) for k in old_stays.keys() | new_stays.keys()
        )
        preserved = old == new and changes <= 1
    elif window := _scope_window(target, request):
        start, end = window
        preserved = old_stays == new_stays and (
            [slot for slot in old if slot[1] < start or slot[2] > end]
            == [slot for slot in new if slot[1] < start or slot[2] > end]
        )
    else:
        matching_sites = {
            place.place_id
            for place in places.values()
            if _name(target) in {_name(name) for name in (place.name, *place.aliases)}
        }
        matches = [i for i, slot in enumerate(old) if slot[0] in matching_sites]
        if len(matches) != 1:
            return ValidationCheck(
                subject="revision",
                status="unknown",
                code="edit_scope",
                message="请确认只修改的日期、景点或住宿，才能逐项核对保留范围。",
            )
        index = matches[0]
        preserved = old_stays == new_stays and (
            (
                len(new) == len(old)
                and old[:index] + old[index + 1 :] == new[:index] + new[index + 1 :]
            )
            or (len(new) == len(old) - 1 and old[:index] + old[index + 1 :] == new)
        )
    kept = sum((Counter(old) & Counter(new)).values())
    return ValidationCheck(
        subject="revision",
        status=rule_status("edit_scope", preserved),
        code="edit_scope",
        message=(
            f"前一版 {len(old)} 项中保留 {kept} 项，未点名的时段和住宿与限定范围一致。"
            if preserved
            else f"前一版 {len(old)} 项中保留 {kept} 项，请恢复用户未点名修改的时段及住宿。"
        ),
    )
