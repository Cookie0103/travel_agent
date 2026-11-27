"""同题同重复的配对比较，聚类区间与通过事件的不一致对。"""

import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import mean

DEFAULT_SEED = 20261127


@dataclass(frozen=True)
class Trial:
    case_id: str
    repeat: int
    passed: bool
    score: float
    seed_id: str | None = None


@dataclass(frozen=True)
class Difference:
    mean: float
    low: float
    high: float


@dataclass(frozen=True)
class Comparison:
    cases: int
    trials: int
    clusters: int
    a_pass_all: float
    b_pass_all: float
    b_only: int
    a_only: int
    mcnemar_p: float
    pass_rate: Difference
    score: Difference


def mcnemar(b_only: int, a_only: int) -> float:
    """双侧精确二项式检验，只用不一致的题，不假设正态逼近。"""
    if min(b_only, a_only) < 0:
        raise ValueError("配对计数不得为负")
    count = b_only + a_only
    tail = sum(math.comb(count, k) for k in range(min(b_only, a_only) + 1))
    return min(1.0, float(2 * tail / 2**count))


def _index(trials: Iterable[Trial]) -> dict[tuple[str, int], Trial]:
    index = {}
    for trial in trials:
        key = trial.case_id, trial.repeat
        if key in index or not trial.case_id or trial.repeat < 1 or not math.isfinite(trial.score):
            raise ValueError("配对记录重复或试验标识/分数无效")
        index[key] = trial
    return index


def _interval(original: float, resamples: list[float], alpha: float) -> Difference:
    resamples.sort()
    last = len(resamples) - 1
    return Difference(
        original,
        resamples[math.floor(last * alpha / 2)],
        resamples[math.ceil(last * (1 - alpha / 2))],
    )


def compare(
    a: Iterable[Trial],
    b: Iterable[Trial],
    *,
    draws: int = 2000,
    seed: int = DEFAULT_SEED,
    alpha: float = 0.05,
) -> Comparison:
    left, right = _index(a), _index(b)
    if not left or left.keys() != right.keys() or draws < 1 or not 0 < alpha < 1:
        raise ValueError("配对两边须有相同试验，抽样次数与置信水平须有效")

    pairs: dict[str, list[tuple[Trial, Trial]]] = {}
    for key in sorted(left):
        x, y = left[key], right[key]
        if x.seed_id != y.seed_id:
            raise ValueError("同题配对的种子归属不同")
        pairs.setdefault(x.case_id, []).append((x, y))
    cluster: dict[str, list[tuple[float, float]]] = {}
    a_all = b_all = a_only = b_only = 0
    for case_id, observations in pairs.items():
        origins = {x.seed_id for x, _ in observations}
        if len(origins) != 1:
            raise ValueError("同题多次试验必须来自同一种子")
        group = next(iter(origins)) or case_id
        truth_a, truth_b = (
            all(x.passed for x, _ in observations),
            all(y.passed for _, y in observations),
        )
        a_all += truth_a
        b_all += truth_b
        a_only += truth_a and not truth_b
        b_only += truth_b and not truth_a
        cluster.setdefault(group, []).append(
            (
                mean(int(y.passed) - int(x.passed) for x, y in observations),
                mean(y.score - x.score for x, y in observations),
            )
        )

    groups = [
        (len(rows), sum(x for x, _ in rows), sum(y for _, y in rows)) for rows in cluster.values()
    ]
    case_count = len(pairs)
    pass_diff = sum(group[1] for group in groups) / case_count
    score_diff = sum(group[2] for group in groups) / case_count
    rng = random.Random(seed)
    passes, scores = [], []
    for _ in range(draws):
        sampled = rng.choices(groups, k=len(groups))
        divisor = sum(group[0] for group in sampled)
        passes.append(sum(group[1] for group in sampled) / divisor)
        scores.append(sum(group[2] for group in sampled) / divisor)
    return Comparison(
        cases=case_count,
        trials=len(left),
        clusters=len(groups),
        a_pass_all=a_all / case_count,
        b_pass_all=b_all / case_count,
        b_only=b_only,
        a_only=a_only,
        mcnemar_p=mcnemar(b_only, a_only),
        pass_rate=_interval(pass_diff, passes, alpha),
        score=_interval(score_diff, scores, alpha),
    )


def stability(reference_delta: float, platform_deltas: Sequence[float]) -> tuple[float, bool]:
    if not platform_deltas or not all(
        math.isfinite(x) for x in (*platform_deltas, reference_delta)
    ):
        raise ValueError("结论稳定度需要有限的参考差值与平台区差值")
    direction = (reference_delta > 0) - (reference_delta < 0)
    fraction = sum((delta > 0) - (delta < 0) == direction for delta in platform_deltas) / len(
        platform_deltas
    )
    return fraction, direction != 0 and fraction >= 0.9
