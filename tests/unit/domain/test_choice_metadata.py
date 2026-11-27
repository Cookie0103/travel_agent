"""choice事件只保留服务端选择字段，其他正文和选项附带字段不持久化。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.execution import RunContext, RuntimeEvent, event_metadata
from backend.tools.travel import PresentationInput


def test_choice_metadata_removes_unknown_fields_inside_options() -> None:
    choice_id = str(uuid4())
    event = RuntimeEvent(
        RunContext(uuid4()),
        "presentation",
        text="private",
        presentation={
            "data": {
                "component": "choice",
                "choice_id": choice_id,
                "kind": "pace",
                "question": "旅行节奏",
                "options": [
                    {
                        "option_id": "relaxed",
                        "label": "比较轻松",
                        "value": "慢节奏",
                        "supplier_body": "private",
                    }
                ],
                "unknown_body": "private",
            }
        },
    )
    metadata = event_metadata(event)
    assert metadata.text == "" and "private" not in str(metadata.presentation)
    assert metadata.presentation and metadata.presentation["data"] == {
        "component": "choice",
        "choice_id": choice_id,
        "kind": "pace",
        "question": "旅行节奏",
        "options": [{"option_id": "relaxed", "label": "比较轻松", "value": "慢节奏"}],
    }


def test_model_cannot_supply_options_or_unknown_choice_kind() -> None:
    for extra in ({"options": [{"label": "任意选项"}]}, {"kind": "invented"}):
        with pytest.raises(ValidationError):
            PresentationInput.model_validate(
                {"component": "choice", "kind": "pace", "expected_revision": 1, **extra}
            )
