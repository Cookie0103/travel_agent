"""盲标表不填真人分、不以排列泄露参考标签，保留任务和条件。"""

import csv
import json
from pathlib import Path

from eval.calibrate_v2 import prepare


def test_preparation_shuffles_labels_and_preserves_blind_task_context(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = [
        {
            "case_id": f"case-{i}",
            "status": "passed" if i < 15 else "failed",
            "text": f"实际测试回答{i}",
            "user_input": "任务原文",
            "conditions": {"city": "京都"},
        }
        for i in range(30)
    ]
    path = prepare(rows, tmp_path / "one")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        data = list(csv.DictReader(handle))
    payload = json.loads((path.parent / "hidden-reference.json").read_text())
    references = payload.get("references", payload)
    labels = [references[row["sample_id"]]["rule_reference"] for row in data]
    assert labels != [1, 0] * 15 and labels != [0, 1] * 15
    assert len(data) == 30 and sum(labels) == 15
    assert all(
        not row["human_pass"]
        and row.get("task") == "任务原文"
        and "京都" in row.get("conditions", "")
        for row in data
    )
