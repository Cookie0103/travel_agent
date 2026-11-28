import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from eval.v3 import phase2_split
from eval.v3.phase2_split import (
    DIRECTORY,
    Split,
    frozen_cases,
    public_path,
    registration,
    split_identity,
)
from eval.v3.run import main


@pytest.mark.parametrize(("split", "count"), [("reflection", 61), ("validation", 60)])
def test_frozen_loader_only_reads_the_manifest_and_named_public_split(
    split: Split, count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths: list[Path] = []
    read_bytes = Path.read_bytes

    def observed(path: Path) -> bytes:
        assert path in {DIRECTORY / "split-manifest.json", public_path(split)}
        paths.append(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", observed)
    cases = frozen_cases(split)
    assert len(cases) == count
    assert {case.case_id for case in cases} == split_identity(split)[0]
    assert paths == [
        DIRECTORY / "split-manifest.json",
        public_path(split),
        DIRECTORY / "split-manifest.json",
    ]


def test_v2_rejects_file_and_canonical_case_hash_mismatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = public_path("reflection")
    destination = tmp_path / source.name
    destination.write_bytes(source.read_bytes() + b"\n")
    manifest_path = tmp_path / "split-manifest.json"
    manifest_path.write_bytes((DIRECTORY / manifest_path.name).read_bytes())
    with pytest.raises(ValueError, match="内容哈希"):
        frozen_cases("reflection", tmp_path)

    # 只修文件哈希，逐题哈希仍须独立阻止文本变更。
    rows = source.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["title"] += "内容变更"
    rows[0] = json.dumps(first, ensure_ascii=False)
    destination.write_text("\n".join(rows) + "\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_bytes())
    manifest["splits"]["reflection"]["file_sha256"] = hashlib.sha256(
        destination.read_bytes()
    ).hexdigest()
    altered = json.dumps(manifest).encode("utf-8")
    manifest_path.write_bytes(altered)
    monkeypatch.setattr(phase2_split, "MANIFEST_SHA256", hashlib.sha256(altered).hexdigest())
    with pytest.raises(ValueError, match="清单登记"):
        frozen_cases("reflection", tmp_path)


def test_frozen_manifest_rejects_valid_metadata_change_before_reading_cases(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "split-manifest.json"
    manifest = json.loads((DIRECTORY / manifest_path.name).read_bytes())
    manifest["splits"]["holdout"]["file_sha256"] = "0" * 64
    altered = json.dumps(manifest).encode("utf-8")
    assert phase2_split.Manifest.model_validate_json(altered).version == "p2v2"
    manifest_path.write_bytes(altered)
    with pytest.raises(ValueError, match="划分清单原始哈希"):
        frozen_cases("reflection", tmp_path)


def test_duplicate_seeds_across_registered_partitions_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "split-manifest.json"
    manifest = json.loads((DIRECTORY / target.name).read_bytes())
    reflection, validation = (manifest["splits"][name] for name in ("reflection", "validation"))
    shared = reflection["seed_ids"][0]
    seed = validation["seed_ids"][0]
    for case in validation["cases"]:
        if case["seed_id"] == seed:
            case["seed_id"] = shared
    validation["seed_ids"][0] = shared
    altered = json.dumps(manifest).encode("utf-8")
    target.write_bytes(altered)
    monkeypatch.setattr(phase2_split, "MANIFEST_SHA256", hashlib.sha256(altered).hexdigest())
    with pytest.raises(ValueError, match="跨份"):
        registration(target)


def test_no_public_loader_for_closed_partitions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: pytest.fail("拒绝前无需打开清单或题目"),
    )
    with pytest.raises(ValueError, match="只开放反思和验证"):
        frozen_cases(cast(Split, "holdout"))
    with pytest.raises(SystemExit) as ended:
        main(["--split", "all"])
    assert ended.value.code == 2


def test_no_argument_v3_selects_v2_reflection_before_initializing_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def load(split: Split) -> None:
        assert split == "reflection"
        raise RuntimeError("已到题库入口")

    monkeypatch.setattr("eval.v3.run.frozen_cases", load)
    with pytest.raises(RuntimeError, match="已到题库入口"):
        main([])


def test_v1_archive_identity_only_reads_legacy_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(phase2_split, "ARCHIVE", tmp_path)
    layout = {
        "reflection": ["r"],
        "validation": ["v"],
        "holdout": ["h"],
    }
    path = tmp_path / "p2_split.json"
    hashcode = "a" * 64
    path.write_text(
        json.dumps(
            {
                "version": "phase2-v1",
                "cases_sha256": hashcode,
                "split_sha256": phase2_split.digest(layout),
                **layout,
            }
        ),
        encoding="utf-8",
    )
    assert split_identity("reflection", archived_v1=True) == (frozenset({"r"}), hashcode)
