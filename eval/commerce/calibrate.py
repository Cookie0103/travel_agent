"""按全局抽样、平台区与收缩规则验收商业评分先验。"""

import argparse
import hashlib
import json
import math
import random
from collections.abc import Sequence
from pathlib import Path
from statistics import mean

from data.eval_world.world import WorldSource, load_world
from eval.commerce.checks import DEFAULT_CHECKS, Comparison, generate, load_cases, passes
from eval.commerce.parameters import Prior, Registry, load_parameters

SEED = 20261129
SAMPLES = 2000
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / ".cache" / "eval-commerce" / "provisional-calibration"
type Axis = tuple[str, str]


def axes(registry: Registry) -> dict[Axis, Prior]:
    return {
        **{("prior", name): item for name, item in registry.priors.items()},
        **{
            (persona, name): item
            for persona, weights in registry.persona_multipliers.items()
            for name, item in weights.items()
        },
        **{("soft_item", name): item for name, item in registry.soft_items.items()},
    }


def latin_hypercube(dimensions: dict[Axis, Prior], size: int, seed: int) -> list[dict[Axis, float]]:
    rng = random.Random(seed)
    rows: list[dict[Axis, float]] = [{} for _ in range(size)]
    for axis, item in dimensions.items():
        low, high = item.bounds
        strata = list(range(size))
        rng.shuffle(strata)
        for row, stratum in zip(rows, strata, strict=True):
            row[axis] = low + (high - low) * (stratum + rng.random()) / size
    return rows


def candidate(prior: Registry, values: dict[Axis, float]) -> Registry:
    def apply(group: str, source: dict[str, Prior]) -> dict[str, Prior]:
        return {
            name: item.model_copy(update={"value": values[(group, name)]})
            for name, item in source.items()
        }

    return prior.model_copy(
        update={
            "priors": apply("prior", prior.priors),
            "persona_multipliers": {
                persona: apply(persona, weights)
                for persona, weights in prior.persona_multipliers.items()
            },
            "soft_items": apply("soft_item", prior.soft_items),
        }
    )


def check_count(cases: Sequence[Comparison], registry: Registry) -> int:
    return sum(passes(test, registry) for test in cases)


def calibration(
    cases: Sequence[Comparison],
    prior: Registry,
    *,
    size: int = SAMPLES,
    source: WorldSource = "synthetic",
    platform: list[Registry] | None = None,
) -> tuple[Registry, dict[str, object]]:
    tune = tuple(case for case in cases if case.split == "tune")
    accept = tuple(case for case in cases if case.split == "accept")
    if not tune or not accept:
        raise ValueError("调参与验收检查集均须非空")
    dimensions = axes(prior)
    baseline = {axis: item.value for axis, item in dimensions.items()}
    settings = latin_hypercube(dimensions, size, SEED)
    tested = [(check_count(tune, candidate(prior, row)), row) for row in settings]
    prior_count = check_count(tune, prior)
    examined = [*tested, (prior_count, baseline)]
    high = max(result for result, _ in examined) / len(tune)
    standard_error = math.sqrt(high * (1 - high) / len(tune))
    region = [row for count, row in examined if count / len(tune) >= high - standard_error]

    if platform is not None:
        platform.extend(candidate(prior, row) for row in region)

    def distance(row: dict[Axis, float]) -> float:
        return math.fsum(
            ((row[key] - item.value) / (item.bounds[1] - item.bounds[0])) ** 2
            for key, item in dimensions.items()
            if item.bounds[1] > item.bounds[0]
        )

    chosen = min(region, key=distance)
    selection = "nearest_prior_in_platform"
    selected = candidate(prior, chosen)
    tune_count, accept_count = check_count(tune, selected), check_count(accept, selected)
    if tune_count / len(tune) - accept_count / len(accept) > 0.03:
        chosen = {axis: (item.value + chosen[axis]) / 2 for axis, item in dimensions.items()}
        selected = candidate(prior, chosen)
        selection = "half_shrink"
        tune_count, accept_count = check_count(tune, selected), check_count(accept, selected)
        if tune_count / len(tune) - accept_count / len(accept) > 0.03:
            chosen, selected, selection = baseline, prior, "prior_after_shrink"
            tune_count, accept_count = prior_count, check_count(accept, selected)
    influence = []
    tail = max(1, len(tested) // 4)
    for axis in dimensions:
        ordered = sorted(tested, key=lambda entry: entry[1][axis])
        difference = mean(count for count, _ in ordered[-tail:]) - mean(
            count for count, _ in ordered[:tail]
        )
        influence.append({"axis": "/".join(axis), "change_in_pass_rate": difference / len(tune)})
    influence.sort(key=lambda entry: abs(float(str(entry["change_in_pass_rate"]))), reverse=True)
    report: dict[str, object] = {
        "source": source,
        "decision": selection,
        "draws": len(settings),
        "seed": SEED,
        "tune": {"passed": tune_count, "total": len(tune)},
        "accept": {"passed": accept_count, "total": len(accept)},
        "prior_tune": {"passed": prior_count, "total": len(tune)},
        "prior_accept": {"passed": check_count(accept, prior), "total": len(accept)},
        "best_tune_rate": high,
        "standard_error": standard_error,
        "platform_size": len(region),
        "sensitivity": influence,
        "parameters": {
            "/".join(axis): {"prior": item.value, "selected": chosen[axis]}
            for axis, item in dimensions.items()
        },
    }
    state = "frozen-rakuten-taste" if source == "rakuten" else "provisional-synthetic"
    return selected.model_copy(update={"state": state}), report


def priors_for_private_world(registry: Registry) -> Registry:
    approved = Prior(
        value=0.5,
        bounds=(0.25, 1.0),
        source="通过 C5 中文体检项目等权起点，Intern-Decision-4B 38c9daf",
        unit="是概率",
    )
    return registry.model_copy(
        update={
            "soft_items": {
                "grounded_reason": approved,
                "stay_fit": approved,
                "pace_fit": Prior(
                    value=0,
                    bounds=(0, 0),
                    source="C5 的 Intern-Decision-4B 节奏项未过体检",
                    unit="是概率",
                ),
            }
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-world", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    prior = load_parameters()
    source: WorldSource = "rakuten" if args.private_world else "synthetic"
    if args.private_world:
        world, _ = load_world(args.private_world, source="rakuten")
        cases = generate(world)
        input_bytes = "".join(case.model_dump_json() + "\n" for case in cases).encode()
        prior = priors_for_private_world(prior)
        output = args.out or DEFAULT_OUTPUT.with_name("rakuten-calibration")
    else:
        cases = load_cases()
        input_bytes = DEFAULT_CHECKS.read_bytes()
        output = args.out or DEFAULT_OUTPUT

    platform: list[Registry] = []
    selected, facts = calibration(cases, prior, source=source, platform=platform)
    output.mkdir(parents=True, exist_ok=True)
    case_hash = hashlib.sha256(input_bytes).hexdigest()
    facts["cases_sha256"] = case_hash
    selected = selected.model_copy(
        update={"version": f"phase2-{source}-calibration-{case_hash[:8]}"}
    )
    suffix = "frozen" if args.private_world else "provisional"
    (output / f"parameters-{suffix}.json").write_text(
        selected.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (output / "report.json").write_text(
        json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / f"platform-{suffix}.jsonl").write_text(
        "".join(registry.model_dump_json() + "\n" for registry in platform),
        encoding="utf-8",
    )
    print("平台区", facts["platform_size"], "调参", facts["tune"], "验收", facts["accept"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
