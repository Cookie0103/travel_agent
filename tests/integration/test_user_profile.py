"""衍生画像的归属/引用、清正文与生成期间遗忘CAS；模型全部合成。"""

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.domain.execution import RunContext
from backend.domain.preferences import PreferencePatch, PreferenceVersion
from backend.persistence.models import MemoryFactRow, UserProfileSummaryRow
from backend.services.common import ServiceError, transaction
from backend.services.memory import MemoryService
from backend.services.preferences import PreferenceService
from backend.services.travel import TravelService
from backend.services.user_profile import UserProfileService
from tests.integration.test_sessions import client as client
from tests.integration.test_sessions import login
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_profile_api_is_owner_scoped_and_disabled_generation_does_not_charge(
    client: TestClient,
) -> None:
    headers = login(client)
    assert client.get("/health").status_code == 200
    assert client.get("/profile-summary").status_code == 401
    response = client.get("/profile-summary", headers=headers)
    assert response.status_code == 200 and response.json()["text"] is None
    assert response.json()["can_update"] is False
    assert (
        client.post(
            "/profile-summary",
            headers=headers,
            json={"expected_revision": 0},
        ).status_code
        == 403
    )


def test_profile_uses_only_active_long_term_facts_and_delete_erases_derivative(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, travel, context = travel_setup
    from backend.providers.claude_agent import structured

    async def exercise() -> None:
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 0, "set": {"interests": ["寺庙"]}}
            ),
        )
        memory = MemoryService(travel.database)
        own = (await memory.facts(context.user_id))[0]
        async with transaction(travel.database) as db:
            db.add(
                MemoryFactRow(
                    user_id=context.user_id,
                    key="pace",
                    value="慢节奏",
                    scope="trip",
                    session_id=context.session_id,
                    status="active",
                    source="manual",
                    evidence_quote="这次而已",
                    valid_from=datetime.now(UTC),
                )
            )

        def synthetic(kind: str, payload: object, root: Path) -> tuple[str, dict[str, object]]:
            assert kind == "profile"
            assert isinstance(payload, dict) and isinstance(payload["active_facts"], list)
            assert all(f["scope"] == "long_term" for f in payload["active_facts"])
            assert len(payload["active_facts"]) == 1
            return json.dumps(
                {
                    "sentences": [
                        f"喜欢参观寺庙 [fact:{own.fact_id}]",
                        f"外人偏好 [fact:{uuid4()}]",
                        "没有引用的推断",
                    ]
                }
            ), {}

        monkeypatch.setattr(structured, "structured_call", synthetic)
        profile = UserProfileService(travel.database, live_enabled=True)
        value = await profile.generate(context.user_id, PreferenceVersion(expected_revision=1))
        assert value.text == f"喜欢参观寺庙 [fact:{own.fact_id}]"
        assert value.cited_fact_ids == (own.fact_id,)
        assert (await travel.business_context(context))["profile_summary"] == value.text
        await memory.delete(context.user_id, own.fact_id, PreferenceVersion(expected_revision=1))
        assert (await profile.get(context.user_id)).text is None
        async with transaction(travel.database) as db:
            row = await db.get(UserProfileSummaryRow, context.user_id)
            assert row and row.text == "" and row.cited_fact_ids == [] and row.invalidated_at

    runner.run(exercise())


def test_forget_during_profile_generation_cannot_restore_body(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, travel, context = travel_setup
    from backend.providers.claude_agent import structured

    async def exercise() -> None:
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 0, "set": {"interests": ["寺庙"]}}
            ),
        )
        own = (await MemoryService(travel.database).facts(context.user_id))[0]
        loop = asyncio.get_running_loop()

        def synthetic(kind: str, payload: object, root: Path) -> tuple[str, dict[str, object]]:
            future = asyncio.run_coroutine_threadsafe(
                PreferenceService(travel.database).change(
                    context.user_id, PreferenceVersion(expected_revision=1)
                ),
                loop,
            )
            future.result(timeout=3)
            return json.dumps({"sentences": [f"喜欢寺庙 [fact:{own.fact_id}]"]}), {}

        monkeypatch.setattr(structured, "structured_call", synthetic)
        service = UserProfileService(travel.database, live_enabled=True)
        with pytest.raises(ServiceError) as error:
            await service.generate(context.user_id, PreferenceVersion(expected_revision=1))
        assert error.value.status == 409
        assert (await service.get(context.user_id)).text is None
        async with transaction(travel.database) as db:
            assert await db.get(UserProfileSummaryRow, context.user_id) is None

    runner.run(exercise())


def test_same_revision_generation_is_single_flight_and_reuses_valid_result(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C6：同一revision的并发/重复POST只调一次模型；引用校验不放宽。"""
    runner, travel, context = travel_setup
    from backend.providers.claude_agent import structured

    async def exercise() -> None:
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 0, "set": {"interests": ["寺庙"]}}
            ),
        )
        own = (await MemoryService(travel.database).facts(context.user_id))[0]
        calls: list[str] = []

        def synthetic(kind: str, payload: object, root: Path) -> tuple[str, dict[str, object]]:
            calls.append(kind)
            time.sleep(0.3)  # 在线程里等待，让并发请求有机会重叠
            return json.dumps({"sentences": [f"喜欢寺庙 [fact:{own.fact_id}]"]}), {}

        monkeypatch.setattr(structured, "structured_call", synthetic)
        service = UserProfileService(travel.database, live_enabled=True)
        version = PreferenceVersion(expected_revision=1)
        views = await asyncio.gather(
            *(service.generate(context.user_id, version) for _ in range(3))
        )
        assert len(calls) == 1
        assert {view.text for view in views} == {f"喜欢寺庙 [fact:{own.fact_id}]"}
        again = await service.generate(context.user_id, version)
        assert len(calls) == 1 and again.text == views[0].text
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 1, "set": {"interests": ["寺庙", "美食"]}}
            ),
        )
        assert (await service.get(context.user_id)).text is None  # 版本变化后不复用
        assert not service._inflight  # noqa: SLF001

    runner.run(exercise())
