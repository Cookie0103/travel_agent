"""读取评测的 JSONL 试验记录。"""

import json
from pathlib import Path
from typing import Any


def read_jsonl(
    path: Path, *, recovery: bool = False, skip_empty: bool = True
) -> list[dict[str, Any]]:
    """续跑允许缺文件或坏行，复盘默认严格拒绝损坏的记录。"""
    if recovery and not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if skip_empty and not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if not recovery:
                raise
    return rows
