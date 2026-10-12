"""选择历史或冻结评测集；冻结内容、划分及历史来源发生变化时拒绝运行。"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eval.cases import Case, load_cases

LEGACY_FILES = ("datamind_adapted.jsonl", "travel_m1.jsonl")


class FrozenSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["travel-eval-v1"]
    status: Literal["candidate", "frozen"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev_ids: list[str]
    test_ids: list[str]
    legacy_sha256: dict[str, str]
    retained_legacy_only: list[str]
    provenance: str
    suite_author_read_test: bool
    test_used_for_model_tuning: bool
    model_test_runs_before_freeze: int
    limitations: list[str]
    pairs: dict[str, str]
    frozen_at: str | None = None


def load_suite(
    root: Path, name: Literal["legacy", "frozen"], split: Literal["dev", "test"]
) -> tuple[list[Case], dict[str, object]]:
    folder = root / "eval" / "cases"
    if name == "legacy":
        return load_cases(tuple(folder / file for file in LEGACY_FILES), split), {
            "name": "legacy-30",
            "frozen": False,
        }
    metadata = FrozenSuite.model_validate_json((folder / "frozen_v1.json").read_bytes())
    path = folder / "frozen_v1.jsonl"
    if metadata.status != "frozen" or not metadata.frozen_at:
        raise ValueError("候选评测集尚未冻结")
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata.sha256:
        raise ValueError("冻结评测集内容发生变化，须另建版本")
    if set(metadata.legacy_sha256) != set(LEGACY_FILES) or any(
        hashlib.sha256((folder / file).read_bytes()).hexdigest() != digest
        for file, digest in metadata.legacy_sha256.items()
    ):
        raise ValueError("历史评测来源发生变化")
    dev, test = load_cases(path, "dev"), load_cases(path, "test")
    dev_ids, test_ids = [case.case_id for case in dev], [case.case_id for case in test]
    if (
        len(dev) != 20
        or len(test) != 40
        or dev_ids != metadata.dev_ids
        or test_ids != metadata.test_ids
        or set(dev_ids) & set(test_ids)
    ):
        raise ValueError("冻结评测划分无效")
    legacy = load_cases(tuple(folder / file for file in LEGACY_FILES), "dev")
    known = {case.case_id: case for case in legacy}
    if set(test_ids) & known.keys() or set(metadata.retained_legacy_only) != known.keys() - set(
        dev_ids
    ):
        raise ValueError("历史dev不得改成未见test")
    if any(case != known[case.case_id] for case in dev if case.case_id in known):
        raise ValueError("沿用历史案例的期望不得改变")
    if not metadata.pairs or any(
        refusal not in test_ids or control not in test_ids or refusal == control
        for refusal, control in metadata.pairs.items()
    ):
        raise ValueError("异常案例缺少正常对照")
    # manifest保存冻结依据；这些期望从不送进模型上下文。
    return (dev if split == "dev" else test), json.loads(metadata.model_dump_json())
