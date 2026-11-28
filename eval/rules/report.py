"""对冻结规则题跑真实规则，输出拦截率、误拦和边界验证。"""

import argparse
import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from eval.commerce.checks import load_cases as load_commerce_cases
from eval.commerce.checks import passes
from eval.commerce.parameters import load_parameters
from eval.rules.scenarios import RULES, Expected, Mode, observe

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "eval" / "cases" / "rules" / "rules-v1.jsonl"
DEFAULT_REPORT = ROOT / ".cache" / "eval-rules" / "report.md"


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    rule: int = Field(ge=1, le=17)
    scenario: Mode
    variant: int = Field(ge=1, le=9)
    expected: Expected


_EXPECTED: dict[int, tuple[Expected, Expected, Expected]] = {
    1: ("none", "none", "unknown"),
    2: ("none", "none", "unknown"),
    3: ("verified", "verified", "unknown"),
    4: ("verified", "verified", "conflict"),
    5: ("verified", "verified", "conflict"),
    6: ("verified", "verified", "conflict"),
    7: ("verified", "verified", "conflict"),
    8: ("none", "none", "unknown"),
    9: ("none", "none", "unknown"),
    10: ("none", "none", "unknown"),
    11: ("none", "none", "unknown"),
    12: ("none", "none", "conflict"),
    13: ("verified", "verified", "conflict"),
    14: ("none", "none", "verified"),
    15: ("none", "none", "unknown"),
    16: ("none", "none", "unknown"),
    17: ("none", "none", "unknown"),
}
_MODES: tuple[Mode, ...] = ("clear", "border", "flag")
_REVIEW_CASES = (
    Case(id="rule05-border-9", rule=5, scenario="border", variant=9, expected="verified"),
    Case(id="rule06-flag-9", rule=6, scenario="flag", variant=9, expected="unknown"),
    Case(id="rule12-flag-9", rule=12, scenario="flag", variant=9, expected="unknown"),
)


def create_cases(path: Path) -> None:
    rows = (
        Case(
            id=f"rule{rule.number:02}-{mode}-{variant}",
            rule=rule.number,
            scenario=mode,
            variant=variant,
            expected=expected,
        )
        for rule in RULES
        for mode, expected in zip(_MODES, _EXPECTED[rule.number], strict=True)
        for variant in range(1, 9)
    )
    path.write_text(
        "".join(row.model_dump_json() + "\n" for row in (*rows, *_REVIEW_CASES)),
        encoding="utf-8",
        newline="\n",
    )


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({numerator / denominator:.1%})" if denominator else "—"


def report(cases: tuple[Case, ...]) -> tuple[str, dict[str, object]]:
    by_rule = Counter(row.rule for row in cases)
    if len({row.id for row in cases}) != len(cases) or set(by_rule) != {
        rule.number for rule in RULES
    }:
        raise ValueError("规则题 ID 重复或覆盖范围不完整")
    body = [
        "# 第二阶段离线规则评测",
        "",
        f"规则题 {len(cases)} 道。每条规则包括正常、边界、触发三类。触发拦截与正常通过分别统计。",
        "",
        "| 规则 | 级别 | 一致率 | 应拦截样本拦截率 | 应通过样本误拦率 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    issues: list[dict[str, str]] = []
    totals: dict[str, dict[str, int]] = {}
    for rule in RULES:
        rows = [row for row in cases if row.rule == rule.number]
        matched = true_blocks = actual_blocks = false_blocks = 0
        for row in rows:
            code, observed = observe(row.rule, row.scenario, row.variant)
            intended = row.expected == "conflict"
            blocked = observed == "conflict"
            matched += observed == row.expected
            true_blocks += intended
            actual_blocks += intended and blocked
            false_blocks += not intended and blocked
            if observed != row.expected:
                issues.append(
                    {
                        "id": row.id,
                        "code": code,
                        "expected": row.expected,
                        "observed": observed,
                    }
                )
        permitted = len(rows) - true_blocks
        totals[str(rule.number)] = {
            "cases": len(rows),
            "matched": matched,
            "should_block": true_blocks,
            "blocked": actual_blocks,
            "false_blocks": false_blocks,
        }
        body.append(
            f"| {rule.number} {rule.title} | {rule.level} | {_rate(matched, len(rows))} | "
            f"{_rate(actual_blocks, true_blocks)} | {_rate(false_blocks, permitted)} |"
        )
    commerce_cases = load_commerce_cases()
    priors = load_parameters()
    commerce: dict[str, dict[str, int]] = {}
    for split in ("tune", "accept"):
        subset = [case for case in commerce_cases if case.split == split]
        commerce[split] = {
            "cases": len(subset),
            "passed": sum(passes(case, priors) for case in subset),
        }
    body.extend(("", "## 商业打分检查集", ""))
    body.append(f"合成评测与先验权重版本 {priors.version}。此处记录先验检查，不是正式定参验收。")
    for split, values in commerce.items():
        body.append(f"- {split} {_rate(values['passed'], values['cases'])}")
    if issues:
        body.extend(("", "## 差异", ""))
        for issue in issues:
            body.append(
                f"- {issue['id']}，{issue['code']}，预期 {issue['expected']}，"
                f"得到 {issue['observed']}。"
            )
    report_data: dict[str, object] = {
        "rule_cases": len(cases),
        "rules": totals,
        "issues": issues,
        "commerce_prior_checks": commerce,
    }
    return "\n".join(body) + "\n", report_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    if args.generate:
        create_cases(args.cases)
    cases = tuple(
        Case.model_validate_json(line)
        for line in args.cases.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    markdown, facts = report(cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")
    args.out.with_suffix(".json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"规则题 {facts['rule_cases']}，差异见 {args.out}")
    return int(bool(facts["issues"]))


if __name__ == "__main__":
    raise SystemExit(main())
