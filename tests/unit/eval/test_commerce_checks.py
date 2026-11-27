"""检查集固定种子以及模板、酒店组的隔离。"""

from data.eval_world.world import load_world
from eval.commerce.checks import KINDS, generate, load_cases


def test_synthetic_checks_can_be_recreated_and_hold_out_entire_templates_and_groups() -> None:
    world, _ = load_world()
    rows = load_cases()
    assert generate(world) == rows
    training = tuple(case for case in rows if case.split == "tune")
    heldout = tuple(case for case in rows if case.split == "accept")
    assert (len(training), len(heldout)) == (108, 72)
    assert {case.kind for case in training} == {case.kind for case in heldout} == set(KINDS)
    assert {case.template for case in training}.isdisjoint(case.template for case in heldout)
    assert {case.group for case in training}.isdisjoint(case.group for case in heldout)
    assert {hotel.id for case in training for hotel in case.first}.isdisjoint(
        hotel.id for case in heldout for hotel in case.first
    )
