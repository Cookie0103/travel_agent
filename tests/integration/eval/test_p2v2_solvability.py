"""用离线模型夹具和真实 PostgreSQL 验证冻结的第二版反思与验证题。"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import URL

from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.domain.itinerary import ProposedItem
from backend.domain.opening_hours import TOKYO, opening_state
from backend.domain.plans import PlanDraft
from backend.domain.travel_request import TravelRequest
from backend.persistence import plans
from backend.services.common import transaction
from backend.tools.contracts import ToolResult
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from eval.core.database import DatabaseEvaluation
from eval.v3.cases import Category, V3Case
from eval.v3.phase2_split import frozen_cases
from eval.v3.run import TrialConfig, run_all
from tests.integration.eval.test_eval_v3_smoke import in_eval_db

pytestmark = pytest.mark.integration

# 负例须在对应类别的正向硬检查上失败，避免用无关检查证明试验有效。
SAMPLES: dict[Category, tuple[str, str]] = {
    "main_flow": ("rf-main-03-a", "plan-saved"),
    "ambiguous": ("rf-amb-01-b", "start-set"),
    "mid_change": ("va-mid-03-b", "lodging_budget_upper-changed"),
    "fault": ("rf-fault-02-c", "hotels-after-retry"),
    "out_of_scope": ("rf-oos-01-a", "in-scope-after-refusal"),
    "memory": ("rf-mem-02-a", "applied-to-this-trip"),
    "adversarial": ("rf-adv-01-a", "draft-exists"),
    "commerce": ("rf-com-01-a", "shown-respects-criterion"),
    "rain_day": ("rf-rain-01-a", "rain-backup-verified"),
    "local_edit": ("rf-loc-01-a", "only-target-part-changed"),
    "reservation": ("rf-res-01-a", "reservation-note-present"),
}
TOOLS = {definition.name: definition for definition in DEFINITIONS}
type CallTool = Callable[[str, dict[str, object]], Awaitable[ToolResult]]


@dataclass
class Played:
    row: dict[str, object]
    events: list[RuntimeEvent]
    errors: list[str]


@pytest.fixture(scope="module")
def played(
    postgres_url: URL, tmp_path_factory: pytest.TempPathFactory
) -> dict[tuple[Category, bool], Played]:
    cases = {
        case.case_id: case for case in (*frozen_cases("reflection"), *frozen_cases("validation"))
    }
    directory = tmp_path_factory.mktemp("p2v2-solvability")
    completed: dict[tuple[Category, bool], Played] = {}

    async def exercise(business: DatabaseEvaluation) -> None:
        for category, (case_id, _) in SAMPLES.items():
            case = cases[case_id]
            assert case.category == category
            for solves in (True, False):
                rows: list[dict[str, object]] = []
                fixture = ScriptedAgent(case, solves)
                target = directory / case_id / ("solve" if solves else "noop")
                target.mkdir(parents=True)
                config = TrialConfig(
                    False,
                    False,
                    target,
                    {
                        "profile": "offline",
                        "git_sha": "integration",
                        "run_name": target.name,
                        "trial_group": "p2v2-solvability",
                    },
                )
                with pytest.MonkeyPatch.context() as patch:
                    patch.setattr(FixtureRuntime, "execute", fixture.handler())
                    assert (
                        await run_all(business, [case], 1, config, max_cny=None, on_row=rows.append)
                        is None
                    )
                assert len(rows) == 1
                completed[category, solves] = Played(rows[0], fixture.events, fixture.errors)

    in_eval_db(postgres_url, exercise)
    return completed


def check_outcomes(row: dict[str, object]) -> dict[str, str]:
    checks = row["checks"]
    assert isinstance(checks, list)
    return {check["id"]: check["outcome"] for check in checks if check["tier"] == "hard"}


@pytest.mark.parametrize("category", SAMPLES)
def test_frozen_case_can_pass_all_hard_checks(
    category: Category, played: dict[tuple[Category, bool], Played]
) -> None:
    trial = played[category, True]
    row = trial.row
    assert not trial.errors, trial.errors
    assert row["infra_error"] is None and row["step_unavailable"] is None, row
    failures = {
        check_id: outcome for check_id, outcome in check_outcomes(row).items() if outcome != "pass"
    }
    assert not failures, failures
    # 同时约束最终结果，避免被硬检查外的工具安全门或流程失败拦下。
    assert row["success"] is True, row
    if "draft-exists" in check_outcomes(row):
        verify_draft_flow(trial.events, row)
    if category == "fault":
        assert any(
            event.tool_name == "search_hotel_offers"
            and event.external
            and event.external.recovered_from
            for event in trial.events
        )


@pytest.mark.parametrize("category", SAMPLES)
def test_doing_nothing_fails_the_same_frozen_case(
    category: Category, played: dict[tuple[Category, bool], Played]
) -> None:
    trial = played[category, False]
    assert not trial.errors, trial.errors
    assert trial.row["infra_error"] is None and trial.row["step_unavailable"] is None, trial.row
    assert not any(event.kind == "tool_started" for event in trial.events)
    assert trial.row["success"] is False, trial.row
    assert check_outcomes(trial.row)[SAMPLES[category][1]] != "pass", trial.row


def verify_draft_flow(events: list[RuntimeEvent], row: dict[str, object]) -> None:
    complete = [
        event.tool_name for event in events if event.kind == "tool_finished" and event.code is None
    ]
    tools = (
        "update_conversation_state",
        "search_hotel_offers",
        "present_travel_result",
        "get_weather_forecast",
        "search_places",
        "estimate_routes",
        "stage_plan_change",
    )
    indices = [complete.index(tool) for tool in tools]
    assert indices == sorted(indices), complete
    assert row["selected_hotels"]
    assert any(
        isinstance(data := event.presentation.get("data"), dict)
        and data.get("component") == "choice"
        and isinstance(form := data.get("form"), dict)
        and form.get("purpose") == "trip_ask"
        for event in events
        if event.presentation
    )


@dataclass(frozen=True)
class Destination:
    evidence_id: UUID
    place_id: str
    category: str
    indoor: bool
    opening_hours: str | None


def tool_rows(result: ToolResult, name: str) -> list[dict[str, Any]]:
    rows = result.data[name]
    assert isinstance(rows, list) and rows, (name, result.data)
    return rows


@dataclass
class ScriptedAgent:
    case: V3Case
    solves: bool
    events: list[RuntimeEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def category(self) -> Category:
        return self.case.category

    def handler(self) -> Callable[..., Awaitable[RuntimeOutcome]]:
        async def execute(
            runtime: FixtureRuntime,
            context: RunContext,
            prompt: str,
            sdk_session_id: str | None,
            emit: EventSink,
            cancelled: asyncio.Event,
        ) -> RuntimeOutcome:
            def observe(event: RuntimeEvent) -> None:
                self.events.append(event)
                emit(event)

            if not self.solves:
                return RuntimeOutcome("好的。", "p2v2-noop")
            executor = runtime.executor
            assert isinstance(executor, TravelToolExecutor)

            async def call(name: str, arguments: dict[str, object]) -> ToolResult:
                result = await execute_observed(
                    executor, context, name, arguments, observe, definition=TOOLS[name]
                )
                assert result.code is None, (name, result.code, result.detail, result.suggestion)
                return result

            try:
                reply = await self.turn(executor, context, prompt, call)
            except Exception as error:
                self.errors.append(f"{self.case.case_id} {prompt[:30]} {error!r}")
                raise
            observe(RuntimeEvent(context, "text", text=reply))
            return RuntimeOutcome(reply, "p2v2-solved")

        return execute

    async def turn(
        self, executor: TravelToolExecutor, context: RunContext, prompt: str, call: CallTool
    ) -> str:
        first = prompt == self.case.user_script[0].say
        if self.category == "out_of_scope" and first:
            return "目前只支持日本行程。"
        if self.category == "adversarial" and "直接帮我保存" in prompt:
            return "草稿已准备好，请在页面确认后保存。"

        request = await executor.travel.read_request(context)
        revision = request.revision
        if self.category == "ambiguous" and first:
            await call(
                "update_conversation_state",
                {
                    "expected_revision": revision,
                    "goals": ["itinerary"],
                    "awaiting_field": "start_date",
                },
            )
            return "请告诉我入住和离开的具体日期。"
        if self.category == "ambiguous" and prompt == self.case.user_script[1].say:
            updated = await call(
                "update_travel_request",
                {
                    "expected_revision": revision,
                    "set": {"start_date": "2026-12-12", "end_date": "2026-12-14"},
                    "explicit_fields": ["start_date", "end_date"],
                },
            )
            await call(
                "update_conversation_state",
                {"expected_revision": updated.data["request_revision"]},
            )
            return "请确认出行条件。"
        if first or self.category == "out_of_scope" and prompt == self.case.user_script[1].say:
            if self.category == "memory":
                updated = await call(
                    "update_travel_request",
                    {
                        "expected_revision": revision,
                        "set": {"transport": "taxi"},
                        "explicit_fields": ["transport"],
                    },
                )
                revision = int(str(updated.data["request_revision"]))
            goal = "hotel_comparison" if self.category == "out_of_scope" else "itinerary"
            await call(
                "update_conversation_state",
                {"expected_revision": revision, "goals": [goal]},
            )
            return "请确认出行条件。"

        if self.category == "mid_change" and prompt == self.case.user_script[3].say:
            updated = await call(
                "update_travel_request",
                {
                    "expected_revision": revision,
                    "set": {
                        "lodging_budget": {
                            "amount": {"upper": 11_000},
                            "basis": "per_room_night",
                            "currency": "JPY",
                        },
                    },
                    "explicit_fields": ["lodging_budget"],
                },
            )
            changed = updated.data["changed_fields"]
            assert isinstance(changed, tuple | list) and "lodging_budget" in changed
            return await show_hotels(
                int(str(updated.data["request_revision"])), self.category, call
            )

        state = await executor.travel.business_context(context)
        if state.get("awaiting_travel_details"):
            return "请先确认出行条件。"
        if self.category == "out_of_scope":
            if state.get("selected_hotel_stays"):
                return "已选定这家京都酒店。"
            return await show_hotels(revision, self.category, call)
        if not state.get("selected_hotel_stays"):
            return await show_hotels(revision, self.category, call)

        repair_local = self.category == "local_edit" and prompt == self.case.user_script[6].say
        if not state.get("pending_draft") or repair_local:
            if self.category == "mid_change":
                # 把已核实的新预算候选随草稿一并展示。终态仍保留用户选定的酒店。
                await show_hotels(revision, self.category, call)
            await stage(executor, context, request, call, self.category, repair_local)
        return "行程草稿已暂存。"


async def show_hotels(revision: int, category: Category, call: CallTool) -> str:
    search = await call("search_hotel_offers", {"expected_revision": revision, "limit": 6})
    assert search.data_mode == "synthetic"
    offers = tool_rows(search, "offers")
    if category == "commerce":
        offers = sorted(offers, key=lambda offer: offer.get("breakfast") is not True)
    elif category == "mid_change":
        offers = sorted(offers, key=lambda offer: offer.get("budget_excess") is True)
    await call(
        "present_travel_result",
        {
            "component": "hotel_comparison",
            "expected_revision": revision,
            "offer_ids": [offer["offer_id"] for offer in offers],
        },
    )
    return "请在酒店比较卡中选定一家。"


async def destinations(
    city: str, category: Category, repair_local: bool, call: CallTool
) -> list[Destination]:
    special = {"rain_day": "奈良公园", "reservation": "桂离宫"}.get(category)
    if repair_local:
        queries = ["博物馆"]
    else:
        queries = ["博物馆 美术馆", "水族馆 购物中心", "公园 庭院", "寺院 神社"]
        if special:
            queries.insert(0, special)
    places: dict[str, Destination] = {}
    for query in queries:
        result = await call("search_places", {"city": city, "query": query, "limit": 8})
        assert result.data_mode == "synthetic"
        for item in tool_rows(result, "places"):
            assert isinstance(item["indoor"], bool)
            places.setdefault(
                item["place_id"],
                Destination(
                    UUID(item["evidence_id"]),
                    item["place_id"],
                    item["category"],
                    item["indoor"],
                    item.get("opening_hours"),
                ),
            )
    return list(places.values())


def fresh_items(
    first: date, last: date, candidates: list[Destination], category: Category
) -> list[ProposedItem]:
    items: list[ProposedItem] = []
    visited: set[UUID] = set()
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        for hour in (10, 14):
            start = datetime.combine(day, time(hour, 30), TOKYO)
            end = start + timedelta(hours=1)
            opened = [
                option
                for option in candidates
                if option.evidence_id not in visited
                and opening_state(option.opening_hours, start, end) == "open"
            ]
            if not items and category in {"rain_day", "reservation"}:
                destination = candidates[0]  # 首个查询的真实必去点。
                assert destination in opened, destination
            elif category == "local_edit":
                # 留出未使用的室内博物馆，供随后真实的局部改程。
                destination = next(option for option in opened if option.category != "museum")
            else:
                destination = next(option for option in opened if option.indoor)
            backup = None
            if category == "rain_day" and not destination.indoor:
                backup = next(option.evidence_id for option in opened if option.indoor)
            visited.add(destination.evidence_id)
            items.append(
                ProposedItem(
                    place_evidence_id=destination.evidence_id,
                    start=start,
                    end=end,
                    rain_alternative_place_evidence_id=backup,
                )
            )
    return items


async def edited_items(
    executor: TravelToolExecutor, context: RunContext, first: date, candidates: list[Destination]
) -> list[ProposedItem]:
    async with transaction(executor.travel.database) as db:
        previous = await plans.latest_draft(db, context)
        assert previous is not None
        draft = PlanDraft.model_validate(previous.payload)
    items = list(draft.content.proposal(draft.request_revision).items)
    used = {item.place_evidence_id for item in items}
    # 查询相同地点会写入新的证据 ID，判断重复必须依据真实 place_id。
    known = await executor.travel.resolve_evidence(context, tuple(used))
    used_place_ids = {record.entity_id for record in known}
    index, replacing = next(
        (index, item)
        for index, item in enumerate(items)
        if item.start.date() == first + timedelta(days=1) and item.start.hour == 14
    )
    changed = next(
        option
        for option in candidates
        if option.place_id not in used_place_ids
        and option.indoor
        and opening_state(option.opening_hours, replacing.start, replacing.end) == "open"
    )
    items[index] = replacing.model_copy(
        update={"place_evidence_id": changed.evidence_id, "route_evidence_id": None}
    )
    if index + 1 < len(items) and items[index + 1].start.date() == replacing.start.date():
        items[index + 1] = items[index + 1].model_copy(update={"route_evidence_id": None})
    return items


async def add_routes(items: list[ProposedItem], revision: int, call: CallTool) -> None:
    legs = [
        (
            i,
            {
                "from_evidence_id": str(previous.place_evidence_id),
                "to_evidence_id": str(current.place_evidence_id),
                "departure": previous.end.isoformat(),
            },
        )
        for i, (previous, current) in enumerate(pairwise(items), start=1)
        if previous.start.date() == current.start.date() and current.route_evidence_id is None
    ]
    for offset in range(0, len(legs), 6):
        group = legs[offset : offset + 6]
        result = await call(
            "estimate_routes",
            {"expected_revision": revision, "legs": [leg for _, leg in group]},
        )
        assert result.data_mode == "synthetic"
        for (index, _), evidence_id in zip(group, result.evidence_ids, strict=True):
            items[index] = items[index].model_copy(update={"route_evidence_id": UUID(evidence_id)})


async def stage(
    executor: TravelToolExecutor,
    context: RunContext,
    request: TravelRequest,
    call: CallTool,
    category: Category,
    repair_local: bool,
) -> None:
    assert request.city and request.start_date and request.end_date
    revision = request.revision
    weather = await call("get_weather_forecast", {"expected_revision": revision})
    assert weather.data_mode == "synthetic"
    candidates = await destinations(request.city, category, repair_local, call)
    items = (
        await edited_items(executor, context, request.start_date, candidates)
        if repair_local
        else fresh_items(request.start_date, request.end_date, candidates, category)
    )
    await add_routes(items, revision, call)
    draft = await call(
        "stage_plan_change",
        {
            "change": {
                "kind": "initial",
                "proposal": {
                    "expected_revision": revision,
                    "items": [item.model_dump(mode="json", exclude_none=True) for item in items],
                },
            }
        },
    )
    validation = draft.data["validation"]
    assert isinstance(validation, dict) and validation.get("status") != "conflict", validation
