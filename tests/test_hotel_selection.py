"""酒店覆盖与套餐上限，保ID边界/未知数量与上游顺序。"""

import pytest

from backend.domain.hotel_selection import hotel_rate_indices


def test_first_quotes_cover_hotels_before_optional_second_packages() -> None:
    keys = [
        ("A", "a1"),
        ("A", "a2"),
        ("A", "a3"),
        ("B", "b1"),
        ("C", "c1"),
        ("D", "d1"),
        ("E", "e1"),
    ]
    assert hotel_rate_indices(keys, 4) == (0, 1, 3, 4, 5)
    assert hotel_rate_indices(keys, 6) == (0, 1, 3, 4, 5, 6)


def test_duplicate_rates_do_not_consume_slots_and_insufficient_hotels_stay_insufficient() -> None:
    assert hotel_rate_indices([("A", "x"), ("A", "x"), ("A", "y"), ("A", "z")], 4) == (0, 2)
    assert hotel_rate_indices([], 4) == ()
    assert hotel_rate_indices([("A", "x"), ("B", "x")], 2) == (0, 1)


@pytest.mark.parametrize("limit", [0, 7, -1])
def test_outside_existing_limits_rejected(limit: int) -> None:
    with pytest.raises(ValueError):
        hotel_rate_indices([], limit)
