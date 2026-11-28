"""第二阶段六城的业务链，对既有 v3 多轮入口使用离线夹具。"""

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import URL

from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.opening_hours import opening_state
from backend.domain.travel_request import pace_of
from backend.tools.contracts import ToolResult
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from eval.core.database import DatabaseEvaluation
from eval.core.evaluation_world import phase2_world
from eval.v3.report import write_reports
from eval.v3.run import TrialConfig, run_all
from tests.integration.eval.test_eval_v3_smoke import REQUEST, in_eval_db, make

pytestmark = pytest.mark.integration


def test_world_runs_ask_select_and_stage_in_all_six_cities(
    postgres_url: URL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_day = date(2026, 11, 3)
    days = [first_day + timedelta(days=offset) for offset in range(4)]
    world = phase2_world(weather_by_date={day: "sunny" for day in days})
    monkeypatch.setattr("eval.v3.run.phase2_world", lambda: world)

    async def scripted(
        runtime: FixtureRuntime,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        executor = runtime.executor
        assert isinstance(executor, TravelToolExecutor)
        request = await executor.travel.read_request(context)
        revision = request.revision

        async def tool(name: str, arguments: dict[str, object]) -> ToolResult:
            result = await execute_observed(
                executor,
                context,
                name,
                arguments,
                emit,
                definition=next(
                    definition for definition in DEFINITIONS if definition.name == name
                ),
            )
            assert result.code is None, (name, result.code)
            return result

        if prompt == "请安排三晚旅行":
            await tool(
                "update_conversation_state", {"expected_revision": revision, "goals": ["itinerary"]}
            )
        elif (await executor.travel.business_context(context)).get("requires_hotel_selection"):
            found = await tool("search_hotel_offers", {"expected_revision": revision, "limit": 3})
            offers = found.data["offers"]
            assert isinstance(offers, list) and offers
            await tool(
                "present_travel_result",
                {
                    "component": "hotel_comparison",
                    "expected_revision": revision,
                    "offer_ids": [offer["offer_id"] for offer in offers],
                },
            )
        else:
            assert pace_of(request) == "标准"
            assert request.start_date == days[0] and request.end_date == days[-1]
            await tool("get_weather_forecast", {"expected_revision": revision})
            places: dict[str, tuple[str, str | None]] = {}
            for query in ("博物馆 美术馆", "公园 庭院", "水族馆 动物园", "观景点 购物中心"):
                found = await tool(
                    "search_places", {"city": request.city, "query": query, "limit": 8}
                )
                assert found.evidence_ids and found.data_mode == "synthetic"
                rows = found.data.get("places")
                assert isinstance(rows, list)
                for place in rows:
                    assert isinstance(place["indoor"], bool)
                    places[place["place_id"]] = (place["evidence_id"], place["opening_hours"])

            items = []
            used: set[str] = set()
            hours = ("09:00", "11:30", "14:30", "17:00")
            for offset, day in enumerate(days):
                count = 4 if offset in (1, 2) else 2
                for hour in hours[:count]:
                    start = datetime.fromisoformat(f"{day}T{hour}+09:00")
                    end = start + timedelta(hours=1)
                    identity, evidence_id = next(
                        (identity, reference)
                        for identity, (reference, opening) in places.items()
                        if identity not in used and opening_state(opening, start, end) == "open"
                    )
                    used.add(identity)
                    items.append(
                        {
                            "place_evidence_id": evidence_id,
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                        }
                    )
            draft = await tool(
                "stage_plan_change",
                {
                    "change": {
                        "kind": "initial",
                        "proposal": {"expected_revision": revision, "items": items},
                    },
                },
            )
            validation = draft.data["validation"]
            assert isinstance(validation, dict)
            assert validation["status"] in {"complete", "partial"}, validation
            assert not draft.data.get("repairs")
            saved = await executor.plans.get_draft(
                context.user_id, UUID(str(draft.data["draft_id"]))
            )
            cards = saved["cards"]
            assert isinstance(cards, list)
            assert len(cards) == len({card["name"] for card in cards}) == len(items) == 12
        return RuntimeOutcome("夹具步骤完成", "fixture-world")

    monkeypatch.setattr(FixtureRuntime, "execute", scripted)

    async def exercise(business: DatabaseEvaluation) -> None:
        cases = [
            make(
                case_id=f"world-city-{index}",
                seed_id="world-smoke" if index == 0 else None,
                fault="429-ok" if index == 0 else None,
                world=None if index == 0 else "phase2",
                setup={
                    "request": {
                        **REQUEST,
                        "city": city.city,
                        "start_date": days[0].isoformat(),
                        "end_date": days[-1].isoformat(),
                        "child_ages": [5] if index == 0 else [],
                        "lodging_budget": None,
                        "lodging_budget_unlimited": True,
                    }
                },
                user_script=[
                    {"say": "请安排三晚旅行"},
                    {
                        "card": {
                            "kind": "trip_ask",
                            "option": "confirm",
                            "answers": {"pace": ["standard"]},
                        }
                    },
                    {"hotel_pick": {"rank": "first"}},
                ],
                hard_checks=[
                    {"id": "selected", "type": "db", "assert": "hotel_selected", "segments": 1},
                    {"id": "draft", "type": "db", "assert": "draft_no_conflict"},
                ],
            )
            for index, city in enumerate(world.cities)
        ]
        config = TrialConfig(
            False,
            False,
            tmp_path,
            {"profile": "offline", "git_sha": "smoke", "run_name": "smoke", "trial_group": "smoke"},
        )
        rows: list[dict[str, object]] = []
        assert await run_all(business, cases, 1, config, max_cny=None, on_row=rows.append) is None
        assert len(rows) == 6
        assert all(row["success"] for row in rows), [
            (row["case_id"], row["reason"], row["infra_error"]) for row in rows
        ]
        assert all(row["hotel_presentations"] and row["selected_hotels"] for row in rows)
        summary = write_reports(tmp_path, dict(config.meta), rows, 1, None)
        sheets = [row["commerce"] for row in rows]
        assert all(isinstance(sheet, dict) and sheet["groups"] for sheet in sheets), sheets
        commerce = summary["commerce"]
        assert isinstance(commerce, dict) and commerce["expected_score_jpy"] > 0
        assert (tmp_path / "report.md").is_file()

    in_eval_db(postgres_url, exercise)
