"""第二阶段多轮题的冻结划分。"""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from eval.v3.cases import ROOT, V3Case, load_cases

CASES = ROOT / "eval/cases/p2_multiturn.jsonl"
MANIFEST = ROOT / "eval/cases/p2_split.json"
type Split = Literal["reflection", "validation", "holdout", "all"]
SIZES = {"reflection": 61, "validation": 60, "holdout": 80}


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["phase2-v1"]
    cases_sha256: str
    split_sha256: str
    reflection: tuple[str, ...]
    validation: tuple[str, ...]
    holdout: tuple[str, ...]


def digest(assignment: dict[str, tuple[str, ...]]) -> str:
    records = json.dumps(assignment, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(records.encode()).hexdigest()


def frozen_cases(
    split: Split, cases_path: Path = CASES, manifest_path: Path = MANIFEST
) -> list[V3Case]:
    manifest = Manifest.model_validate_json(manifest_path.read_bytes())
    layout = {name: getattr(manifest, name) for name in SIZES}
    if hashlib.sha256(cases_path.read_bytes()).hexdigest() != manifest.cases_sha256:
        raise ValueError("多轮题内容哈希已变")
    if digest(layout) != manifest.split_sha256:
        raise ValueError("多轮题划分哈希已变")
    cases = load_cases(cases_path)
    by_id = {case.case_id: case for case in cases}
    ids = [case_id for values in layout.values() for case_id in values]
    if set(ids) != by_id.keys() or len(ids) != len(by_id):
        raise ValueError("多轮题划分必须恰好覆盖整个题库")
    seeds: dict[str, str] = {}
    for name, case_ids in layout.items():
        counts = Counter(by_id[case_id].category for case_id in case_ids)
        if (
            len(case_ids) != SIZES[name]
            or len(counts) != 11
            or max(counts.values()) - min(counts.values()) > 1
        ):
            raise ValueError(f"{name} 的多轮题类别或条数不符")
        for case_id in case_ids:
            seed = by_id[case_id].seed_id
            if seed is None or seeds.setdefault(seed, name) != name:
                raise ValueError("同一种子的多轮题变体跨份")
    return cases if split == "all" else [by_id[case_id] for case_id in layout[split]]
