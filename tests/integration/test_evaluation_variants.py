"""R06/R14/16：同一实际SDK/CLI和真实PG下的单因素隔离，不访问模型API。"""

import asyncio
import json
import shutil
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import TypeAdapter

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.preferences import PreferencePatch
from backend.mcp.bridge import sdk_tool_name
from backend.persistence import plans
from backend.providers.claude_agent.evaluation import EvaluationVariant, evaluation_definitions
from backend.services.common import ServiceError, transaction
from backend.services.preferences import PreferenceService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response


@pytest.mark.skipif(not shutil.which("claude"), reason="需要实际CLI，本机脚本不访问模型")
@pytest.mark.parametrize(
    "variant",
    [
        "full",
        "no_tools",
        "no_skills",
        "no_preferences",
        "no_repairs",
        "no_compaction",
        "baseline_b2",
    ],
)
def test_actual_sdk_advertises_variant_and_keeps_trip_and_preferences_unchanged(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    variant: EvaluationVariant,
) -> None:
    runner, travel, context = travel_setup
    preferences = PreferenceService(travel.database)
    saved = runner.run(
        preferences.change(
            context.user_id,
            PreferencePatch.model_validate(
                {
                    "expected_revision": 0,
                    "set": {"interests": ["private-preference-marker"]},
                }
            ),
        )
    )
    before = runner.run(travel.get_request(context))
    requests: list[dict[str, object]] = []

    def forward(body: bytes) -> tuple[int, bytes]:
        request = json.loads(body)
        requests.append(request)
        # 只有本机脚本回答，真实SDK仍自行发送协议/工具schema与完整终止结果。
        return scripted_response(
            json.dumps(
                {
                    **request,
                    "messages": [
                        {"content": [{"type": "tool_result", "content": "synthetic final answer"}]}
                    ],
                }
            ).encode()
        )

    report, guard = run_database_worker(
        travel, context, tmp_path, forward, "解释当前旅行条件，不调用工具", variant=variant
    )
    assert report["status"] == "success" and guard.attempts == 1 and not guard.failures, (
        report.get("code"),
        report.get("reason"),
        guard.attempts,
        guard.failures,
        guard.failure_details,
    )
    assert report["checkpoint_persisted"] is (variant == "full")
    assert report["resume_mode"] == "business_snapshot"
    native_tools = requests[0].get("tools", [])
    assert isinstance(native_tools, list)
    assert {tool["name"] for tool in native_tools} == {
        sdk_tool_name(d.name) for d in evaluation_definitions(variant, database=True)
    }
    system = json.dumps(requests[0]["system"])
    assert ("private-preference-marker" in system) is (
        variant not in {"no_tools", "no_preferences", "baseline_b2"}
    )
    if variant == "no_tools":
        assert "服务端业务状态" not in system and str(context.user_id) not in system
    assert runner.run(preferences.get(context.user_id)) == saved
    assert runner.run(travel.get_request(context)) == before


def test_no_repairs_keeps_first_validation_and_final_stage_checks(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        first, _ = await destinations(travel, context)
        candidate = proposal(first)
        executor = TravelToolExecutor(travel, max_validations=1)
        result = await executor.execute(
            context, "validate_itinerary", candidate.model_dump(mode="json")
        )
        assert result.code is None and result.data["repair_rounds_remaining"] == 0
        again = await executor.execute(
            context, "validate_itinerary", candidate.model_dump(mode="json")
        )
        assert again.code == "blocked"
        changed = candidate.model_copy(
            update={
                "items": (
                    candidate.items[0].model_copy(
                        update={
                            "start": candidate.items[0].start + timedelta(minutes=30),
                            "end": candidate.items[0].end + timedelta(minutes=30),
                        }
                    ),
                    *candidate.items[1:],
                )
            }
        )
        rejected_repair = await executor.execute(
            context,
            "stage_plan_change",
            {
                "change": {"kind": "initial", "proposal": changed.model_dump(mode="json")},
            },
        )
        assert rejected_repair.code == "blocked" and rejected_repair.data == {}
        async with transaction(travel.database) as db:
            assert await plans.latest_draft(db, context) is None
            assert await plans.for_session(db, context) is None
        staged = await executor.execute(
            context,
            "stage_plan_change",
            {
                "change": {"kind": "initial", "proposal": candidate.model_dump(mode="json")},
            },
        )
        assert staged.code is None and executor.validations == 1
        # 草稿可保留冲突供展示；最终用户确认必须重新校验并拒绝硬冲突。
        failed = TravelToolExecutor(travel, max_validations=1)
        closed = proposal(first, closed=True)
        check = await failed.execute(context, "validate_itinerary", closed.model_dump(mode="json"))
        assert check.code is None and check.data["status"] == "conflict"
        conflict_draft = await failed.execute(
            context,
            "stage_plan_change",
            {
                "change": {"kind": "initial", "proposal": closed.model_dump(mode="json")},
            },
        )
        assert conflict_draft.code is None
        validation = conflict_draft.data["validation"]
        assert isinstance(validation, dict) and validation["status"] == "conflict"
        with pytest.raises(ServiceError, match="硬冲突") as error:
            await failed.plans.confirm(context.user_id, UUID(str(conflict_draft.data["draft_id"])))
        assert error.value.code == "conflict"
        async with transaction(travel.database) as db:
            plan = await plans.for_session(db, context)
            assert plan is not None and str(plan.id) == staged.data["plan_id"]
            assert plan.current_version == 0  # 模型暂存/对照均不能正式确认。

    runner.run(exercise())


@pytest.mark.skipif(not shutil.which("claude"), reason="实际CLI，本机API脚本不访问模型")
def test_no_repairs_actual_sdk_receives_conflict_then_blocked_repair(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
) -> None:
    runner, travel, context = travel_setup
    first, _ = runner.run(destinations(travel, context))
    arguments = proposal(first, closed=True).model_dump(mode="json")
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
            value = results[-1]
            feedback.append(json.loads(value if isinstance(value, str) else value[0]["text"]))
            if feedback[-1]["status"] == "error":
                return scripted_response(body)
        status, response = scripted_response(
            json.dumps({**request, "messages": []}).encode(),
            tool_calls=((sdk_tool_name("validate_itinerary"), arguments),),
        )
        return status, response.replace(b'"tool_0"', f'"variant_{len(results)}"'.encode())

    report, guard = run_database_worker(
        travel, context, tmp_path, forward, "检查闭馆冲突", variant="no_repairs"
    )
    assert report["status"] == "success" and guard.attempts == 3 and not guard.failures
    assert len(feedback) == 2
    data = feedback[0]["data"]
    assert isinstance(data, dict) and data["status"] == "conflict"
    assert data["repair_rounds_remaining"] == 0
    error = feedback[1]["error"]
    assert isinstance(error, dict) and error["code"] == "blocked"
    assert report["checkpoint_persisted"] is False


@pytest.mark.skipif(not shutil.which("claude"), reason="实际CLI；人工usage只核验原生机制")
@pytest.mark.parametrize("variant", ["full", "no_compaction", "baseline_b2"])
def test_native_compaction_control_with_same_usage_and_trip(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    variant: EvaluationVariant,
) -> None:
    runner, travel, context = travel_setup
    before = runner.run(travel.get_request(context))
    count = 0

    def forward(body: bytes) -> tuple[int, bytes]:
        nonlocal count
        count += 1
        request = json.loads(body)
        if count == 1:
            status, content = scripted_response(
                json.dumps({**request, "messages": []}).encode(),
                tool_calls=((sdk_tool_name("load_skill"), {"name": "hotel-comparison"}),),
            )
            # 两配置完全相同的人工usage/阈值；不当真实token/模型摘要质量。
            return status, content.replace(b'"input_tokens": 100', b'"input_tokens": 40000')
        return scripted_response(
            json.dumps(
                {
                    **request,
                    "messages": [
                        {
                            "content": [
                                {"type": "tool_result", "content": "synthetic summary or answer"}
                            ]
                        }
                    ],
                }
            ).encode()
        )

    report, guard = run_database_worker(
        travel,
        context,
        tmp_path,
        forward,
        "读取酒店比较步骤",
        variant=variant,
        max_attempts=6,
        auto_compact_percent=5,
    )
    assert report["status"] == "success" and not guard.failures, (
        report.get("code"),
        report.get("reason"),
        guard.attempts,
        guard.failures,
    )
    events = TypeAdapter(list[RuntimeEvent]).validate_python(report["events"])
    compacted = sum(e.kind == "context_compacted" for e in events)
    if variant == "full":
        assert compacted >= 1 and guard.attempts > 2
    else:
        assert compacted == 0 and guard.attempts == 2
        assert report["checkpoint_persisted"] is False
    assert any(e.kind == "tool_finished" and e.code is None for e in events)
    assert runner.run(travel.get_request(context)) == before
