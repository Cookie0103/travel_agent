"""重复/未执行/未知测量及原币种报表，失败不能在下一轮静默重试。"""

import json
from pathlib import Path

import pytest

from backend.domain.execution import RunContext
from eval.cases import Case
from eval.graders import Observation
from eval.report import measured_summary, token_summary
from eval.run import run_cases


def case() -> Case:
    return Case(
        case_id="report-control",
        source="self-authored regression",
        adaptation="not model quality",
        input="京都景点",
    )


@pytest.mark.asyncio
async def test_repeat_creates_three_distinct_attempts_and_does_not_retry_after_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts: list[RunContext] = []

    async def observe(
        case: Case, live: bool, context: RunContext
    ) -> tuple[Observation, dict[str, object]]:
        contexts.append(context)
        return Observation("completed", "有结果", ()), {
            "identity": {
                "provider": "fake",
                "model": "fixture-demo",
                "sdk_version": "none",
                "cli_version": "none",
            }
        }

    monkeypatch.setattr("eval.run.observe", observe)
    output = tmp_path / "three"
    summary = await run_cases([case()], output, repeats=3)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["comparison_group"] == "not_applicable_fixture"
    assert summary["repetitions"] == 3 and summary["expected_attempts"] == 3
    assert summary["passed"] == 3 and len({c.session_id for c in contexts}) == 3
    attempts = [
        json.loads(line)
        for line in (output / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [r["repeat"] for r in attempts] == [1, 2, 3]
    assert len({r["context"]["run_id"] for r in attempts}) == 3
    assert summary["original_currency_cost"] == {} and summary["semantic_fact_quality"] is None

    async def fail(
        case: Case, live: bool, context: RunContext
    ) -> tuple[Observation, dict[str, object]]:
        raise ValueError("dependency failure")

    monkeypatch.setattr("eval.run.observe", fail)
    failed = await run_cases([case()], tmp_path / "failure", repeats=3, live=True)
    manifest = json.loads((tmp_path / "failure/manifest.json").read_text(encoding="utf-8"))
    assert manifest["comparison_group"] == "search_only"  # 无DB偏好，不能冒充B3。
    assert failed["errors"] == 1 and failed["not_run"] == 2
    assert (
        len((tmp_path / "failure" / "attempts.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    )


def test_report_keeps_original_currencies_unknown_cost_and_failure_denominators() -> None:
    rows: list[dict[str, object]] = [
        {
            "case_id": "first",
            "status": "passed",
            "repeat": 1,
            "elapsed_seconds": 1.0,
            "accounting_currency": "CNY",
            "run_accounted": "0.04",
        },
        {
            "case_id": "second",
            "status": "failed",
            "repeat": 1,
            "elapsed_seconds": 3.0,
            "accounting_currency": "USD",
            "run_accounted": "0.10",
        },
        {
            "case_id": "first",
            "status": "error",
            "repeat": 2,
            "elapsed_seconds": 5.0,
            "accounting_currency": "CNY",
            "run_accounted": None,
        },
        {"case_id": "second", "status": "not_run", "repeat": 2},
        {"case_id": "first", "status": "not_run", "repeat": 3},
        {"case_id": "second", "status": "not_run", "repeat": 3},
    ]
    report = measured_summary(rows, 3)
    cost = report["original_currency_cost"]
    assert isinstance(cost, dict)
    assert cost["CNY"]["total"] is None and cost["CNY"]["measured_subtotal"] == "0.04"
    assert cost["USD"]["total"] == "0.10"
    assert report["rule_rate_range"] == {"min": 0.5, "max": 0.5}
    assert report["latency_seconds"] == {
        "measured_n": 3,
        "p50": 3.0,
        "p95": 5.0,
        "method": "nearest-rank",
    }
    assert report["semantic_fact_quality"] is None


def test_unknown_tokens_and_request_counts_never_become_zero() -> None:
    tokens = {
        "input_tokens": 10,
        "output_tokens": 2,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    assert token_summary([{"tokens": tokens}])["totals"] == tokens
    for invalid in (None, {}, {**tokens, "output_tokens": True}, {**tokens, "input_tokens": -1}):
        assert token_summary([{"tokens": tokens}, {"tokens": invalid}])["totals"] is None
    report = measured_summary(
        [
            {"repeat": 1, "status": "passed", "http_attempts": 2},
            {"repeat": 1, "status": "error"},
        ],
        1,
    )
    assert report["http_attempts"] == {"total": None, "measured_subtotal": 2, "unknown_n": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("repeat", [0, 4, True])
async def test_invalid_repeat_never_creates_output_or_runtime(tmp_path: Path, repeat: int) -> None:
    with pytest.raises(ValueError, match="重复次数"):
        await run_cases([case()], tmp_path / "invalid", repeats=repeat)
    assert not (tmp_path / "invalid").exists()
