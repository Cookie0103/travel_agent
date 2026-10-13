"""闭合记忆操作和引用来源；用户原文规范化不允许工具文本混入。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.memory import MemoryOperation, quote_matches
from backend.tools.travel import DEFINITIONS


def test_quote_matching_normalizes_width_and_whitespace_but_requires_substring() -> None:
    assert quote_matches("我喜欢ＡＢＣ　和公共交通", "ABC 和公共交通")
    assert not quote_matches("我只想去京都", "喜欢奢华酒店")


def test_model_visible_memory_schema_explains_key_specific_values() -> None:
    definition = next(d for d in DEFINITIONS if d.name == "propose_memory")
    definitions = definition.schema["$defs"]
    assert isinstance(definitions, dict)
    schema = definitions["MemoryOperation"]["properties"]["value"]
    description = schema.get("description", "")
    assert all(
        word in description
        for word in ("pace", "特种兵", "transport", "transit", "companion_pattern", "solo")
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"key": "system_prompt"},
        {"value": "任意节奏"},
        {"op": "CONFIRM"},
        {"op": "UPDATE"},
        {"target_fact_id": str(uuid4())},
    ],
)
def test_memory_operations_reject_open_keys_values_and_missing_targets(
    bad: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        MemoryOperation.model_validate(
            {
                "op": "ADD",
                "key": "pace",
                "value": "特种兵",
                "scope": "long_term",
                "quote": "喜欢特种兵",
                **bad,
            }
        )
