"""F6：同义修饰可匹配，否定方向与封闭值不可被归一化抹去。"""

import pytest

from eval.memory_metrics import matches


@pytest.mark.parametrize(
    ("key", "value", "core", "expected"),
    [
        ("avoid", "避免长距离步行", "长距离步行", True),
        ("avoid", "不喜欢早起（行程不要安排早起）", "早起", True),
        ("dietary", "只在这次旅行吃素", "吃素", True),
        ("dietary", "本次旅行吃素", "吃素", True),
        ("dietary", "不想吃素", "吃素", False),
        ("dietary", "不吃素", "吃素", False),
        ("dietary", "不 吃素", "吃素", False),
        ("avoid", "喜欢早起", "早起", False),
        ("avoid", "不想避免早起", "早起", False),
        ("avoid", "不要避免早起", "早起", False),
        ("interest", "不喜欢早起", "早起", False),
        ("pace", "特种兵式旅行", "特种兵", False),
        ("transport", "公共交通", "transit", False),
    ],
)
def test_alias_polarity_and_closed_values(key: str, value: str, core: str, expected: bool) -> None:
    gold = {"key": key, "scope": "trip", "op": "ADD", "values": [core]}
    prediction = {"key": key, "scope": "trip", "op": "ADD", "value": value}
    assert matches(gold, prediction) is expected
