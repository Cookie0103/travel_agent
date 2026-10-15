"""R15：建议区间轻偏离/极端异常，以及旧单城报告完全不变。"""

from datetime import timedelta

import pytest

from backend.domain.validator import visit_checks
from tests.test_itinerary import place
from tests.test_multi_city_itinerary import multi_city_example


@pytest.mark.parametrize(
    "category,minutes,expected",
    [
        ("museum", 15, "conflict"),
        ("museum", 40, "unknown"),
        ("museum", 22.5, "unknown"),
        ("museum", 45, None),
        ("museum", 180, None),
        ("museum", 360, "unknown"),
        ("museum", 361, "conflict"),
        ("shrine", 360, "conflict"),
        ("art_gallery", 30, "unknown"),
        ("historical_place", 60, None),
        ("park", 60, None),
        ("viewpoint", 60, None),
        ("zoo", 60, "unknown"),
        ("theme_park", 60, "conflict"),
        ("shopping_mall", 15, "unknown"),
        ("attraction", 60, None),
        ("hotel", 600, None),
        ("restaurant", 600, None),
        ("train_station", 600, None),
        ("unknown", 600, None),
    ],
)
def test_sightseeing_duration_uses_advisory_ranges_and_strict_extreme_boundaries(
    category: str, minutes: float, expected: str | None
) -> None:
    current, proposal, _ = multi_city_example()
    target = proposal.items[0].model_copy(
        update={"end": proposal.items[0].start + timedelta(minutes=minutes)}
    )
    proposal = proposal.model_copy(update={"items": (target,)})
    destination = place().model_copy(update={"city": "大阪", "category": category})
    durations = [
        c
        for c in visit_checks(current, proposal, 0, destination)
        if c.code == "visit_duration_range"
    ]
    assert [c.status for c in durations] == ([] if expected is None else [expected])
    assert all("建议" in c.message for c in durations)


def test_missing_place_does_not_invent_a_category_duration() -> None:
    current, proposal, _ = multi_city_example()
    assert not any(
        c.code == "visit_duration_range" for c in visit_checks(current, proposal, 0, None)
    )


def test_legacy_single_city_extreme_duration_keeps_original_checks() -> None:
    current, proposal, _ = multi_city_example()
    current = current.model_copy(update={"segments": None})
    target = proposal.items[0].model_copy(
        update={"end": proposal.items[0].start + timedelta(minutes=15)}
    )
    proposal = proposal.model_copy(update={"items": (target,)})
    destination = place().model_copy(update={"city": "大阪", "category": "museum"})
    assert not any(
        c.code == "visit_duration_range" for c in visit_checks(current, proposal, 0, destination)
    )
