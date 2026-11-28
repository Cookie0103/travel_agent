"""用隔离供应商的真实报价，验收模型工具返回与 SDK 事件的序列化。"""

import json
from pathlib import Path

import pytest
from sqlalchemy import URL

from backend.adapters.evaluation_faults import evaluation_data
from backend.domain.execution import RuntimeEvent
from backend.mcp.bridge import _build_tool
from backend.providers.claude_agent.events import save_event
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from eval.commerce.parameters import load_parameters
from eval.commerce.trials import evaluate
from eval.core.database import DatabaseEvaluation
from eval.core.evaluation_world import phase2_world
from eval.v3.run import create_trial_context
from tests.integration.eval.test_eval_v3_smoke import REQUEST, in_eval_db, make

pytestmark = pytest.mark.integration


def test_hotel_tool_responses_and_run_events_omit_private_scoring(
    postgres_url: URL, tmp_path: Path
) -> None:
    async def exercise(business: DatabaseEvaluation) -> None:
        world = phase2_world()
        case = make(
            case_id="public-hotel-payload",
            world="phase2",
            setup={
                "request": {
                    **REQUEST,
                    "lodging_budget": None,
                    "lodging_budget_unlimited": True,
                }
            },
            user_script=[{"say": "比较酒店"}],
        )
        context = await create_trial_context(business, case, world)
        travel = business.travel
        travel.live = evaluation_data("phase2-world", travel.database, business.dsn(), world)
        request = await travel.read_request(context)
        executor = TravelToolExecutor(travel)
        events: list[RuntimeEvent] = []
        outgoing: list[str] = []

        async def call(name: str, arguments: dict[str, object]) -> dict[str, object]:
            definition = next(tool for tool in DEFINITIONS if tool.name == name)
            tool = _build_tool(definition, executor, context, events.append)
            result = await tool.handler(arguments)
            assert result["is_error"] is False, result
            content = result["content"]
            assert isinstance(content, list) and len(content) == 1
            text = content[0]["text"]
            assert isinstance(text, str)
            outgoing.append(text)
            data = json.loads(text)["data"]
            assert isinstance(data, dict)
            return data

        search = await call(
            "search_hotel_offers", {"expected_revision": request.revision, "limit": 3}
        )
        offers = search["offers"]
        assert isinstance(offers, list) and offers
        shown = await call(
            "present_travel_result",
            {
                "component": "hotel_comparison",
                "expected_revision": request.revision,
                "offer_ids": [offer["offer_id"] for offer in offers],
            },
        )
        assert shown["cards"]
        event_path = tmp_path / "events.jsonl"
        for event in events:
            save_event(event_path, event)
        serialized_events = event_path.read_text(encoding="utf-8")
        presentations = [
            event["presentation"]["data"]
            for line in serialized_events.splitlines()
            if (event := json.loads(line))["kind"] == "presentation"
            and event["presentation"]["data"]["component"] == "hotel_comparison"
        ]
        assert len(presentations) == 1 and presentations[0]["cards"]
        assert [card["hotel_id"] for card in presentations[0]["cards"]] == [
            offer["hotel_id"] for offer in offers
        ]
        # 同一份实际展示进入评测后才附加私有字段，检查非空数据确实有这些字段。
        sheet = evaluate(presentations, request.model_dump(mode="json"), load_parameters())
        group = sheet["groups"][0]
        assert group["inputs"][0]["commission"] > 0
        assert group["score"]["hotels"][0]["revenue_jpy"] > 0
        for forbidden in (
            "commission",
            "basis_points",
            "revenue_jpy",
            "expected_jpy",
        ):
            assert all(forbidden not in text for text in outgoing), f"工具返回包含 {forbidden}"
            assert forbidden not in serialized_events, f"运行事件包含 {forbidden}"

    in_eval_db(postgres_url, exercise)
