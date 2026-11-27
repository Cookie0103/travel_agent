"""第二阶段六城的业务链，对既有 v3 多轮入口使用离线夹具。"""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import URL

from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.tools.contracts import ToolResult
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from eval.core.database import DatabaseEvaluation
from eval.core.evaluation_world import phase2_world
from eval.v3.run import TrialConfig, run_all
from tests.integration.eval.test_eval_v3_smoke import REQUEST, in_eval_db, make

pytestmark = pytest.mark.integration


def test_world_runs_ask_select_and_stage_in_all_six_cities(
    postgres_url: URL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = phase2_world()

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

        if prompt == "请安排两天旅行":
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
            found = await tool(
                "search_places", {"city": request.city, "query": "", "indoor": True, "limit": 2}
            )
            assert found.evidence_ids and found.data_mode == "synthetic"
            assert request.start_date
            await tool(
                "stage_plan_change",
                {
                    "change": {
                        "kind": "initial",
                        "proposal": {
                            "expected_revision": revision,
                            "items": [
                                {
                                    "place_evidence_id": found.evidence_ids[0],
                                    "start": f"{request.start_date}T14:00+09:00",
                                    "end": f"{request.start_date}T15:30+09:00",
                                }
                            ],
                        },
                    },
                },
            )
        return RuntimeOutcome("夹具步骤完成", "fixture-world")

    monkeypatch.setattr(FixtureRuntime, "execute", scripted)

    async def exercise(business: DatabaseEvaluation) -> None:
        cases = [
            make(
                case_id=f"world-city-{index}",
                world="phase2",
                setup={
                    "request": {
                        **REQUEST,
                        "city": city.city,
                        "lodging_budget": None,
                        "lodging_budget_unlimited": True,
                    }
                },
                user_script=[
                    {"say": "请安排两天旅行"},
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

    in_eval_db(postgres_url, exercise)
