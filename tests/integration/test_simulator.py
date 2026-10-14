"""无动作/无交付的实际PG终态不能被E7判为通过；trace创建前固定。"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy import URL

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.limits import ProbeError
from backend.persistence import runs
from backend.persistence.temporary import temporary_database
from backend.providers.claude_agent.application import GuardedRuntime
from backend.services.common import transaction
from eval.database import DatabaseEvaluation, database_evaluation, selector_runner
from eval.simulator import SCENARIOS, trial

pytestmark = pytest.mark.integration


def test_empty_completed_answers_fail_all_goals_and_trace_is_already_anchored(
    postgres_url: URL, tmp_path: Path
) -> None:
    anchored: list[str] = []
    businesses: list[DatabaseEvaluation] = []
    anchors: list[str] = []

    async def execute(
        self: GuardedRuntime,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        async with transaction(businesses[0].sessions.database) as db:
            row = await runs.owned(db, context.user_id, context.run_id)
            assert row and row.trace_id == anchors[0]
            anchored.append(row.trace_id)
        return RuntimeOutcome(
            text="你没说喜欢特种兵，没有长期资料但你通常独自出行。", sdk_session_id="synthetic"
        )

    with temporary_database(postgres_url, "eval") as url, selector_runner() as runner:

        async def exercise() -> None:
            async with database_evaluation(url) as business:
                businesses.append(business)
                provider = TracerProvider(shutdown_on_exit=False)
                try:
                    with provider.get_tracer("test").start_as_current_span(
                        "evaluation.trial"
                    ) as root:
                        trace_id = format(root.get_span_context().trace_id, "032x")
                        anchors.append(trace_id)
                        with (
                            patch.object(GuardedRuntime, "execute", execute),
                            patch(
                                "eval.simulator.structured_call",
                                return_value=('{"kind":"done","text":"结束"}', {}),
                            ),
                        ):
                            for scenario in SCENARIOS:
                                result = await trial(
                                    business, scenario, 1, tmp_path, False, trace_id
                                )
                                assert result["status"] == "failed", scenario.case_id
                                checks = result["checks"]
                                assert isinstance(checks, dict) and checks["completed_runs"] is True
                finally:
                    provider.shutdown()

        runner.run(exercise())
    assert len(anchored) == 8


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (
            '{"kind":"choice","text":"选择","choice_id":"bad","option_id":"keep","api_key":"sk-simulator-private-value"}',
            "invalid_simulator_output",
        ),
        (
            '{"kind":"choice","text":"选择","choice_id":"00000000-0000-0000-0000-000000000001","option_id":"keep"}',
            "choice_missing",
        ),
    ],
)
def test_controller_failure_preserves_redacted_output_and_rejected_action(
    postgres_url: URL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: str, reason: str
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-simulator-private-value")

    async def execute(
        self: GuardedRuntime,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        return RuntimeOutcome(text="合成回复", sdk_session_id="synthetic")

    with temporary_database(postgres_url, "eval") as url, selector_runner() as runner:

        async def exercise() -> None:
            async with database_evaluation(url) as business:
                with (
                    patch.object(GuardedRuntime, "execute", execute),
                    patch("eval.simulator.structured_call", return_value=(response, {})),
                ):
                    result = await trial(
                        business, SCENARIOS[1], 1, tmp_path, False, "synthetic-trace"
                    )
                failure = result["controller_failure"]
                assert isinstance(failure, dict) and failure["reason"] == reason
                raw = failure["raw_simulator_output"]
                rejected = failure["rejected_action"]
                assert isinstance(raw, str) and len(raw.encode("utf-8")) <= 2048
                assert isinstance(rejected, str) and '"kind"' in rejected
                assert "sk-simulator-private-value" not in raw + rejected
                assert result["status"] == "failed"
                dialogue = result["dialogue"]
                assert isinstance(dialogue, list) and isinstance(dialogue[0], dict)
                assert dialogue[0]["run_id"]
                assert dialogue[0]["answered_at"]

        runner.run(exercise())


def test_unavailable_simulator_keeps_the_finished_turn_and_failure_reason(
    postgres_url: URL, tmp_path: Path
) -> None:
    async def execute(
        self: GuardedRuntime,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        return RuntimeOutcome(text="合成回复", sdk_session_id="synthetic")

    with temporary_database(postgres_url, "eval") as url, selector_runner() as runner:

        async def exercise() -> None:
            async with database_evaluation(url) as business:
                with (
                    patch.object(GuardedRuntime, "execute", execute),
                    patch(
                        "eval.simulator.structured_call",
                        side_effect=ProbeError("blocked", "private-error"),
                    ),
                ):
                    result = await trial(
                        business, SCENARIOS[1], 1, tmp_path, False, "synthetic-trace"
                    )
                assert result["status"] == "failed"
                assert result["error"] == "ProbeError"
                details = result["controller_failure"]
                assert isinstance(details, dict) and details["reason"] == "simulator_unavailable"
                assert details["raw_simulator_output"] is None
                assert details["rejected_action"] is None
                assert "private-error" not in json.dumps(result, default=str)
                assert isinstance(result["dialogue"], list) and len(result["dialogue"]) == 1

        runner.run(exercise())
