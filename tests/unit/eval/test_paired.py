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


def test_cluster_bootstrap_false_positive_rate_is_near_nominal() -> None:
    # 零假设下每个种子的方向独立且等概率，一个种子的三道题完全相关。
    # 对正向种子个数按精确二项概率加权，避免外层模拟的抽样波动。
    clusters = 24
    pass_rejections = score_rejections = 0
    for positive in range(clusters + 1):
        directions = tuple(index < positive for index in range(clusters))
        before = [
            Trial(f"{index}-{case}", 1, not up, float(not up), f"seed-{index}")
            for index, up in enumerate(directions)
            for case in range(3)
        ]
        after = [
            Trial(row.case_id, 1, not row.passed, 1 - row.score, row.seed_id) for row in before
        ]
        result = compare(before, after, draws=600)
        weight = comb(clusters, positive)
        if not result.pass_rate.low <= 0 <= result.pass_rate.high:
            pass_rejections += weight
        if not result.score.low <= 0 <= result.score.high:
            score_rejections += weight
    assert 0.03 <= pass_rejections / 2**clusters <= 0.07
    assert 0.03 <= score_rejections / 2**clusters <= 0.07
