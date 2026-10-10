"""R06：真实SDK接校验冲突后再提修复，或触及3轮上限；脚本模型不产生API费用。"""

import asyncio
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.domain.execution import RunContext
from backend.domain.plans import PlanDraft
from backend.mcp.bridge import sdk_tool_name
from backend.persistence import plans
from backend.services.catalog import CatalogService
from backend.services.common import transaction
from backend.services.travel import TravelService
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not shutil.which("claude"), reason="需要本机Claude CLI，不访问真实模型")
@pytest.mark.parametrize("repair", [True, False])
@pytest.mark.parametrize("conflict", ["opening_hours", "repeated_place_warning"])
def test_sdk_reads_conflict_and_repairs_or_reports_limit(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    repair: bool,
    conflict: str,
) -> None:
    runner, travel, context = travel_setup
    first, second = runner.run(destinations(travel, context))
    if conflict == "repeated_place_warning":
        alternative = runner.run(CatalogService(travel).get(context, "places", "osm:way/98115917"))
        second = alternative.evidence[0]
    feedback: list[dict[str, object]] = []

    def forward(body: bytes) -> tuple[int, bytes]:
        request = json.loads(body)
        results = [
            part["content"]
            for message in request["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if isinstance(part, dict) and part.get("type") == "tool_result"
        ]
        if results:
            content = results[-1]
            payload = json.loads(content if isinstance(content, str) else content[0]["text"])
            feedback.append(payload)
            if payload["status"] == "error" or (repair and payload["data"]["status"] != "conflict"):
                return scripted_response(body)
            checks = payload["data"]["checks"]
            assert any(c["status"] == "conflict" and c["code"] == conflict for c in checks), checks
        fixed = bool(repair and results)
        candidate = proposal(first, closed=conflict == "opening_hours" and not fixed)
        if conflict == "repeated_place_warning":
            candidate = candidate.model_copy(
                update={
                    "items": (
                        candidate.items[0],
                        candidate.items[0].model_copy(
                            update={
                                "place_evidence_id": (second if fixed else first).evidence_id,
                                "start": datetime.fromisoformat("2026-11-03T14:00+09:00"),
                                "end": datetime.fromisoformat("2026-11-03T15:00+09:00"),
                            }
                        ),
                    )
                }
            )
        arguments = candidate.model_dump(mode="json")
        status, response = scripted_response(
            json.dumps({**request, "messages": []}).encode(),
            tool_calls=((sdk_tool_name("validate_itinerary"), arguments),),
        )
        return status, response.replace(b'"tool_0"', f'"validation_{len(results)}"'.encode())

    report, guard = run_database_worker(
        travel, context, tmp_path, forward, "检查行程并按冲突反馈修复，最多3轮", max_attempts=6
    )
    assert report["status"] == "success", (report.get("code"), guard.failures)
    assert not guard.failures and guard.attempts == (3 if repair else 6)
    data = [payload["data"] for payload in feedback]
    assert all(isinstance(value, dict) for value in data)
    if repair:
        assert [value["status"] for value in data if isinstance(value, dict)] == [
            "conflict",
            "partial",
        ]
    else:
        error = feedback[-1]["error"]
        assert len(feedback) == 5 and isinstance(error, dict) and error["code"] == "blocked"
        penultimate = data[-2]
        assert isinstance(penultimate, dict) and penultimate["repair_rounds_remaining"] == 0


@pytest.mark.skipif(not shutil.which("claude"), reason="需要真实CLI；本地脚本不调用模型")
def test_sdk_complete_three_day_chain_has_enough_turns_without_saving_formal_plan(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], tmp_path: Path
) -> None:
    """R06/R08：SDK真实执行条件→六个不同地点→酒店→路线→校验→草稿→卡片→回答。"""
    runner, travel, context = travel_setup
    runner.run(destinations(travel, context))  # 复用目录初始化，模型阶段重新查当前revision事实。
    proposal_data: dict[str, object] = {}
    entities = (
        "osm:way/57111281",
        "osm:way/554879249",
        "osm:way/98115917",
        "osm:way/336641107",
        "osm:way/98103477",
        "osm:way/619903245",
    )

    def forward(body: bytes) -> tuple[int, bytes]:
        nonlocal proposal_data
        request = json.loads(body)
        payloads = [
            json.loads(value if isinstance(value, str) else value[0]["text"])
            for message in request["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if isinstance(part, dict) and part.get("type") == "tool_result"
            for value in [part["content"]]
        ]
        assert all(value["status"] == "ok" for value in payloads)
        step = len(payloads)
        arguments: dict[str, object]
        if step == 0:
            tool, arguments = (
                "update_travel_request",
                {
                    "expected_revision": 1,
                    "set": {
                        "transport": "walk",
                        "budget": "50000",
                        "currency": "JPY",
                        "departure_time": "09:00",
                    },
                },
            )
        elif step == 1:
            calls: tuple[tuple[str, dict[str, object]], ...] = tuple(
                (sdk_tool_name("get_place_facts"), {"entity_id": entity}) for entity in entities
            )
            status, content = scripted_response(
                json.dumps({**request, "messages": []}).encode(), tool_calls=calls
            )
            for index in range(len(calls)):
                content = content.replace(
                    f'"tool_{index}"'.encode(), f'"complete_plan_facts_{index}"'.encode()
                )
            return status, content
        elif step == 7:
            tool, arguments = "search_hotel_offers", {"expected_revision": 2, "limit": 1}
        elif step == 8:
            ids = [value["evidence_ids"][0] for value in payloads[1:7]]
            legs = [
                {
                    "from_evidence_id": ids[(day - 3) * 2],
                    "to_evidence_id": ids[(day - 3) * 2 + 1],
                    "departure": f"2026-11-{day:02d}T11:00:00+09:00",
                }
                for day in range(3, 6)
            ]
            tool, arguments = "estimate_routes", {"expected_revision": 2, "legs": legs}
        elif step == 9:
            items = []
            for day in range(3):
                start = datetime.fromisoformat("2026-11-03T00:00:00+09:00") + timedelta(days=day)
                for index, hour in enumerate((10, 14)):
                    item = {
                        "place_evidence_id": payloads[day * 2 + index + 1]["evidence_ids"][0],
                        "start": (start + timedelta(hours=hour)).isoformat(),
                        "end": (start + timedelta(hours=hour + 1)).isoformat(),
                    }
                    if index:
                        item["route_evidence_id"] = payloads[8]["data"]["routes"][day][
                            "evidence_id"
                        ]
                    items.append(item)
            proposal_data = {
                "expected_revision": 2,
                "items": items,
                "hotel_evidence_id": payloads[7]["evidence_ids"][0],
            }
            tool, arguments = "validate_itinerary", proposal_data
        elif step == 10:
            assert payloads[-1]["data"]["status"] in {"complete", "partial"}
            tool, arguments = (
                "stage_plan_change",
                {"change": {"kind": "initial", "proposal": proposal_data}},
            )
        elif step == 11:
            tool, arguments = (
                "present_travel_result",
                {"component": "itinerary", "draft_id": payloads[-1]["data"]["draft_id"]},
            )
        else:
            assert step == 12
            return scripted_response(body)
        status, content = scripted_response(
            json.dumps({**request, "messages": []}).encode(),
            tool_calls=((sdk_tool_name(tool), arguments),),
        )
        return status, content.replace(b'"tool_0"', f'"complete_plan_{step}"'.encode())

    report, guard = run_database_worker(
        travel,
        context,
        tmp_path,
        forward,
        "暂存京都三日游，查事实路线并校验后展示，正式保存等用户页面确认",
        max_attempts=12,
    )
    assert report["status"] == "success", (report.get("code"), report.get("reason"), guard.attempts)
    assert guard.attempts == 8 and not guard.failures
    events = report["events"]
    assert isinstance(events, list)
    assert [e["tool_name"] for e in events if e["kind"] == "tool_finished"] == [
        "update_travel_request",
        "get_place_facts",
        "get_place_facts",
        "get_place_facts",
        "get_place_facts",
        "get_place_facts",
        "get_place_facts",
        "search_hotel_offers",
        "estimate_routes",
        "validate_itinerary",
        "stage_plan_change",
        "present_travel_result",
    ]
    assert all(e["code"] is None for e in events if e["kind"] == "tool_finished")

    async def verify() -> None:
        async with transaction(travel.database) as db:
            formal = await plans.for_session(db, context)
            draft = await plans.latest_draft(db, context)
            assert formal and formal.current_version == 0 and draft
            stored = PlanDraft.model_validate(draft.payload)
            assert stored.validation.status in {"complete", "partial"}
            assert len(stored.content.items) == 6

    runner.run(verify())
