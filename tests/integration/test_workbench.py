"""R05–R08：固定离线样例调用真实工具/PG；持久卡片、局部改程与锁定失败。"""

import asyncio
import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL

from backend.api.app import create_app
from backend.domain.execution import BusinessResult, RunContext
from backend.domain.plans import StageInput
from backend.domain.travel_request import RequestPatch
from backend.persistence.catalog import import_catalog
from backend.services.common import ServiceError
from backend.services.plans import LockInput, PlanService
from backend.services.runs import MessageInput, RunService, RunView
from backend.services.sessions import SessionService
from backend.services.travel import TravelService
from backend.services.views import HotelPresentation, PlanView
from backend.tools.travel import TravelToolExecutor
from data.import_catalog import load_snapshot
from tests.integration.test_sessions import login
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_http_workbench_flow_and_read_only_reconnect(postgres_url: URL) -> None:
    """R01–R08：实际HTTP契约、离线Agent、真实PG、SSE、确认和恢复读取。"""
    sessions = SessionService(postgres_url, demo_enabled=True)
    options = {"loop_factory": asyncio.SelectorEventLoop}

    async def seed() -> None:
        async with sessions.database.sessions.begin() as db:
            await import_catalog(db, load_snapshot())

    with TestClient(create_app(sessions), backend_options=options) as client:
        assert client.portal is not None
        client.portal.call(seed)
        owner, other = login(client), login(client)
        session_id = client.post("/sessions", headers=owner).json()["session_id"]
        request_path = f"/sessions/{session_id}/request"
        conditions = {
            "city": "京都",
            "start_date": "2026-11-03",
            "end_date": "2026-11-05",
            "adults": 2,
            "child_ages": [],
            "rooms": 1,
            "budget": "50000",
            "transport": "walk",
            "departure_time": "09:00",
        }
        assert (
            client.patch(
                request_path,
                headers=owner,
                json={
                    "expected_revision": 0,
                    "set": {**conditions, "adults": 0},
                },
            ).status_code
            == 422
        )
        updated = client.patch(
            request_path,
            headers=owner,
            json={
                "expected_revision": 0,
                "set": conditions,
            },
        )
        assert updated.status_code == 200, updated.text
        assert (
            client.patch(
                request_path,
                headers=owner,
                json={
                    "expected_revision": 0,
                    "set": {"rooms": 2},
                },
            ).status_code
            == 409
        )
        path = f"/sessions/{session_id}/messages"
        body = {"client_message_id": str(uuid4()), "text": "演示：生成行程"}
        created = client.post(path, headers=owner, json=body)
        assert created.status_code == 202, created.text
        run_path = "/runs/" + created.json()["run_id"]
        stream = client.get(run_path + "/events", headers=owner)
        events = [
            json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")
        ]
        assert events[0]["kind"] == "started" and events[-1]["kind"] == "completed", events[-1]
        assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
        snapshot = client.get(run_path, headers=owner).json()
        assert snapshot["status"] == "completed" and len(snapshot["presentations"]) == 1
        assert snapshot["business_result"]["kind"] == "draft_staged"
        assert snapshot["business_result"]["validation_status"] == "partial"
        draft_id = snapshot["presentations"][0]["presentation"]["data"]["draft_id"]
        draft_path = f"/plan-drafts/{draft_id}"
        draft = client.get(draft_path, headers=owner).json()
        assert len(draft["cards"]) == 6 and draft["validation"]["status"] == "partial"
        assert client.get(draft_path, headers=other).status_code == 404
        assert client.post(draft_path + "/confirm", headers=other).status_code == 404
        saved = client.post(draft_path + "/confirm", headers=owner)
        assert saved.status_code == 200, saved.text
        assert client.post(draft_path + "/confirm", headers=owner).json() == saved.json()
        assert client.post(path, headers=owner, json=body).json()["run_id"] == snapshot["run_id"]
        replay = client.get(
            run_path + "/events",
            headers={
                **owner,
                "Last-Event-ID": str(events[-2]["sequence"]),
            },
        )
        assert [line for line in replay.text.splitlines() if line.startswith("id:")] == [
            "id: " + str(events[-1]["sequence"]),
        ]
        plan_path = "/plans/" + saved.json()["plan_id"]
    with TestClient(create_app(SessionService(postgres_url)), backend_options=options) as restarted:
        # Runtime fields/events stay immutable; only the original draft's confirmation is projected.
        assert restarted.get(run_path, headers=owner).json() == {
            **snapshot,
            "business_result": {
                "kind": "confirmed",
                "draft_id": None,
                "plan_id": saved.json()["plan_id"],
                "validation_status": None,
                "code": None,
                "reason": None,
                "version": 1,
            },
        }
        assert restarted.get(plan_path, headers=owner).json()["version"] == 1
        assert restarted.get(draft_path, headers=owner).json()["status"] == "confirmed"


async def run_demo(service: RunService, context: RunContext, text: str) -> RunView:
    run = await service.submit(
        context.user_id, context.session_id, MessageInput(client_message_id=uuid4(), text=text)
    )
    await asyncio.wait_for(asyncio.gather(*tuple(service.tasks.values())), timeout=10)
    return await service.get(context.user_id, run.run_id)


def test_offline_workbench_compares_stages_confirms_and_changes_one_item(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        async with travel.database.sessions.begin() as db:
            await import_catalog(db, load_snapshot())
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {"transport": "walk", "departure_time": "09:00", "budget": "50000"},
                }
            ),
        )
        service, plans = RunService(travel.database), PlanService(travel)
        comparison = await run_demo(service, context, "演示：比较酒店")
        assert comparison.status == "completed"
        payload = comparison.presentations[0]["presentation"]
        assert isinstance(payload, dict)
        hotels = HotelPresentation.model_validate(payload["data"])
        assert len(hotels.cards) == 3 and hotels.comparison.comparable
        initial = await run_demo(service, context, "演示：生成行程")
        assert initial.status == "completed", initial.answer
        assert initial.business_result and initial.business_result.kind == "draft_staged"
        payload = initial.presentations[0]["presentation"]
        assert isinstance(payload, dict) and isinstance(payload["data"], dict)
        draft_id = UUID(str(payload["data"]["draft_id"]))
        draft = PlanView.model_validate(await plans.get_draft(context.user_id, draft_id))
        assert len(draft.cards) == 6 and draft.validation.status == "partial"
        saved = await plans.confirm(context.user_id, draft_id)
        assert saved.version == 1
        assert await plans.confirm(context.user_id, draft_id) == saved
        revised = await run_demo(service, context, "演示：修改第二天下午")
        assert revised.status == "completed", revised.answer
        payload = revised.presentations[0]["presentation"]
        assert isinstance(payload, dict) and isinstance(payload["data"], dict)
        draft = PlanView.model_validate(
            await plans.get_draft(context.user_id, UUID(str(payload["data"]["draft_id"])))
        )
        assert (
            len(draft.changes) == 1 and draft.changes[0].item_id == saved.content.items[3].item_id
        )
        confirmed = await plans.confirm(context.user_id, draft.draft_id) if draft.draft_id else None
        assert confirmed and confirmed.version == 2
        for before, after in zip(saved.content.items, confirmed.content.items, strict=True):
            if before.item_id != saved.content.items[3].item_id:
                assert before == after
        assert confirmed.content.hotel_evidence_id == saved.content.hotel_evidence_id
        # 第一日多一项后，下标3已不是第二天下午；仍必须按日期/时段定位。
        extra = await plans.stage(
            context,
            StageInput.model_validate(
                {
                    "change": {
                        "kind": "patch",
                        "plan_id": str(saved.plan_id),
                        "patch": {
                            "base_version": 2,
                            "expected_revision": 2,
                            "operations": [
                                {
                                    "op": "add",
                                    "item": {
                                        "place_evidence_id": str(
                                            saved.content.items[0].place_evidence_id
                                        ),
                                        "start": "2026-11-03T09:00:00+09:00",
                                        "end": "2026-11-03T09:30:00+09:00",
                                    },
                                }
                            ],
                        },
                    }
                }
            ),
        )
        await plans.confirm(context.user_id, extra.draft_id)
        located = await run_demo(service, context, "演示：修改第二天下午")
        assert located.status == "completed"
        payload = located.presentations[0]["presentation"]
        assert isinstance(payload, dict) and isinstance(payload["data"], dict)
        located_draft = PlanView.model_validate(
            await plans.get_draft(context.user_id, UUID(str(payload["data"]["draft_id"])))
        )
        assert len(located_draft.changes) == 1
        assert located_draft.changes[0].item_id == saved.content.items[3].item_id
        await plans.locks(
            context.user_id,
            saved.plan_id,
            LockInput(expected_version=3, locked_item_ids=(confirmed.content.items[3].item_id,)),
        )
        blocked = await run_demo(service, context, "演示：修改第二天下午")
        assert blocked.status == "failed" and blocked.error_code == "validation"
        assert not blocked.presentations
        # 重建服务只读取落库快照，不触发模型或重复工具。
        restarted = RunService(travel.database)
        assert await restarted.get(context.user_id, initial.run_id) == replace(
            initial, business_result=BusinessResult("confirmed", plan_id=saved.plan_id, version=1)
        )
        assert not restarted.tasks
        with pytest.raises(ServiceError, match="执行不存在"):
            await restarted.get(uuid4(), initial.run_id)
        await service.close()

    runner.run(exercise())


def test_demo_reports_no_matching_hotels_without_index_error(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 1, "set": {"adults": 12, "rooms": 1, "transport": "walk"}}
            ),
        )
        service = RunService(travel.database)
        result = await run_demo(service, context, "演示：比较酒店")
        assert result.status == "failed" and result.error_code == "unavailable"
        assert "没有可用数据" in result.answer
        assert not result.presentations
        await service.close()

    runner.run(exercise())


def test_demo_rejects_ambiguous_second_afternoon_hidden_by_card_truncation(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        async with travel.database.sessions.begin() as db:
            await import_catalog(db, load_snapshot())
        executor = TravelToolExecutor(travel)
        first = await executor.execute(
            context, "get_place_facts", {"entity_id": "osm:way/57111281"}
        )
        second = await executor.execute(
            context, "get_place_facts", {"entity_id": "osm:way/554879249"}
        )
        items = [
            {
                "place_evidence_id": first.evidence_ids[0],
                "start": f"2026-11-03T{hour:02}:00:00+09:00",
                "end": f"2026-11-03T{hour:02}:30:00+09:00",
            }
            for hour in range(9, 16)
        ]
        items.extend(
            {
                "place_evidence_id": second.evidence_ids[0],
                "start": f"2026-11-04T{hour:02}:00:00+09:00",
                "end": f"2026-11-04T{hour:02}:30:00+09:00",
            }
            for hour in (14, 16)
        )
        plans = PlanService(travel)
        draft = await plans.stage(
            context,
            StageInput.model_validate(
                {
                    "change": {
                        "kind": "initial",
                        "proposal": {"expected_revision": 1, "items": items},
                    }
                }
            ),
        )
        saved = await plans.confirm(context.user_id, draft.draft_id)
        service = RunService(travel.database)
        result = await run_demo(service, context, "演示：修改第二天下午")
        assert result.status == "failed" and result.error_code == "validation"
        assert "截断行程" in result.answer and not result.presentations
        assert (await plans.get(context.user_id, saved.plan_id))["version"] == 1
        await service.close()

    runner.run(exercise())


@pytest.mark.parametrize("text", ["演示：未知命令", "演示：修改第二天下午", "演示：生成行程"])
def test_demo_rejects_invalid_command_missing_saved_plan_or_transport(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    text: str,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        async with travel.database.sessions.begin() as db:
            await import_catalog(db, load_snapshot())
        service = RunService(travel.database)
        result = await run_demo(service, context, text)
        assert result.status == "failed" and result.error_code in {"validation", "blocked"}
        assert not result.presentations
        await service.close()

    runner.run(exercise())
