"""合法上下文读取不等于查到酒店；V2空结果评分与旧suite语义区分。"""

from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from backend.domain.execution import RunContext, RuntimeEvent
from eval.cases import Case
from eval.graders import Observation, grade


@pytest.mark.parametrize("code", [None, "rate_limited", "validation"])
def test_context_result_does_not_count_as_hotel_results(code: str | None) -> None:
    context = RunContext(uuid4())
    first, second = uuid4(), uuid4()
    case = Case.model_validate(
        {
            "case_id": "v2-no-hotels",
            "input": "查酒店",
            "source": "self-authored",
            "adaptation": "scope control",
            "required_tools": ["search_hotel_offers"],
            "allowed_tools": ["get_business_context", "search_hotel_offers"],
            "result_tools": ["search_hotel_offers"],
            "should_have_results": False,
        }
    )
    events = (
        RuntimeEvent(context, "tool_started", tool_name="get_business_context", tool_call_id=first),
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="get_business_context",
            tool_call_id=first,
            result_empty=False,
        ),
        RuntimeEvent(context, "tool_started", tool_name="search_hotel_offers", tool_call_id=second),
        TypeAdapter(RuntimeEvent).validate_python(
            {
                "context": context,
                "kind": "tool_finished",
                "tool_name": "search_hotel_offers",
                "tool_call_id": second,
                "code": code,
                "result_empty": True,
            }
        ),
    )
    assert (
        grade(case, Observation("completed", "酒店无候选；说明已尝试的步骤", events))["has_results"]
        is True
    )
