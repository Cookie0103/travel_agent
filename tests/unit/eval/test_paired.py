"""对已知差异和无差异的精确二项式分布验收。"""

from math import comb

import pytest

from eval.core.paired import Trial, compare, mcnemar, stability


def test_paired_repeats_and_seed_groups_use_question_level_evidence() -> None:
    a = [
        Trial(f"q{i}", repeat, i >= 24, float(i >= 24), f"seed{i // 3}")
        for i in range(36)
        for repeat in (1, 2, 3)
    ]
    b = [Trial(row.case_id, row.repeat, True, row.score + 0.5, row.seed_id) for row in a]
    outcome = compare(a, b, draws=300)
    assert (outcome.cases, outcome.trials, outcome.clusters) == (36, 108, 12)
    assert outcome.b_only == 24 and outcome.a_only == 0
    assert outcome.mcnemar_p < 0.05 and outcome.pass_rate.low > 0
    assert outcome.score.mean == pytest.approx(0.5)
    assert stability(0.5, [0.1] * 9 + [-0.1]) == (0.9, True)
    assert stability(0.5, [0.1] * 8 + [-0.1, 0]) == (0.8, False)


def test_exact_mcnemar_false_positive_rate_is_near_nominal() -> None:
    # 100 个无方向偏好的不一致题，精确枚举零假设分布。
    total = 100
    rejected = sum(comb(total, n) for n in range(total + 1) if mcnemar(n, total - n) < 0.05)
    expect = rejected / 2**total
    assert 0.03 <= expect <= 0.05
