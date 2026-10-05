"""冻结集完整性与故障期望；旧失败案例不得被重新标成未见test或弱化。"""

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.execution import RunContext, RuntimeEvent
from eval.cases import Case
from eval.graders import Observation, grade
from eval.run import ROOT
from eval.suites import LEGACY_FILES, load_suite


def frozen_copy(tmp_path: Path) -> Path:
    target = tmp_path / "eval" / "cases"
    target.mkdir(parents=True)
    for name in (*LEGACY_FILES, "frozen_v1.json", "frozen_v1.jsonl"):
        shutil.copyfile(ROOT / "eval" / "cases" / name, target / name)
    metadata_path = target / "frozen_v1.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(status="frozen", frozen_at="2026-10-03T00:00:00+00:00")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return tmp_path


def test_frozen_suite_keeps_legacy_thirty_and_distinct_twenty_forty(tmp_path: Path) -> None:
    root = frozen_copy(tmp_path)
    legacy, _ = load_suite(root, "legacy", "dev")
    dev, metadata = load_suite(root, "frozen", "dev")
    test, _ = load_suite(root, "frozen", "test")
    assert (len(legacy), len(dev), len(test)) == (30, 20, 40)
    assert metadata["test_used_for_model_tuning"] is False
    assert not {c.case_id for c in test} & {c.case_id for c in legacy}
    assert all(
        c == next(old for old in legacy if old.case_id == c.case_id)
        for c in dev
        if c.case_id in {old.case_id for old in legacy}
    )


@pytest.mark.parametrize(
    "change", ["candidate", "content", "legacy", "split", "pairs", "known-test"]
)
def test_frozen_suite_rejects_unfrozen_modified_or_relabelled_cases(
    tmp_path: Path, change: str
) -> None:
    root = frozen_copy(tmp_path)
    folder = root / "eval" / "cases"
    metadata_path = folder / "frozen_v1.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if change == "candidate":
        metadata["status"] = "candidate"
    elif change == "content":
        with (folder / "frozen_v1.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("\n")
    elif change == "legacy":
        with (folder / LEGACY_FILES[0]).open("a", encoding="utf-8") as handle:
            handle.write("\n")
    elif change == "split":
        metadata["test_ids"].pop()
    elif change == "pairs":
        metadata["pairs"] = {"test-osaka-scope": "missing"}
    else:
        path = folder / "frozen_v1.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[20]["case_id"] = "okinawa-beach"
        metadata["test_ids"][0] = "okinawa-beach"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        metadata["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError):
        load_suite(root, "frozen", "test")


def test_optional_results_require_explicit_failure_and_do_not_allow_unpaired_tools() -> None:
    case = Case(
        case_id="expected-hold-error",
        input="暂留",
        source="test",
        adaptation="actual fault required",
        fault="supplier_500",
        expected_tool_errors=("provider_error",),
        business_checks=("expected_tool_failure",),
        result_requirement="optional",
        allowed_tools=["hold_hotel", "get_travel_facts"],
        required_tools=["hold_hotel"],
    )
    context = RunContext(uuid4())
    start = RuntimeEvent(context, "tool_started", tool_name="hold_hotel", tool_call_id=uuid4())
    end = replace(start, kind="tool_finished", code="provider_error", result_empty=True)
    actual = Observation("completed", "供应商暂时失败", (start, end))
    assert all(grade(case, actual).values())
    read = replace(start, tool_name="get_travel_facts", tool_call_id=uuid4())
    read_end = replace(read, kind="tool_finished", result_empty=False)
    assert all(grade(case, replace(actual, events=(read, read_end, start, end))).values())
    assert not grade(case, replace(actual, events=(start,)))["tool_success"]
    with pytest.raises(ValidationError):
        Case(
            case_id="bad",
            input="x",
            source="test",
            adaptation="test",
            result_requirement="optional",
        )
