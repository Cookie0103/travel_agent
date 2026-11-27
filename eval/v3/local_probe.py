"""汇总 A7 预先选定的十道反思题，每题一次。"""

import argparse
import json
from pathlib import Path
from statistics import median

CASES = frozenset(
    [f"p2-main-flow-1-{index:02d}" for index in range(1, 7)]
    + [f"p2-commerce-1-{index:02d}" for index in range(1, 5)]
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trials", type=Path, nargs="?")
    args = parser.parse_args()
    if args.trials is None:
        print(" ".join(f"--case-id {case}" for case in sorted(CASES)))
        return 0
    rows = [json.loads(raw) for raw in args.trials.read_text(encoding="utf-8").splitlines() if raw]
    if {row["case_id"] for row in rows} != CASES or len(rows) != 10:
        parser.error("需要 A7 固定十题的完整结果")
    passed = sum(
        not row.get("infra_error")
        and not row["tools"]["hallucinated"]
        and not row["tools"]["blocked"]
        and any(
            check["id"] == "draft-no-conflict" and check["outcome"] == "pass"
            for check in row["checks"]
        )
        for row in rows
    )
    elapsed = [row["total_s"] for row in rows]
    print(
        json.dumps(
            {
                "drafts_through_valid_tools": passed,
                "attempted_cases": len(rows),
                "median_seconds": median(elapsed),
                "max_seconds": max(elapsed),
                "draft_count_eligible": passed >= 8,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
