import json
from pathlib import Path

import pytest

from eval.v3.phase2_split import CASES, MANIFEST, frozen_cases


def test_frozen_split_rejects_changed_content_and_assignment(tmp_path: Path) -> None:
    assert len(frozen_cases("reflection")) == 61
    assert len(frozen_cases("validation")) == 60
    assert len(frozen_cases("holdout")) == 80
    altered = tmp_path / CASES.name
    altered.write_bytes(CASES.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="内容哈希"):
        frozen_cases("reflection", altered)
    manifest = json.loads(MANIFEST.read_bytes())
    manifest["holdout"][0], manifest["reflection"][0] = (
        manifest["reflection"][0],
        manifest["holdout"][0],
    )
    altered_manifest = tmp_path / MANIFEST.name
    altered_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="划分哈希"):
        frozen_cases("reflection", manifest_path=altered_manifest)
