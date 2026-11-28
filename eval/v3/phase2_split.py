"""第二阶段 v2 题只按所选分区读取，历史 v1 只用于核对已保存运行。"""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from eval.v3.cases import ROOT, V3Case, load_cases

DIRECTORY = ROOT / "eval" / "cases" / "p2v2"
ARCHIVE = ROOT / "eval" / "cases" / "archive" / "phase2-v1"
LEGACY_CASES = ROOT / "eval" / "cases" / "p2_multiturn.jsonl"
MANIFEST_SHA256 = "6c7fb0f42b97ab9adb9776e063f1d7850c6aeb5d14ab9b5e5d17792aa8aed2ee"
SIZES = {"reflection": 61, "validation": 60, "holdout": 80}
PUBLIC_SPLITS = ("reflection", "validation")
type Split = Literal["reflection", "validation"]
type Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class CaseRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str
    seed_id: str
    category: str
    sha256: Sha256


class SplitRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    file: str
    file_sha256: Sha256
    count: int
    cases: tuple[CaseRegistration, ...]
    seed_ids: tuple[str, ...]


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["p2v2"]
    splits: dict[str, SplitRegistration]


class LegacyManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["phase2-v1"]
    cases_sha256: Sha256
    split_sha256: Sha256
    reflection: tuple[str, ...]
    validation: tuple[str, ...]
    holdout: tuple[str, ...]


def digest(data: object, *, ascii_only: bool = True) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=ascii_only)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def public_path(split: Split, directory: Path = DIRECTORY) -> Path:
    if split not in PUBLIC_SPLITS:
        raise ValueError("日常评测只开放反思和验证分区")
    return directory / f"p2v2-{split}.jsonl"


def registration(manifest_path: Path) -> Manifest:
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("第二阶段 v2 划分清单原始哈希已变")
    manifest = Manifest.model_validate_json(raw)
    if manifest.splits.keys() != SIZES.keys():
        raise ValueError("第二阶段 v2 划分清单必须恰好登记反思、验证、留出三份")
    seen: set[str] = set()
    seeds: set[str] = set()
    for name, expected in SIZES.items():
        part = manifest.splits[name]
        ids = {entry.case_id for entry in part.cases}
        part_seeds = {entry.seed_id for entry in part.cases}
        counts = Counter(entry.category for entry in part.cases)
        if (
            part.count != expected
            or len(part.cases) != expected
            or len(ids) != expected
            or len(counts) != 11
            or min(counts.values()) < 4
            or part_seeds != set(part.seed_ids)
            or len(part_seeds) != len(part.seed_ids)
        ):
            raise ValueError(f"{name} 的 v2 清单条数、类别或种子不符")
        if seen & ids or seeds & part_seeds:
            raise ValueError("v2 题号或种子跨份")
        seen.update(ids)
        seeds.update(part_seeds)
    return manifest


def split_identity(split: Split, *, archived_v1: bool = False) -> tuple[frozenset[str], str]:
    """检查已保存运行时读取清单元数据。"""
    public_path(split)
    if not archived_v1:
        part = registration(DIRECTORY / "split-manifest.json").splits[split]
        return frozenset(entry.case_id for entry in part.cases), part.file_sha256
    legacy = LegacyManifest.model_validate_json((ARCHIVE / "p2_split.json").read_bytes())
    layout = {key: getattr(legacy, key) for key in SIZES}
    if digest(layout) != legacy.split_sha256:
        raise ValueError("已归档 v1 划分哈希已变")
    return frozenset(layout[split]), legacy.cases_sha256


def frozen_cases(split: Split, directory: Path = DIRECTORY) -> list[V3Case]:
    """只读取清单和指定公开分区，验证文件与逐题哈希后解码。"""
    path = public_path(split, directory)
    manifest_path = directory / "split-manifest.json"
    if directory.is_symlink() or path.is_symlink() or manifest_path.is_symlink():
        raise ValueError(f"{split} 的 v2 题文件路径不符")
    part = registration(manifest_path).splits[split]
    if part.file != f"{split}.jsonl":
        raise ValueError(f"{split} 的 v2 题文件路径不符")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != part.file_sha256:
        raise ValueError(f"{split} 的 v2 多轮题内容哈希已变")
    text = raw.decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != part.count:
        raise ValueError(f"{split} 的 v2 题数与清单不符")
    for entry, line in zip(part.cases, lines, strict=True):
        case = json.loads(line)
        if (
            not isinstance(case, dict)
            or case.get("case_id") != entry.case_id
            or case.get("seed_id") != entry.seed_id
            or case.get("category") != entry.category
            or digest(case, ascii_only=False) != entry.sha256
        ):
            raise ValueError(f"{split} 的 v2 题目与清单登记不符")
    return load_cases(path, verified_text=text)
