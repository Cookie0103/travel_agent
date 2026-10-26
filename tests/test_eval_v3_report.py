"""v3报告：pass^k、Success@T、失败原因表、scatter.csv列。"""

import csv
import json
from pathlib import Path

import pytest

from eval.v3_report import SCATTER_COLUMNS, success_at, summarize, write_reports


def row(case_id: str, trial: int, success: bool, **kw: object) -> dict[str, object]:
    return {
        "case_id": case_id,
        "category": kw.pop("category", "main_flow"),
        "trial": trial,
        "repeat": trial,
        "status": "passed" if success else "failed",
        "success": success,
        "reason": None if success else kw.pop("reason", "hard:x"),
        "total_s": kw.pop("total_s", 30.0),
        "max_turn_s": kw.pop("max_turn_s", 20.0),
        "ttfua_s": kw.pop("ttfua_s", 5.0),
        "soft_score": kw.pop("soft_score", None),
        "judge_yes_rate": None,
        "cost_cny": kw.pop("cost_cny", "0.5"),
        "claim_unknown": kw.pop("claim_unknown", 0),
        **kw,
    }


ROWS = [
    row("a", 1, True),
    row("a", 2, True),
    row("a", 3, True, max_turn_s=130.0),
    row("b", 1, True),
    row("b", 2, False, reason="false_claim:budget", category="memory"),
    row("b", 3, True, soft_score=0.5),
]


def test_pass_power_and_success_at() -> None:
    summary = summarize(ROWS, 3)
    assert summary["pass_power_1"] == 1.0  # 两题第1次都成功
    assert summary["pass_power_3"] == 0.5  # 只有a三次全成功
    assert summary["success_at"] == {
        "60": pytest.approx(4 / 6),
        "120": pytest.approx(4 / 6),
        "180": pytest.approx(5 / 6),
    }
    assert success_at([], 60) is None


def test_pass_power_3_is_none_when_repeat_is_lower() -> None:
    summary = summarize([r for r in ROWS if r["trial"] == 1], 1)
    assert summary["pass_power_3"] is None and summary["pass_power_1"] == 1.0


def test_failure_table_cost_and_unknown_claims() -> None:
    data = [
        *ROWS,
        row("c", 1, False, reason="over_time", category="fault", claim_unknown=2, cost_cny="1.5"),
    ]
    summary = summarize(data, 3, stopped="max_cny_reached:9")
    assert summary["failures"] == {
        "false_claim:budget": {"memory": 1},
        "over_time": {"fault": 1},
    }
    assert summary["cost_cny"]["total"] == "4.5"  # type: ignore[index]
    assert summary["claim_unknown"] == {
        "count": 2,
        "trials_with_unknown": 1,
        "note": "unknown不判失败，单独显示",
    }
    assert summary["stopped"] == "max_cny_reached:9"
    assert summary["total_s"]["p50"] == 30.0  # type: ignore[index]


def test_missing_cost_makes_total_unknown_instead_of_zero() -> None:
    data = [row("a", 1, True), {**row("a", 2, True)}]
    del data[1]["cost_cny"]
    assert summarize(data, 2)["cost_cny"]["total"] is None  # type: ignore[index]


def test_cache_hit_rate_needs_every_trial_measured() -> None:
    tokens = {"input_tokens": 10, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 0}
    cached = [row("a", 1, True, cache=tokens), row("a", 2, True, cache=tokens)]
    assert summarize(cached, 2)["cache"] == {
        "measured_n": 2,
        "unknown_n": 0,
        "hit_rate": 0.75,
        "measured_hit_rate": 0.75,
    }
    partial = summarize([*cached, row("a", 3, True, cache=None)], 3)["cache"]
    assert partial["hit_rate"] is None and partial["measured_hit_rate"] == 0.75  # type: ignore[index]
    assert summarize(ROWS, 3)["cache"]["hit_rate"] is None  # type: ignore[index]


def test_write_reports_creates_scatter_summary_and_markdown(tmp_path: Path) -> None:
    write_reports(
        tmp_path,
        {"run_name": "r1", "live": False, "profile": "human", "git_sha": "abcdef1234"},
        ROWS,
        3,
        None,
    )
    with (tmp_path / "scatter.csv").open(encoding="utf-8") as handle:
        lines = list(csv.reader(handle))
    assert (
        tuple(lines[0])
        == SCATTER_COLUMNS
        == (
            "case_id",
            "category",
            "trial",
            "success",
            "total_s",
            "max_turn_s",
            "ttfua_s",
            "soft_score",
            "judge_yes_rate",
            "cost_cny",
            "reason",
        )
    )
    assert len(lines) == 7 and lines[5][3] == "0" and lines[5][-1] == "false_claim:budget"
    assert lines[6][7] == "0.5" and lines[1][7] == ""  # 无软分写空，不写0
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["trials"] == 6
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "pass^3" in markdown and "false_claim:budget" in markdown and "离线夹具" in markdown
    assert "输入缓存命中率：n/a" in markdown
