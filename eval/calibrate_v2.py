"""真人CSV与隐藏参考标签的离线一致率；不会代填真人标签。"""

import argparse
import csv
import json
import random
from pathlib import Path


def agreement(
    pairs: list[tuple[int, int]], *, minimum_pairs: int = 30, allow_partial: bool = True
) -> dict[str, object]:
    if any(
        type(a) is not int or type(b) is not int or a not in (0, 1) or b not in (0, 1)
        for a, b in pairs
    ):
        raise ValueError("校准标签必须是0/1")
    matrix = [[sum(a == i and b == j for a, b in pairs) for j in range(2)] for i in range(2)]
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n if n else None
    chance = (
        sum(sum(matrix[i]) * sum(row[i] for row in matrix) for i in range(2)) / n**2 if n else None
    )
    if n < minimum_pairs and not allow_partial:
        observed, chance = None, None
    return {
        "status": "pending" if n < minimum_pairs else "paired",
        "paired": n,
        "exact_rate": observed,
        "kappa": (observed - chance) / (1 - chance)
        if observed is not None and chance is not None and chance < 1
        else None,
        "confusion": matrix,
        "basis": "actual human labels only; model reference remains uncalibrated until paired",
    }


def human_pairs(rows: list[dict[str, str]], references: dict[str, object]) -> list[tuple[int, int]]:
    pairs = []
    for row in rows:
        if "编号" in row:
            answers = [
                row.get(key, "").strip()
                for key in ("Q1按要求做了吗", "Q2说得清楚不矛盾吗", "Q3知道下一步吗")
            ]
            if row.get("不确定", "").strip() not in ("", "否", "0") or any(
                a not in ("是", "否") for a in answers
            ):
                continue
            identifier, value = row["编号"], int(all(a == "是" for a in answers))
        else:
            if not row.get("human_rater", "").strip() or row.get("human_pass") not in ("0", "1"):
                continue
            identifier, value = row["sample_id"], int(row["human_pass"])
        reference = references.get(identifier)
        model = reference.get("model_reference") if isinstance(reference, dict) else None
        if type(model) is int and model in (0, 1):
            pairs.append((model, value))
    return pairs


def prepare(rows: list[dict[str, object]], directory: Path) -> Path:
    selected = []
    for status in ("passed", "failed"):
        candidates = [
            row
            for row in rows
            if row.get("status") == status and isinstance(row.get("text"), str) and row["text"]
        ]
        if len(candidates) < 15:
            raise ValueError("需要15条通过和15条失败的实际回答，不生成假回答补数")
        selected.extend(candidates[:15])
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / "human-labels.csv"
    references = {}
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "case_id",
                "task",
                "conditions",
                "answer",
                "human_pass",
                "human_rater",
                "notes",
            ],
        )
        writer.writeheader()
        # 固定种子洗牌，可复现但不以奇偶泄露参考标签。
        ordered = selected.copy()
        random.Random(20261013).shuffle(ordered)
        for index, row in enumerate(ordered, 1):
            sample = f"sample-{index:02d}"
            writer.writerow(
                {
                    "sample_id": sample,
                    "case_id": row.get("case_id"),
                    "task": row.get("user_input", ""),
                    "conditions": json.dumps(row.get("conditions", {}), ensure_ascii=False),
                    "answer": row["text"],
                }
            )
            references[sample] = {
                "rule_reference": int(row["status"] == "passed"),
                "model_reference": None,
                "event_summary": row.get("event_summary"),
            }
    (directory / "hidden-reference.json").write_text(
        json.dumps({"seed": 20261013, "references": references}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("references", type=Path)
    args = parser.parse_args()
    references = json.loads(args.references.read_text(encoding="utf-8"))
    references = references.get("references", references)
    with args.csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    readable = bool(rows and "编号" in rows[0])
    print(
        json.dumps(
            agreement(
                human_pairs(rows, references),
                minimum_pairs=20 if readable else 30,
                allow_partial=not readable,
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
