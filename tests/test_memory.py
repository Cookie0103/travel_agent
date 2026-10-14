"""闭合记忆操作和引用来源；用户原文规范化不允许工具文本混入。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.memory import MemoryOperation, quote_matches, quote_source_valid
from backend.tools.travel import DEFINITIONS


def test_quote_matching_normalizes_width_and_whitespace_but_requires_substring() -> None:
    assert quote_matches("我喜欢ＡＢＣ　和公共交通", "ABC 和公共交通")
    assert not quote_matches("我只想去京都", "喜欢奢华酒店")


@pytest.mark.parametrize(
    ("prompt", "quote", "expected"),
    [
        ("我喜欢ＡＢＣＤ的画", "ABCD", True),
        ("我喜欢特种兵旅行", "特种兵", False),
        ("特　种 兵", "特种兵", True),
        ("京都酒店", "    ", False),
    ],
)
def test_quote_source_applies_normalized_length_and_whole_message_exception(
    prompt: str, quote: str, expected: bool
) -> None:
    assert quote_source_valid(prompt, quote) is expected


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
