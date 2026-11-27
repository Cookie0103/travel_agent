"""重算两个同题结果的成对差异和商业结论稳定度。"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from eval.commerce.parameters import Registry, load_parameters
from eval.commerce.score import rescore
from eval.core.paired import Trial, compare, stability


def load(path: Path) -> dict[tuple[str, int], dict[str, object]]:
    index = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if not isinstance(row.get("commerce"), dict) or row.get("infra_error"):
            continue
        key = (row["case_id"], row["repeat"])
        if key in index:
            raise ValueError("出现重复的商业试验")
        index[key] = row
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--platform", required=True, type=Path)
    parser.add_argument("--parameters", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reference = load_parameters(args.parameters) if args.parameters else load_parameters()
    platform = [
        Registry.model_validate_json(line)
        for line in args.platform.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    a, b = load(args.baseline), load(args.candidate)
    if not a or a.keys() != b.keys():
        raise ValueError("比较要求两份报告具有同题同重复且完整的商业试验")
    soft_rows = [
        row
        for row in (*a.values(), *b.values())
        if isinstance(sheet := row.get("commerce"), dict)
        and sheet.get("passed")
        and sheet.get("groups")
    ]
    measured_soft = []
    for row in soft_rows:
        facts, measurement = row.get("soft_facts"), row.get("commerce_soft")
        if (
            isinstance(facts, dict)
            and bool(facts)
            and isinstance(measurement, dict)
            and measurement.get("state") == "observed"
            and isinstance(values := measurement.get("by_hotel"), dict)
            and facts.keys() == values.keys()
        ):
            measured_soft.append(measurement)
    use_soft = bool(soft_rows) and len(soft_rows) == len(measured_soft)
    identities = {
        (row.get("model"), row.get("revision"), row.get("temperature")) for row in measured_soft
    }
    if use_soft and len(identities) > 1:
        raise ValueError("同一比较只使用一套软性模型、权重版本及温度")

    def series(rows: dict[tuple[str, int], dict[str, object]], registry: Registry) -> list[Trial]:
        trials = []
        for (case_id, repeat), row in rows.items():
            sheet = row["commerce"]
            assert isinstance(sheet, dict)
            seed = row.get("seed_id")
            measured = row.get("commerce_soft")
            values = measured.get("by_hotel") if use_soft and isinstance(measured, dict) else None
            trials.append(
                Trial(
                    case_id,
                    repeat,
                    bool(sheet["passed"]),
                    rescore(sheet, registry, soft=values if isinstance(values, dict) else None),
                    str(seed) if seed else None,
                )
            )
        return trials

    paired = compare(series(a, reference), series(b, reference))
    deltas = [
        mean(trial.score for trial in series(b, parameters))
        - mean(trial.score for trial in series(a, parameters))
        for parameters in platform
    ]
    fraction, clear = stability(paired.score.mean, deltas)
    result = {
        **asdict(paired),
        "parameters": reference.version,
        "parameter_state": reference.state,
        "platform_size": len(platform),
        "soft_model": next(iter(identities)) if use_soft else None,
        "soft_scoring": "measured" if use_soft else "hard_only",
        "soft_rows_measured": len(measured_soft),
        "soft_rows_eligible": len(soft_rows),
        "stability": fraction,
        "conclusion": ("候选更高" if paired.score.mean > 0 else "基线更高")
        if clear
        else "分不出高下",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{result['conclusion']} · 结论稳定度 {fraction:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
