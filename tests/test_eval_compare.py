"""比较原完整配对、失败分母与版本；合成记录不调用模型或冒充真实评测。"""

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext
from backend.providers.claude_agent.evaluation import (
    EvaluationVariant,
    evaluation_definitions,
    evaluation_metadata,
)
from eval.cases import Case
from eval.compare import compare
from eval.report import measured_summary, rate
from eval.run import manifest


def write_batch(
    path: Path, *, variant: EvaluationVariant = "full", statuses: tuple[str, ...] = ("passed",) * 6
) -> None:
    path.mkdir()
    cases = [
        Case(
            case_id=f"compare-{index}",
            source="synthetic",
            adaptation="not actual model",
            input="PRIVATE-PROMPT-SENTINEL",
        )
        for index in range(2)
    ]
    metadata = {
        **manifest(cases, evaluation_definitions(variant, database=True)),
        **evaluation_metadata(variant, live=True, database=True, workflow=None),
        "business_database": True,
        "catalog_sha256": "a" * 64,
        "data_version": "synthetic-v1",
        "max_http_attempts_per_case": 12,
        "repetitions": 3,
        "evaluation_suite": {"version": "synthetic"},
    }
    rows = []
    attempts = []
    for index, status in enumerate(statuses):
        case_id = cases[index % 2].case_id
        row = {
            "case_id": case_id,
            "repeat": index // 2 + 1,
            "status": status,
            "identity": {
                "provider": "deepseek",
                "model": "deepseek-flash",
                "sdk_version": "0.2.163",
                "cli_version": "2.1.114",
            },
            "accounting_currency": "CNY",
            "http_attempts": 1,
            "run_accounted": "0.01",
            "elapsed_seconds": 2,
            "first_progress_seconds": None,
            "text": "PRIVATE-ANSWER-SENTINEL",
            "content_record": {"secret": "PRIVATE-FACT-SENTINEL"},
        }
        if status == "not_run":
            row = {"case_id": case_id, "repeat": index // 2 + 1, "status": status}
        elif status == "error":
            row = {
                "case_id": case_id,
                "repeat": index // 2 + 1,
                "status": status,
                "reason": "business_setup_failed",
            }
        else:
            attempts.append(
                {
                    "case_id": case_id,
                    "repeat": index // 2 + 1,
                    "context": asdict(RunContext(uuid4())),
                    "evaluation_variant": variant,
                }
            )
        rows.append(row)
    totals = rate(rows)
    summary = {
        "mode": "live_database",
        "case_count": 2,
        "expected_attempts": 6,
        "repetitions": 3,
        "workflow": "autonomous",
        "evaluation_variant": variant,
        "data_version": "synthetic-v1",
        **{k: v for k, v in totals.items() if k != "expected"},
        **measured_summary(rows, 3),
    }
    for name, value in (("manifest.json", metadata), ("summary.json", summary)):
        (path / name).write_text(json.dumps(value, default=str), encoding="utf-8")
    for name, values in (("results.jsonl", rows), ("attempts.jsonl", attempts)):
        (path / name).write_text(
            "".join(json.dumps(value, default=str) + "\n" for value in values), encoding="utf-8"
        )


def test_complete_pairing_counts_original_failures_and_exports_no_private_content(
    tmp_path: Path,
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write_batch(a, statuses=("passed", "failed", "passed", "failed", "passed", "failed"))
    write_batch(b, variant="no_tools", statuses=("failed",) * 6)
    output = compare(a, b)
    paired = output["paired"]
    assert isinstance(paired, dict)
    assert paired["planned_n"] == 6 and paired["rule_pass_delta_b_minus_a"] == -0.5
    assert paired["outcomes"] == {"passed->failed": 3, "failed->failed": 3}
    changes = output["declared_configuration_changes"]
    assert isinstance(changes, list) and "sdk_resume_enabled" in changes
    assert "PRIVATE" not in json.dumps(output)


@pytest.mark.parametrize(
    "field",
    [
        "sha256",
        "selected_cases",
        "catalog_sha256",
        "evaluation_suite",
        "max_http_attempts_per_case",
        "data_version",
        "pricing",
        "schema_sha256",
        "skills",
        "automatic_compaction",
        "sdk_resume_enabled",
        "comparison_group",
    ],
)
def test_source_case_data_and_undeclared_configuration_drift_are_rejected(
    tmp_path: Path, field: str
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write_batch(a)
    write_batch(b, variant="no_tools")
    p = b / "manifest.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    if field == "sha256":
        data[field]["pyproject.toml"] = "b" * 64
    elif field == "selected_cases":
        data[field][0]["input"] = "changed"
    elif field == "catalog_sha256":
        data[field] = "b" * 64
    elif field == "evaluation_suite":
        data[field] = {"version": "changed"}
    elif field == "max_http_attempts_per_case":
        data[field] = 11
    elif field in {"data_version", "pricing", "comparison_group", "automatic_compaction"}:
        data[field] = "changed"
    elif field == "schema_sha256":
        data[field] = "b" * 64
    elif field == "skills":
        data[field] = ["unexpected"]
    else:
        data[field] = True
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        compare(a, b)


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "duplicate",
        "extra",
        "order",
        "attempt-missing",
        "attempt-duplicate",
        "identity-reuse",
        "summary-stale",
        "unfinished",
        "fixture",
        "mixed-model",
        "sdk-drift",
    ],
)
def test_incomplete_or_inconsistent_batches_cannot_silently_drop_cases(
    tmp_path: Path, corruption: str
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write_batch(a)
    write_batch(b)
    rp = b / "results.jsonl"
    rows = [json.loads(s) for s in rp.read_text(encoding="utf-8").splitlines()]
    ap = b / "attempts.jsonl"
    attempts = [json.loads(s) for s in ap.read_text(encoding="utf-8").splitlines()]
    sp = b / "summary.json"
    summary = json.loads(sp.read_text(encoding="utf-8"))
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate":
        rows[-1] = rows[0]
    elif corruption == "extra":
        rows.append(rows[0])
    elif corruption == "order":
        rows.reverse()
    elif corruption == "attempt-missing":
        attempts.pop()
    elif corruption == "attempt-duplicate":
        attempts[-1] = attempts[0]
    elif corruption == "identity-reuse":
        attempts[-1]["context"] = attempts[0]["context"]
    elif corruption == "summary-stale":
        summary["passed"] = 0
    elif corruption == "unfinished":
        sp.unlink()
    elif corruption == "fixture":
        summary["mode"] = "offline_database_fixture"
    elif corruption == "mixed-model":
        rows[0]["identity"]["model"] = "deepseek-v4-pro"
    else:
        for row in rows:
            row["identity"]["cli_version"] = "2.1.115"
        summary["runtime_identities"][0]["cli_version"] = "2.1.115"
    rp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    ap.write_text("".join(json.dumps(r) + "\n" for r in attempts), encoding="utf-8")
    if corruption != "unfinished":
        sp.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        compare(a, b)


def test_error_and_not_run_stay_in_planned_denominator_and_unknown_is_not_zero(
    tmp_path: Path,
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    statuses = ("failed", "error", "not_run", "not_run", "not_run", "not_run")
    write_batch(a, statuses=statuses)
    write_batch(b, statuses=statuses)
    output = compare(a, b)
    groups = output["groups"]
    assert isinstance(groups, dict)
    assert groups["a"]["measurement"]["errors"] == 1
    assert groups["a"]["measurement"]["not_run"] == 4
    assert output["runtime_identity_complete"] is False
    paired = output["paired"]
    assert isinstance(paired, dict) and paired["cost_unpaired_or_unknown_n"] == 5


def test_cli_missing_private_path_returns_utf8_error_without_leaking_path(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "eval.compare", "--runs", str(tmp_path / "PRIVATE-PATH"), "missing"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 1 and "比较未完成" in completed.stdout
    assert "PRIVATE" not in completed.stdout + completed.stderr


def rewrite_results(path: Path, rows: list[dict[str, object]]) -> None:
    (path / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    summary_path = path / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update({key: value for key, value in rate(rows).items() if key != "expected"})
    summary.update(measured_summary(rows, 3))
    summary_path.write_text(json.dumps(summary), encoding="utf-8")


def test_missing_measurements_remain_unknown_without_zero_cost_or_latency(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write_batch(a)
    write_batch(b)
    rows = [
        json.loads(line) for line in (b / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows[0].update(run_accounted=None, elapsed_seconds=None, http_attempts=None)
    rewrite_results(b, rows)
    output = compare(a, b)
    groups = output["groups"]
    assert isinstance(groups, dict)
    measured = groups["b"]["measurement"]
    assert measured["original_currency_cost"]["CNY"]["total"] is None
    assert measured["original_currency_cost"]["CNY"]["unknown_n"] == 1
    assert measured["latency_unknown_n"] == measured["http_attempts"]["unknown_n"] == 1
    paired = output["paired"]
    assert isinstance(paired, dict) and paired["cost_unpaired_or_unknown_n"] == 1
    delta = paired["original_currency_cost_delta_b_minus_a"]["CNY"]
    assert delta["total"] is None
    assert delta["measured_subtotal"] == "0.00"
    assert delta["measured_n"] == 5 and delta["unknown_n"] == 1


def test_different_provider_currencies_are_never_converted_or_subtracted(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write_batch(a)
    write_batch(b)
    rows = [
        json.loads(line) for line in (b / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for row in rows:
        row["identity"].update(provider="anthropic", model="claude-haiku-4-5-20251001")
        row["accounting_currency"] = "USD"
    rewrite_results(b, rows)
    output = compare(a, b)
    paired = output["paired"]
    assert isinstance(paired, dict)
    assert paired["original_currency_cost_delta_b_minus_a"] == {}
    assert paired["cost_unpaired_or_unknown_n"] == 6


def test_experiment_groups_cannot_reuse_contexts(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write_batch(a)
    write_batch(b)
    first = json.loads((a / "attempts.jsonl").read_text(encoding="utf-8").splitlines()[0])
    path = b / "attempts.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["context"] = first["context"]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="两个实验组"):
        compare(a, b)


@pytest.mark.parametrize(
    "field,value",
    [
        ("elapsed_seconds", True),
        ("first_progress_seconds", -1),
        ("http_attempts", 13),
        ("run_accounted", "NaN"),
    ],
)
def test_invalid_measurement_is_rejected_before_reporting(
    tmp_path: Path, field: str, value: object
) -> None:
    from backend.providers.probe.settings import ProbeError

    a, b = tmp_path / "a", tmp_path / "b"
    write_batch(a)
    write_batch(b)
    rows = [
        json.loads(line) for line in (b / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows[0][field] = value
    rewrite_results(b, rows)
    with pytest.raises((ValueError, ProbeError)):
        compare(a, b)
