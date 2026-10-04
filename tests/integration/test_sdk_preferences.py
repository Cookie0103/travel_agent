"""R13/R14：实际CLI中删除偏好后新建SDK会话，旧历史不能重新注入。"""

import asyncio
import json
import shutil
from dataclasses import replace
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RuntimeOutcome
from backend.domain.preferences import PreferencePatch, PreferenceVersion
from backend.mcp.bridge import sdk_tool_name
from backend.services.preferences import PreferenceService
from backend.services.runs import MessageInput, RunService
from backend.services.travel import RunContext, TravelService
from tests.fakes import FakeRuntime
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_sdk_recovery import sdk_id
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not shutil.which("claude"), reason="需要实际CLI，不访问真实模型")
@pytest.mark.parametrize("saved_preference", [True, False])
def test_deleted_preference_invalidates_sdk_history_without_changing_trip(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    saved_preference: bool,
) -> None:
    runner, travel, context = travel_setup
    preferences = PreferenceService(travel.database)
    marker = "deleted-interest-" + uuid4().hex
    if saved_preference:
        runner.run(
            preferences.change(
                context.user_id,
                PreferencePatch.model_validate(
                    {
                        "expected_revision": 0,
                        "set": {"interests": [marker], "transport": "transit"},
                    }
                ),
            )
        )
    runs = RunService(
        travel.database,
        runtime_factory=lambda executor: FakeRuntime(
            RuntimeOutcome(text="之前回答提及偏好：" + marker, sdk_session_id="fixture-preferences")
        ),
    )

    async def persist_dialogue() -> None:
        previous = await runs.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text="读取偏好"),
        )
        await asyncio.gather(*tuple(runs.tasks.values()))
        assert marker in (await runs.get(context.user_id, previous.run_id)).answer
        await runs.close()

    runner.run(persist_dialogue())
    requests: list[dict[str, object]] = []
    scripted = partial(
        scripted_response, tool_calls=((sdk_tool_name("load_skill"), {"name": "hotel-comparison"}),)
    )

    def forward(body: bytes) -> tuple[int, bytes]:
        requests.append(json.loads(body))
        return scripted(body)

    first, guard = run_database_worker(travel, context, tmp_path, forward, "读取当前条件及偏好")
    assert first["status"] == "success" and first["checkpoint_persisted"] is True
    assert not guard.failures and marker in json.dumps(requests[0]["system"])
    first_id = sdk_id(first)
    runner.run(
        preferences.change(
            context.user_id, PreferenceVersion(expected_revision=int(saved_preference))
        )
    )
    requests.clear()
    second, guard = run_database_worker(
        travel, replace(context, run_id=uuid4()), tmp_path, forward, "继续读取当前条件及偏好"
    )
    assert second["status"] == "success" and not guard.failures
    assert second["resume_mode"] == "business_snapshot" and sdk_id(second) != first_id
    assert marker not in json.dumps(requests)
    assert runner.run(travel.get_request(context)).revision == 1
    assert runner.run(preferences.get(context.user_id)).revision == int(saved_preference) + 1
