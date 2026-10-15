"""F6：只允许成功提议之后展示同一张本轮记忆卡，不扩大到查询或任意展示。"""

from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from eval.cases import Case
from eval.graders import Observation, grade


def events(
    *, kind: str = "memory_confirm", present_first: bool = False
) -> tuple[RuntimeEvent, ...]:
    context = RunContext(uuid4(), uuid4(), uuid4())
    proposal, display = uuid4(), uuid4()
    data = {"component": "choice", "kind": "memory_confirm", "choice_id": "owned-card"}
    before = (
        RuntimeEvent(context, "tool_started", tool_name="propose_memory", tool_call_id=proposal),
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="propose_memory",
            tool_call_id=proposal,
            result_empty=False,
        ),
        RuntimeEvent(
            context,
            "presentation",
            tool_name="propose_memory",
            tool_call_id=proposal,
            presentation={"data": data},
        ),
    )
    after = (
        RuntimeEvent(
            context, "tool_started", tool_name="present_travel_result", tool_call_id=display
        ),
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="present_travel_result",
            tool_call_id=display,
            result_empty=False,
        ),
        RuntimeEvent(
            context,
            "presentation",
            tool_name="present_travel_result",
            tool_call_id=display,
            presentation={"data": {**data, "kind": kind}},
        ),
    )
    return (*after, *before) if present_first else (*before, *after)


@pytest.mark.parametrize(
    ("kind", "first", "expected"),
    [
        ("memory_confirm", False, True),
        ("budget_relaxation", False, False),
        ("memory_confirm", True, False),
    ],
)
def test_only_owned_memory_presentation_after_proposal_is_allowed(
    kind: str, first: bool, expected: bool
) -> None:
    case = Case(
        case_id="v2-mem-test",
        source="synthetic",
        adaptation="control",
        input="记住偏好",
        memory_category="extraction",
        required_tools=["propose_memory"],
        allowed_tools=["propose_memory"],
        should_have_results=True,
    )
    actual = Observation("completed", "请确认记忆", events(kind=kind, present_first=first))
    assert grade(case, actual)["no_unnecessary_tools"] is expected
