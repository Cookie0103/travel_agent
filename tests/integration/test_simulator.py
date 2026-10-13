"""无动作/无交付的实际PG终态不能被E7判为通过；trace创建前固定。"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy import URL

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeOutcome
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
