"""局部修复：对带硬冲突的行程做有界、单调的确定性改动；校验与路线查询由调用方注入。

只接受“硬冲突数严格下降且不出现新种类/数量的冲突”的改动，已访问集合防环，总尝试数有上限。
不新增景点、不改日期范围、不放宽校验；去掉景点或换天必须写入disclosed，由回复如实说明。
锁定项的时间与内容不动（修不动就保留冲突），只可能随前后项变化而重建路线引用，并披露。
"""

import re
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from math import ceil
from uuid import UUID

from backend.domain.catalog import VISIT_DURATION_RANGES, Place
from backend.domain.itinerary import RouteEstimate, ValidationCheck, ValidationReport
from backend.domain.opening_hours import KYOTO, opening_state
from backend.domain.plans import PlanContent, PlanItem

STALE = {"route_unexpected", "route_scope", "route_departure"}  # 重建路线即可消除
MAX_OPS = 12
STEP = timedelta(minutes=15)
DAY_START, DAY_END = time(7), time(21)

Candidate = tuple[list[PlanItem], str, set[UUID]]  # 新列表、披露文案、被改动项ID
Validate = Callable[[PlanContent], Awaitable[ValidationReport]]
# 参数(前项place证据, 本项place证据, 出发时间)；返回按序对应的(route证据ID, 估算)，额度不足可更短
Reroute = Callable[
    [Sequence[tuple[UUID, UUID, datetime]]], Awaitable[Sequence[tuple[UUID, RouteEstimate]]]
]


@dataclass
class Facts:
    places: Mapping[UUID, Place]  # place证据ID -> 地点
    routes: dict[UUID, RouteEstimate]  # route证据ID -> 估算（重建后追加）
    days: tuple[date, ...]  # 旅行日期范围


@dataclass(frozen=True)
class Repair:
    content: PlanContent
    report: ValidationReport
    disclosed: tuple[str, ...] = ()


@dataclass
class _Run:
    content: PlanContent
    report: ValidationReport
    touched: set[UUID] = field(default_factory=set)


def conflicts(report: ValidationReport) -> list[ValidationCheck]:
    return [check for check in report.checks if check.status == "conflict"]


def item_index(subject: str) -> int | None:
    found = re.fullmatch(r"(?:item:(\d+)|route:-?\d+->(\d+))", subject)
    return int(found[1] or found[2]) if found else None


def day_of(item: PlanItem) -> date:
    return item.start.astimezone(KYOTO).date()


def at(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment, KYOTO)


def label(item: PlanItem, facts: Facts) -> str:
    place = facts.places.get(item.place_evidence_id)
    start, end = item.start.astimezone(KYOTO), item.end.astimezone(KYOTO)
    return f"「{place.name if place else '某一项'}」（{start:%m-%d %H:%M}–{end:%H:%M}）"


def replaced(items: Sequence[PlanItem], index: int, **update: object) -> list[PlanItem]:
    return [item.model_copy(update=update) if i == index else item for i, item in enumerate(items)]


def clamp(
    items: Sequence[PlanItem], bad: list[ValidationCheck], facts: Facts
) -> Iterator[Candidate]:
    for check in bad:
        i = item_index(check.subject)
        if check.code not in {"visit_duration", "visit_duration_range"} or i is None:
            continue
        item, place = items[i], facts.places.get(items[i].place_evidence_id)
        bounds = place and VISIT_DURATION_RANGES.get(place.category.strip().casefold())
        if item.locked or not bounds:
            continue
        lower, upper = (timedelta(minutes=minutes) for minutes in bounds)
        end = item.start + min(max(item.end - item.start, lower), upper)
        yield (
            replaced(items, i, end=end),
            f"停留时长调整为区间内：{label(item, facts)}",
            {item.item_id},
        )


def shifts(
    items: Sequence[PlanItem], bad: list[ValidationCheck], facts: Facts
) -> Iterator[Candidate]:
    """同一天内、不越过相邻项，把停留平移到最近的营业窗口。"""
    for check in bad:
        i = item_index(check.subject)
        if check.code != "opening_hours" or i is None:
            continue
        item, place = items[i], facts.places.get(items[i].place_evidence_id)
        if item.locked or place is None:
            continue
        day, length = day_of(item), item.end - item.start
        low = items[i - 1].end if i and day_of(items[i - 1]) == day else at(day, DAY_START)
        high = (
            items[i + 1].start
            if i + 1 < len(items) and day_of(items[i + 1]) == day
            else at(day, DAY_END)
        )
        slots = (at(day, DAY_START) + n * STEP for n in range(57))
        fits = sorted(
            (s for s in slots if low <= s and s + length <= high and s != item.start),
            key=lambda s: abs(s - item.start),
        )
        found = next(
            (s for s in fits if opening_state(place.opening_hours, s, s + length) == "open"), None
        )
        if found is not None:
            yield (
                replaced(items, i, start=found, end=found + length),
                f"平移到营业时段：{label(item, facts)}→{found:%H:%M}开始",
                {item.item_id},
            )


def pushes(
    items: Sequence[PlanItem], bad: list[ValidationCheck], facts: Facts
) -> Iterator[Candidate]:
    """路段时间不足：本项及其后同日各项整体后推缺口。"""
    for check in bad:
        i = item_index(check.subject)
        if check.code != "route_gap" or not i or (rid := items[i].route_evidence_id) is None:
            continue
        route = facts.routes.get(rid)
        if route is None or route.minutes is None:
            continue
        shortfall = route.departure + timedelta(minutes=route.minutes) - items[i].start
        delta = timedelta(minutes=5 * ceil(shortfall.total_seconds() / 300))
        tail = [j for j in range(i, len(items)) if day_of(items[j]) == day_of(items[i])]
        if any(items[j].locked for j in tail) or items[tail[-1]].end + delta > at(
            day_of(items[i]), time(23)
        ):
            continue
        moved = [
            item.model_copy(update={"start": item.start + delta, "end": item.end + delta})
            if j in tail
            else item
            for j, item in enumerate(items)
        ]
        yield (
            moved,
            f"后推{delta.total_seconds() / 60:g}分钟以留足路程：{label(items[i], facts)}起",
            {items[j].item_id for j in tail},
        )


def moves(
    items: Sequence[PlanItem], bad: list[ValidationCheck], facts: Facts
) -> Iterator[Candidate]:
    """营业时间无法在当天满足：挪到相邻、仍有空档的旅行日（排在当天末尾）。"""
    for check in bad:
        i = item_index(check.subject)
        if check.code != "opening_hours" or i is None:
            continue
        item, place = items[i], facts.places.get(items[i].place_evidence_id)
        if item.locked or place is None:
            continue
        length = item.end - item.start
        others = [x for j, x in enumerate(items) if j != i]
        for day in sorted(
            (
                d
                for d in (day_of(item) - timedelta(days=1), day_of(item) + timedelta(days=1))
                if d in facts.days
            ),
            key=lambda d: sum(day_of(x) == d for x in others),
        ):
            same = [x.end for x in others if day_of(x) == day]
            start = max(same) + timedelta(minutes=30) if same else at(day, time(9))
            if (
                start + length <= at(day, DAY_END)
                and opening_state(place.opening_hours, start, start + length) == "open"
            ):
                moved = item.model_copy(
                    update={"start": start, "end": start + length, "route_evidence_id": None}
                )
                result = sorted([*others, moved], key=lambda x: x.start)
                yield (
                    result,
                    f"改到{day:%m-%d}：{label(item, facts)}→{start:%H:%M}开始",
                    {item.item_id},
                )


def drops(
    items: Sequence[PlanItem], bad: list[ValidationCheck], facts: Facts
) -> Iterator[Candidate]:
    """最低优先级：重复景点的后一次，其次是涉及冲突、最靠后的项；不删某天仅剩的一项和锁定项。"""
    first: dict[str, int] = {}
    later: set[int] = set()
    for j, item in enumerate(items):
        place = facts.places.get(item.place_evidence_id)
        if place and first.setdefault(place.place_id, j) != j:
            later.add(j)
    involved = {item_index(check.subject) for check in bad} - {None}
    if any(check.code == "repeated_place_warning" for check in bad):
        involved |= later
    for i in sorted(
        (j for j in involved if isinstance(j, int)), key=lambda j: (j not in later, -j)
    ):
        item = items[i]
        if item.locked or sum(day_of(x) == day_of(item) for x in items) < 2:
            continue
        yield (
            [x for j, x in enumerate(items) if j != i],
            f"已去掉{label(item, facts)}，原地无法解决冲突",
            set(),
        )


OPERATORS = (clamp, shifts, pushes, moves, drops)  # 由小到大；去项最后


def core(report: ValidationReport, skip: frozenset[str] | set[str] = frozenset()) -> Counter[str]:
    return Counter(c.code for c in conflicts(report) if c.code not in skip)


async def settle(run: _Run, facts: Facts, validate: Validate, reroute: Reroute) -> None:
    """清除多余路线、重建过期或刚改动处缺失的路线；冲突数不升才采用。"""
    items = list(run.content.items)
    legs: list[int] = []
    for check in conflicts(run.report):
        i = item_index(check.subject)
        if i is None or check.code not in STALE:
            continue
        if check.code == "route_unexpected":
            items[i] = items[i].model_copy(update={"route_evidence_id": None})
        else:
            legs.append(i)
    legs += [
        i
        for i, item in enumerate(items)
        if i
        and item.item_id in run.touched
        and item.route_evidence_id is None
        and day_of(items[i - 1]) == day_of(item)
    ]
    legs = [i for i in dict.fromkeys(legs) if i and items[i - 1].end <= items[i].start]
    built = (
        await reroute(
            [
                (items[i - 1].place_evidence_id, items[i].place_evidence_id, items[i - 1].end)
                for i in legs
            ]
        )
        if legs
        else ()
    )
    for i, (evidence_id, estimate) in zip(legs, built, strict=False):
        facts.routes[evidence_id] = estimate
        items[i] = items[i].model_copy(update={"route_evidence_id": evidence_id})
    content = run.content.model_copy(update={"items": tuple(items)})
    if content == run.content:
        return
    report = await validate(content)
    if core(report).total() <= core(run.report).total():
        run.content, run.report = content, report


async def repair(
    content: PlanContent,
    report: ValidationReport,
    facts: Facts,
    *,
    validate: Validate,
    reroute: Reroute,
) -> Repair:
    """返回冲突不多于输入的最优内容；无法改进则原样返回。"""
    best = _Run(content, report)
    await settle(best, facts, validate, reroute)
    limit = min(MAX_OPS, 3 * max(len(conflicts(report)), 1))
    seen = {fingerprint(best.content)}
    disclosed: list[str] = []
    ops = 0
    while ops < limit and conflicts(best.report):
        progress = False
        bad = conflicts(best.report)
        for operator in OPERATORS:
            for items, note, changed in operator(best.content.items, bad, facts):
                key = fingerprint(best.content.model_copy(update={"items": tuple(items)}))
                if key in seen or ops >= limit:
                    continue
                seen.add(key)
                ops += 1
                trial = _Run(
                    best.content.model_copy(update={"items": tuple(items)}),
                    report,
                    best.touched | changed,
                )
                trial.report = await validate(trial.content)
                # 先按“重建路线即可消除”之外的冲突筛选，避免为注定失败的候选耗路线额度
                if core(trial.report, STALE).total() >= core(best.report, STALE).total() or (
                    core(trial.report, STALE) - core(best.report, STALE)
                ):
                    continue
                await settle(trial, facts, validate, reroute)
                if core(trial.report).total() < core(best.report).total() and not (
                    core(trial.report) - core(best.report)
                ):
                    best, progress = trial, True
                    disclosed.append(note)
                    break
            if progress:
                break
        if not progress:
            break
    pinned = {item.item_id: item for item in content.items if item.locked}
    # 锁定项的时间与内容从不被改；路线引用是派生数据，随前后项变化重建时必须披露。
    disclosed += [
        f"锁定项{label(item, facts)}时间与内容未动，仅更新了路线引用"
        for item in best.content.items
        if item.item_id in pinned
        and item.route_evidence_id != pinned[item.item_id].route_evidence_id
    ]
    return Repair(best.content, best.report, tuple(disclosed))


def fingerprint(content: PlanContent) -> tuple[tuple[object, ...], ...]:
    return tuple((i.item_id, i.start, i.end, i.route_evidence_id) for i in content.items)
