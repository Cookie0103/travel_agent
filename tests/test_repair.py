"""局部修复：每个算子修好自己的场景、不恶化、有上限、去项必披露，用真实校验器作裁判。"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

import pytest

from backend.domain.catalog import Place
from backend.domain.evidence import EvidenceRecord
from backend.domain.itinerary import (
    ItineraryProposal,
    ProposedItem,
    RouteEstimate,
    ValidationReport,
)
from backend.domain.plans import PlanContent, PlanItem, initial_content
from backend.domain.repair import MAX_OPS, Facts, Repair, conflicts, repair
from backend.domain.travel_request import TravelRequest
from backend.domain.validator import validate_itinerary
from tests.test_itinerary import NOW, item, place, record, request

pytestmark = pytest.mark.asyncio

DAYS = (date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5))
D3, D4 = "2026-11-03", "2026-11-04"  # 周二、周三


def trip() -> TravelRequest:
    return TravelRequest.model_validate(
        {
            **request().model_dump(),
            "segments": [
                {"city": "京都", "arrive": D3, "depart": D4},
                {"city": "京都", "arrive": D4, "depart": "2026-11-05"},
            ],
        }
    )


class Scene:
    """真实校验器 + 内存证据；reroute用固定耗时的假路线并统计调用。"""

    def __init__(self, minutes: int = 10) -> None:
        self.request, self.minutes = trip(), minutes
        self.records: dict[UUID, EvidenceRecord] = {}
        self.places: dict[UUID, Place] = {}
        self.routes: dict[UUID, RouteEstimate] = {}
        self.validations = self.reroutes = 0

    def spot(self, n: int, hours: str = "24/7", category: str = "temple") -> EvidenceRecord:
        base = place().model_copy(
            update={
                "place_id": f"t:{n}",
                "name": f"景点{n}",
                "opening_hours": hours,
                "category": category,
                "city": "京都",
            }
        )
        rec = record(base, self.request)
        self.records[rec.evidence_id], self.places[rec.evidence_id] = rec, base
        return rec

    def route(
        self, a: EvidenceRecord, b: EvidenceRecord, at: str, minutes: int | None = None
    ) -> EvidenceRecord:
        estimate = RouteEstimate(
            from_place_id=self.places[a.evidence_id].place_id,
            to_place_id=self.places[b.evidence_id].place_id,
            transport="walk",
            departure=datetime.fromisoformat(at),
            minutes=self.minutes if minutes is None else minutes,
            confidence="estimate",
        )
        rec = record(estimate, self.request)
        self.records[rec.evidence_id], self.routes[rec.evidence_id] = rec, estimate
        return rec

    def content(self, *items: ProposedItem) -> PlanContent:
        return initial_content(ItineraryProposal(expected_revision=1, items=tuple(items)))

    async def validate(self, content: PlanContent) -> ValidationReport:
        self.validations += 1
        proposal = content.proposal(1)
        wanted = [self.records[i] for i in proposal.evidence_ids()]
        return validate_itinerary(self.request, proposal, tuple(wanted), NOW)

    async def reroute(
        self, legs: Sequence[tuple[UUID, UUID, datetime]]
    ) -> list[tuple[UUID, RouteEstimate]]:
        self.reroutes += len(legs)
        built = []
        for a, b, departure in legs:
            rec = self.route(self.records[a], self.records[b], departure.isoformat())
            built.append((rec.evidence_id, self.routes[rec.evidence_id]))
        return built

    async def run(self, content: PlanContent) -> tuple[Repair, ValidationReport]:
        before = await self.validate(content)
        facts = Facts(self.places, dict(self.routes), DAYS)
        return await repair(
            content, before, facts, validate=self.validate, reroute=self.reroute
        ), before


def codes(report: ValidationReport) -> list[str]:
    """冲突code；场景没有酒店，固定的hotel_stay_missing与行程修复无关，不计入。"""
    return [c.code for c in conflicts(report) if c.code != "hotel_stay_missing"]


def by_index(content: PlanContent) -> list[PlanItem]:
    return list(content.items)


async def test_opening_hours_conflict_is_fixed_by_shifting_within_the_same_day() -> None:
    scene = Scene()
    shrine = scene.spot(1, "Mo-Su 09:00-17:00")
    content = scene.content(item(shrine, f"{D3}T18:00+09:00", f"{D3}T19:00+09:00"))
    fixed, before = await scene.run(content)
    assert "opening_hours" in codes(before) and "opening_hours" not in codes(fixed.report)
    moved = fixed.content.items[0]
    assert moved.end - moved.start == timedelta(hours=1) and moved.start.hour <= 16
    assert moved.start.date() == date(2026, 11, 3) and len(fixed.content.items) == 1
    assert any("平移" in note for note in fixed.disclosed)


async def test_unfixable_closure_returns_the_input_unchanged_within_the_bound() -> None:
    scene = Scene()
    closed = scene.spot(1, "Mo-Su off")
    content = scene.content(item(closed, f"{D3}T10:00+09:00", f"{D3}T11:00+09:00"))
    fixed, before = await scene.run(content)
    assert fixed.content == content and fixed.report == before and fixed.disclosed == ()
    assert scene.validations <= 1 + 1 + MAX_OPS  # 初始、settle之外最多MAX_OPS次尝试


async def test_extreme_visit_duration_is_clamped_into_the_range() -> None:
    scene = Scene()
    temple = scene.spot(1)
    content = scene.content(item(temple, f"{D3}T10:00+09:00", f"{D3}T10:01+09:00"))
    fixed, before = await scene.run(content)
    assert "visit_duration_range" in codes(before)
    assert "visit_duration_range" not in codes(fixed.report)
    assert fixed.content.items[0].end - fixed.content.items[0].start >= timedelta(minutes=20)


async def test_route_gap_pushes_the_item_and_later_items_and_rebuilds_their_routes() -> None:
    scene = Scene()
    a, b, c = scene.spot(1), scene.spot(2), scene.spot(3)
    ab = scene.route(a, b, f"{D3}T11:00+09:00", minutes=60)
    bc = scene.route(b, c, f"{D3}T13:00+09:00", minutes=10)
    content = scene.content(
        item(a, f"{D3}T10:00+09:00", f"{D3}T11:00+09:00"),
        item(b, f"{D3}T11:30+09:00", f"{D3}T13:00+09:00", ab),
        item(c, f"{D3}T14:00+09:00", f"{D3}T15:00+09:00", bc),
    )
    scene.records |= {}  # 路线证据已登记
    fixed, before = await scene.run(content)
    assert "route_gap" in codes(before) and not codes(fixed.report)
    starts = [i.start for i in fixed.content.items]
    assert starts[1] - content.items[1].start == timedelta(minutes=30)  # 恰为缺口
    assert starts[2] - content.items[2].start == timedelta(minutes=30)
    assert fixed.content.items[2].route_evidence_id != bc.evidence_id  # 后续路段已重建
    assert scene.reroutes >= 1


async def test_item_moves_to_an_adjacent_day_when_its_own_day_cannot_work() -> None:
    scene = Scene()
    other, wednesday_only = scene.spot(1), scene.spot(2, "We 09:00-17:00")
    content = scene.content(
        item(other, f"{D3}T09:00+09:00", f"{D3}T10:00+09:00"),
        item(wednesday_only, f"{D3}T12:00+09:00", f"{D3}T13:00+09:00"),
    )
    fixed, before = await scene.run(content)
    assert "opening_hours" in codes(before) and "opening_hours" not in codes(fixed.report)
    moved = next(
        i for i in fixed.content.items if i.place_evidence_id == wednesday_only.evidence_id
    )
    assert moved.start.date() == date(2026, 11, 4)
    assert any("改到11-04" in note for note in fixed.disclosed)


async def test_repeated_place_drops_the_later_visit_and_discloses_it() -> None:
    scene = Scene()
    a, b, c = scene.spot(1), scene.spot(2), scene.spot(3)
    content = scene.content(
        item(a, f"{D3}T10:00+09:00", f"{D3}T11:00+09:00"),
        item(b, f"{D3}T13:00+09:00", f"{D3}T14:00+09:00"),
        item(a, f"{D4}T10:00+09:00", f"{D4}T11:00+09:00"),
        item(c, f"{D4}T13:00+09:00", f"{D4}T14:00+09:00"),
    )
    fixed, before = await scene.run(content)
    assert "repeated_place_warning" in codes(before)
    assert "repeated_place_warning" not in codes(fixed.report)
    kept = {i.place_evidence_id for i in fixed.content.items}
    assert kept == {a.evidence_id, b.evidence_id, c.evidence_id}  # 不新增景点
    assert len(fixed.content.items) == 3 and any("已去掉「景点1」" in n for n in fixed.disclosed)


async def test_lone_item_of_a_day_and_locked_items_are_never_dropped() -> None:
    scene = Scene()
    a = scene.spot(1)
    lone = scene.content(
        item(a, f"{D3}T10:00+09:00", f"{D3}T11:00+09:00"),
        item(a, f"{D4}T10:00+09:00", f"{D4}T11:00+09:00"),
    )
    fixed, _ = await scene.run(lone)
    assert fixed.content == lone and fixed.disclosed == ()  # 各天仅一项，去掉会空出一天
    two_a_day = scene.content(
        item(a, f"{D3}T10:00+09:00", f"{D3}T11:00+09:00"),
        item(scene.spot(2), f"{D3}T13:00+09:00", f"{D3}T14:00+09:00"),
        item(a, f"{D4}T10:00+09:00", f"{D4}T11:00+09:00"),
        item(scene.spot(3), f"{D4}T13:00+09:00", f"{D4}T14:00+09:00"),
    )
    locked = two_a_day.model_copy(
        update={
            "items": tuple(
                i.model_copy(update={"locked": n == 2}) for n, i in enumerate(two_a_day.items)
            )
        }
    )
    fixed, _ = await scene.run(locked)
    assert fixed.content == locked and fixed.disclosed == ()


async def test_stale_routes_are_cleared_or_rebuilt_without_touching_times() -> None:
    scene = Scene()
    a, b, c = scene.spot(1), scene.spot(2), scene.spot(3)
    early = scene.route(a, b, f"{D3}T10:00+09:00")  # 出发早于前一项结束：过期
    first_of_day = scene.route(a, b, f"{D4}T09:00+09:00")  # 当天首项不该带路段
    content = scene.content(
        item(a, f"{D3}T10:30+09:00", f"{D3}T11:00+09:00"),
        item(b, f"{D3}T12:00+09:00", f"{D3}T13:00+09:00", early),
        item(c, f"{D4}T10:00+09:00", f"{D4}T11:00+09:00", first_of_day),
    )
    fixed, before = await scene.run(content)
    assert {"route_departure", "route_unexpected"} <= set(codes(before))
    assert not codes(fixed.report) and scene.reroutes == 1  # 只重建一段，另一段直接清除
    assert [(i.start, i.end) for i in fixed.content.items] == [
        (i.start, i.end) for i in content.items
    ]
    assert fixed.content.items[2].route_evidence_id is None and fixed.disclosed == ()


async def test_exhausted_route_budget_leaves_stale_routes_without_failing() -> None:
    scene = Scene()
    a, b = scene.spot(1), scene.spot(2)
    early = scene.route(a, b, f"{D3}T10:00+09:00")
    content = scene.content(
        item(a, f"{D3}T10:30+09:00", f"{D3}T11:00+09:00"),
        item(b, f"{D3}T12:00+09:00", f"{D3}T13:00+09:00", early),
    )

    async def no_budget(
        legs: Sequence[tuple[UUID, UUID, datetime]],
    ) -> list[tuple[UUID, RouteEstimate]]:
        return []

    before = await scene.validate(content)
    fixed = await repair(
        content,
        before,
        Facts(scene.places, dict(scene.routes), DAYS),
        validate=scene.validate,
        reroute=no_budget,
    )
    assert fixed.content == content and fixed.report == before


@pytest.mark.parametrize("seed", range(3))
async def test_repair_never_increases_conflicts_and_stays_bounded(seed: int) -> None:
    scene = Scene()
    spots = [scene.spot(n, hours) for n, hours in enumerate(["We 09:00-17:00", "off", "24/7"])]
    rows = [
        item(
            spots[(n + seed) % 3],
            f"{D3}T{9 + 3 * n:02d}:00+09:00",
            f"{D3}T{10 + 3 * n:02d}:00+09:00",
        )
        for n in range(3)
    ]
    fixed, before = await scene.run(scene.content(*rows))
    assert len(codes(fixed.report)) <= len(codes(before))
    assert scene.validations <= 2 + MAX_OPS * 2
