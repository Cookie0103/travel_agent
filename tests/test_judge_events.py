"""内容参考分的事件输入仅含封闭事实，阈值不成为任务通过门槛。"""

import json
from uuid import uuid4

import pytest

from backend.agent.persona import CONTENT_RUBRIC
from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.external_data import ExternalAttempt
from eval.content import QualityScore
from eval.event_summary import event_summary
from eval.judge import judge_input
from eval.persona import Sample, content_reference


def test_content_input_retains_event_facts_but_not_body_or_card_text() -> None:
    context = RunContext(uuid4())
    summary = event_summary(
        (
            RuntimeEvent(context, "text", text="private-body"),
            RuntimeEvent(
                context,
                "tool_finished",
                tool_name="search_hotel_offers",
                choice_card="none",
                external=ExternalAttempt(attempts=2),
                data_mode="synthetic",
            ),
            RuntimeEvent(
                context,
                "presentation",
                presentation={
                    "data": {
                        "component": "choice",
                        "kind": "memory_confirm",
                        "question": "private-quote",
                    }
                },
            ),
        )
    )
    sample = Sample(case_id="case", user_input="需求", text="回答", event_summary=summary)
    payload = judge_input(sample, kind="content")
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "private-body" not in encoded and "private-quote" not in encoded
    assert "search_hotel_offers" in encoded and "synthetic" in encoded
    assert summary.memory_card is True and summary.budget_card is False
    assert summary.tools[0].attempts == 2 and summary.tools[0].choice_card == "none"
    assert "event_summary" not in judge_input(sample, kind="persona")
    assert event_summary(None).budget_card is None


def test_content_reference_threshold_configurable_without_task_pass_field() -> None:
    quality = QualityScore(relevance=3, explanation=3, tradeoffs=3, reason="参考")
    default = content_reference(quality)
    assert default["title"] == "未校准参考分" and default["binary_reference"] is True
    assert content_reference(quality, threshold=4)["binary_reference"] is False
    assert default["threshold"] == 3 and default["task_pass_gate"] is False
    assert "passed" not in default and "status" not in default
    for bad in (0, 6, True):
        with pytest.raises(ValueError):
            content_reference(quality, threshold=bad)


def test_content_rubric_caps_unsupported_and_contradictory_explanation() -> None:
    assert "事件不支持的说法时，explanation ≤ 2" in CONTENT_RUBRIC
    assert "回答前后矛盾时，explanation ≤ 2" in CONTENT_RUBRIC
    assert "未校准参考分" in CONTENT_RUBRIC


def test_actual_tool_source_reaches_the_judge_and_persistent_metadata() -> None:
    import asyncio

    from backend.domain.execution import event_metadata
    from backend.tools.contracts import ToolResult
    from backend.tools.execution import execute_observed
    from backend.tools.travel import DEFINITIONS
    from tests.test_external_tool_recovery import SyntheticExecutor

    async def exercise() -> None:
        executor = SyntheticExecutor()
        executor.responses = [ToolResult({}, data_mode="synthetic")]
        events: list[RuntimeEvent] = []
        definition = next(d for d in DEFINITIONS if d.name == "search_places")
        await execute_observed(
            executor,
            RunContext(uuid4()),
            "search_places",
            {"city": "京都"},
            events.append,
            definition=definition,
        )
        projected = tuple(event_metadata(e) for e in events)
        assert event_summary(projected).tools[0].data_mode == "synthetic"

    asyncio.run(exercise())


def test_multiturn_reference_uses_only_last_answer_events_or_unknown() -> None:
    from eval.calibration import row_event_summary

    first = RunContext(uuid4())
    last = RunContext(first.user_id, first.session_id)
    events = (
        RuntimeEvent(
            first,
            "presentation",
            presentation={"data": {"component": "choice", "kind": "budget_relaxation"}},
        ),
        RuntimeEvent(last, "tool_finished", tool_name="search_hotel_offers", choice_card="none"),
    )
    row: dict[str, object] = {
        "text": "最后回答",
        "dialogue": [
            {"status": "completed", "answer": "第一轮", "session_id": str(first.session_id)},
            {"status": "completed", "answer": "最后回答", "session_id": str(last.session_id)},
        ],
    }
    summary = row_event_summary(row, events)
    assert summary.budget_card is False and len(summary.tools) == 1
    wrong = {**row, "text": "未绑定的其他回答"}
    assert row_event_summary(wrong, events).budget_card is None
    assert row_event_summary(row, events[:1]).budget_card is None
    positive = row_event_summary({"text": "第一轮", "dialogue": row["dialogue"][:1]}, events[:1])
    assert positive.budget_card is True
