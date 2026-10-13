"""模型分诊只能输出闭合标签与已存在步骤，不算准确率或确定根因。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.execution import RunContext, RuntimeEvent
from eval.triage import Triage, compact_steps, validate_triage


def test_triage_compacts_events_without_text_arguments_or_private_names() -> None:
    context = RunContext(uuid4())
    steps = compact_steps(
        (
            RuntimeEvent(context, "text", text="private-text"),
            RuntimeEvent(context, "tool_started", tool_name="search_hotel_offers"),
        )
    )
    assert "private-text" not in str(steps) and len(steps) == 1
    assert validate_triage('{"first_step":0,"label":"wrong_tool"}', steps).first_step == 0
    with pytest.raises(ValueError):
        validate_triage('{"first_step":2,"label":"wrong_tool"}', steps)
    with pytest.raises(ValidationError):
        Triage.model_validate({"first_step": 0, "label": "private-freeform-label"})
