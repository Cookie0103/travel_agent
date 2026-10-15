"""F4：合成三城资料经真实选择/校验/暂存生成全日期草稿，不宣称模型效果。"""

import asyncio
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import URL

from backend.adapters.evaluation_faults import evaluation_data
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.itinerary import HotelStay, ItineraryProposal
from backend.domain.plans import StageInput
from backend.persistence import runs
from backend.persistence.temporary import temporary_database
from backend.services.common import transaction
from backend.services.planning import PlanningService
from backend.services.plans import PlanService
from backend.services.runs import MessageInput, RunService
from backend.tools.travel import TravelToolExecutor
from eval.cases import Case
from eval.database import database_evaluation
from tests.integration.test_runs import WaitingRuntime

pytestmark = pytest.mark.integration


def test_three_city_synthetic_inventory_supports_a_full_date_draft(postgres_url: URL) -> None:
    async def exercise(url: URL) -> None:
        async with database_evaluation(url) as business:
            cities = ("京都", "大阪", "奈良")
            segments = [
                {"city": city, "arrive": f"2026-11-0{i + 3}", "depart": f"2026-11-0{i + 4}"}
                for i, city in enumerate(cities)
            ]
            case = Case(
                case_id="three-city-fixture",
                source="self authored fixture control",
                adaptation="data feasibility only",
                input="比较三城",
                allowed_tools=["search_places", "search_hotel_offers"],
                required_tools=["search_places", "search_hotel_offers"],
                should_have_results=True,
                external_fault="coverage",
                initial_state={
                    "request": {
                        "city": "京都",
                        "start_date": "2026-11-03",
                        "end_date": "2026-11-06",
                        "segments": segments,
                        "adults": 2,
                        "child_ages": [],
                        "rooms": 1,
                        "currency": "JPY",
                        "transport": "walk",
                        "lodging_budget_unlimited": True,
                        "soft_constraints": ["节奏：标准"],
                        "hard_constraints": ["住宿：独立房间", "房型：禁烟", "床型：无要求"],
                    }
                },
            )
            context = await business.prepare(case)
            request = await business.travel.get_request(context)
            executor = TravelToolExecutor(business.travel)
            place_ids: dict[str, tuple[str, ...]] = {}
            stays = []
            for index, (city, segment) in enumerate(zip(cities, segments, strict=True)):
                if index:
                    async with transaction(business.travel.database) as db:
                        await runs.finish(db, context, RuntimeOutcome(text="本城市资料已展示"))
                        next_run = await runs.create(
                            db,
                            context.user_id,
                            context.session_id,
                            uuid4(),
                            f"继续查询{city}",
                            "offline",
                        )
                    context = RunContext(context.user_id, context.session_id, next_run.id)
                    await business.travel.close_data()
                    business.travel.live = evaluation_data(
                        "coverage", business.travel.database, business.dsn()
                    )
                    executor = TravelToolExecutor(business.travel)
                places = await executor.execute(
                    context, "search_places", {"city": city, "query": "", "limit": 8}
                )
                assert places.code is None and len(places.evidence_ids) == 8
                place_ids[city] = places.evidence_ids
                hotels = await executor.execute(
                    context,
                    "search_hotel_offers",
                    {
                        "expected_revision": request.revision,
                        "segment_arrive": segment["arrive"],
                        "limit": 1,
                    },
                )
                assert hotels.code is None and hotels.evidence_ids
                stays.append(
                    HotelStay(
                        hotel_evidence_id=UUID(hotels.evidence_ids[0]),
                        check_in=date.fromisoformat(segment["arrive"]),
                        check_out=date.fromisoformat(segment["depart"]),
                    )
                )
            async with transaction(business.travel.database) as db:
                await runs.finish(db, context, RuntimeOutcome(text="选择各段酒店"))
            service = RunService(
                business.travel.database,
                runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="合成离线选择")),
            )
            try:
                submitted = await service.submit(
                    context.user_id,
                    context.session_id,
                    MessageInput(
                        client_message_id=uuid4(),
                        text="三段住宿已选，继续规划",
                        expected_revision=request.revision,
                        hotel_stays=tuple(stays),
                    ),
                )
                active = RunContext(context.user_id, context.session_id, submitted.run_id)
                items = []
                for day, city in enumerate(("京都", "大阪", "奈良", "奈良")):
                    offset = 4 if day == 3 else 0
                    start = datetime(2026, 11, 3 + day, 9, tzinfo=ZoneInfo("Asia/Tokyo"))
                    for index in range(4):
                        begins = start + timedelta(hours=index * 2)
                        items.append(
                            {
                                "place_evidence_id": place_ids[city][offset + index],
                                "start": begins.isoformat(),
                                "end": (begins + timedelta(hours=1)).isoformat(),
                            }
                        )
                proposal = ItineraryProposal.model_validate(
                    {"expected_revision": request.revision, "items": items}
                )
                report = await PlanningService(business.travel).validate(active, proposal)
                assert report.status != "conflict", report.feedback()
                assert not any(check.code == "repeated_place_warning" for check in report.checks)
                draft = await PlanService(business.travel).stage(
                    active,
                    StageInput.model_validate(
                        {
                            "change": {
                                "kind": "initial",
                                "proposal": proposal.model_dump(mode="json"),
                            }
                        }
                    ),
                )
                assert len(draft.content.hotel_stays) == 3
                assert {item.start.date() for item in draft.content.items} == {
                    date(2026, 11, d) for d in (3, 4, 5, 6)
                }
                assert len(draft.content.items) == 16
            finally:
                await service.close()

    with temporary_database(postgres_url, "eval") as url, asyncio.Runner() as runner:
        runner.run(exercise(url))
