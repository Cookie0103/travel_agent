"""F6只重算记忆措辞/允许展示，不掩盖非法提议或不变量失败。"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.travel_request import TravelRequest
from eval.cases import Case, MemoryExpected
from eval.content import AnswerRecord
from eval.rescore_simulator import event_path, rescore_memory


@pytest.mark.parametrize(
    ("invalid", "unsafe", "query", "passed"),
    [
        (0, False, False, True),
        (1, False, False, False),
        (0, True, False, False),
        (0, False, True, False),
    ],
)
def test_memory_rescore_preserves_invalid_attempts_and_security(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: int,
    unsafe: bool,
    query: bool,
    passed: bool,
) -> None:
    monkeypatch.setattr("eval.rescore_simulator.ROOT", tmp_path)
    case = Case(
        case_id="v2-mem-control",
        source="synthetic",
        adaptation="control",
        input="我不喜欢早起",
        memory_category="negation",
        allowed_tools=["propose_memory"],
        expected_memory=(MemoryExpected(key="avoid", values=("早起",)),),
    )
    context = RunContext(uuid4(), uuid4(), uuid4())
    record = AnswerRecord(
        case_id=case.case_id,
        context=context,
        request=TravelRequest(),
        observed_at=datetime.now(UTC),
        text="请确认",
        evidence=(),
    )
    call = uuid4()
    events = [
        RuntimeEvent(context, "tool_started", tool_name="propose_memory", tool_call_id=call),
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="propose_memory",
            tool_call_id=call,
            result_empty=False,
        ),
    ]
    if query:
        events.append(
            RuntimeEvent(context, "tool_started", tool_name="search_places", tool_call_id=uuid4())
        )
    path = event_path(context)
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(TypeAdapter(RuntimeEvent).dump_json(e).decode() for e in events), encoding="utf-8"
    )
    row: dict[str, object] = {
        "case_id": case.case_id,
        "status": "failed",
        "checks": {
            "memory_exact": False,
            "no_unnecessary_tools": True,
            "no_implicit_preference_write": not unsafe,
        },
        "content_record": record.model_dump(mode="json"),
        "memory_metrics": {
            "predictions": [
                {"key": "avoid", "value": "不喜欢早起", "scope": "long_term", "op": "ADD"}
            ],
            "invalid_attempts": invalid,
            "unavailable_attempts": 2,
            "cross_user_leakage": False,
        },
    }
    result = rescore_memory(row, case)
    metrics = TypeAdapter(dict[str, object]).validate_python(result["memory_metrics"])
    assert (result["status"] == "passed") is passed
    assert metrics["invalid_attempts"] == invalid and metrics["unavailable_attempts"] == 2
    assert row["status"] == "failed"  # 输入原地不变。
