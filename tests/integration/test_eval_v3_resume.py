"""v3断点续跑：跳过已完成、重跑infra_error、限额停止、中断写报告、与不中断结果一致。

run_trial被打桩，不跑模型也不碰真实接口；main()走真实的临时PG与报告流程。
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import URL

from eval.v3_run import completed_keys, latest_rows, main, resume_command

pytestmark = pytest.mark.integration

CASES = [
    {
        "case_id": cid,
        "category": category,
        "title": cid,
        "user_script": [{"say": "你好"}],
        "rubric": [{"id": f"r{i}", "q": "q"} for i in range(3)],
    }
    for cid, category in (("case-a", "main_flow"), ("case-b", "memory"))
]


def fake_row(case_id: str, trial: int, infra: str | None = None) -> dict[str, object]:
    success = infra is None
    return {
        "case_id": case_id,
        "category": "main_flow" if case_id == "case-a" else "memory",
        "trial": trial,
        "repeat": trial,
        "status": "passed" if success else "failed",
        "success": success,
        "reason": None if success else "infra_error",
        "trace_id": None,
        "flags": {"success": success, "hard_pass": True, "within_time": None},
        "soft_score": None,
        "metrics": {"ttfua_s": 1.0, "turn_latency_max_s": 2.0},
        "total_s": 3.0,
        "max_turn_s": 2.0,
        "ttfua_s": 1.0,
        "claim_unknown": 0,
        "tools": {
            "missing_required": [],
            "forbidden_used": [],
            "hallucinated": [],
            "blocked": False,
        },
        "memory_layers": {},
        "judge": None,
        "judge_yes_rate": None,
        "infra_error": infra,
        "cost_cny": "0",
    }


class Script:
    """按(case, trial)给出每次调用的结果：None=成功，字符串=infra_error，'INTERRUPT'=Ctrl-C。"""

    def __init__(self, plan: dict[tuple[str, int], list[str | None]] | None = None) -> None:
        self.plan = plan or {}
        self.calls: list[tuple[str, int]] = []

    async def __call__(
        self, business: Any, case: Any, trial: int, config: Any, trace_id: Any
    ) -> Any:
        key = (case.case_id, trial)
        self.calls.append(key)
        queue = self.plan.get(key, [])
        outcome = queue.pop(0) if queue else None
        if outcome == "INTERRUPT":
            raise KeyboardInterrupt
        return fake_row(case.case_id, trial, outcome)


@pytest.fixture
def env(postgres_url: URL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in CASES) + "\n")
    monkeypatch.setattr("eval.v3_run.RUNS_DIR", tmp_path / "runs")
    saved = dict(os.environ)  # main()会写TRAVEL_PROFILE等进程环境变量，必须还原，免得污染后续测试
    try:
        yield cases
    finally:
        os.environ.clear()
        os.environ.update(saved)


def start(script: Script, monkeypatch: pytest.MonkeyPatch, cases: Path, *extra: str) -> int:
    monkeypatch.setattr("eval.v3_run.run_trial", script)
    return main(["--cases", str(cases), "--repeat", "2", *extra])


def only_run(tmp_path: Path) -> Path:
    (directory,) = (tmp_path / "runs").iterdir()
    return directory


def lines(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (directory / "trials.jsonl").read_text().splitlines()]


def test_pure_helpers_latest_row_wins_and_infra_rows_are_not_completed() -> None:
    rows = [
        fake_row("a", 1),
        fake_row("a", 2, "provider_error"),
        fake_row("a", 2),
        fake_row("b", 1, "timeout"),
    ]
    assert [(r["case_id"], r["trial"], r["infra_error"]) for r in latest_rows(rows)] == [
        ("a", 1, None),
        ("a", 2, None),
        ("b", 1, "timeout"),
    ]
    assert completed_keys(rows, 2) == {("a", 1), ("a", 2)}
    assert completed_keys(rows[:2], 2) == {("a", 1)}  # a,2只有infra_error行：待重跑
    assert completed_keys(rows, 1) == {("a", 1)}  # 超出repeat的不算


def test_resume_skips_completed_and_reruns_infra_error(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = Script({("case-a", 2): ["provider_error"]})
    assert start(first, monkeypatch, env) == 0
    directory = only_run(tmp_path)
    assert len(lines(directory)) == 4
    capsys.readouterr()
    second = Script()
    assert start(second, monkeypatch, env, "--resume", str(directory)) == 0
    assert second.calls == [("case-a", 2)]  # 只重跑infra_error的那个
    assert "已完成 3，待跑 1" in capsys.readouterr().out
    rows = lines(directory)
    assert len(rows) == 5  # 旧行保留，新行追加
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["trials"] == 4 and summary["failures"] == {}  # 以最新一行为准
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["resumed_from"][0]["completed"] == 3 and manifest["stopped"] is None
    # 全部完成后再续跑：什么都不跑
    third = Script()
    assert start(third, monkeypatch, env, "--resume", str(directory)) == 0 and third.calls == []


def test_interrupt_writes_reports_prints_resume_command_and_matches_uninterrupted_run(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert start(Script(), monkeypatch, env) == 0
    reference = only_run(tmp_path)
    expected = {n: (reference / n).read_text() for n in ("summary.json", "scatter.csv")}
    monkeypatch.setattr("eval.v3_run.RUNS_DIR", tmp_path / "runs2")
    capsys.readouterr()
    interrupted = Script({("case-b", 1): ["INTERRUPT"]})
    assert start(interrupted, monkeypatch, env) == 130
    directory = next((tmp_path / "runs2").iterdir())
    out = capsys.readouterr().out
    assert "接着跑：uv run python scripts/dev.py eval-v3 --resume " + str(directory) in out
    assert f"--repeat 2 --profile human --cases {env}" in out
    assert len(lines(directory)) == 2  # 在途trial不记录
    assert json.loads((directory / "manifest.json").read_text())["stopped"] == "interrupted"
    assert json.loads((directory / "summary.json").read_text())["trials"] == 2  # 已完成部分的报告
    assert start(Script(), monkeypatch, env, "--resume", str(directory)) == 0
    for name, text in expected.items():
        assert (directory / name).read_text() == text  # 与不中断的运行一致


def test_resume_refuses_changed_cases_or_selection_unless_forced(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert start(Script(), monkeypatch, env) == 0
    directory = only_run(tmp_path)
    script = Script()
    capsys.readouterr()
    # 选择的case-id不同
    assert start(script, monkeypatch, env, "--resume", str(directory), "--case-id", "case-a") == 2
    assert "所选case-id" in capsys.readouterr().out and script.calls == []
    # 题库内容变了
    env.write_text(env.read_text() + "\n")
    assert start(script, monkeypatch, env, "--resume", str(directory)) == 2
    assert "题库文件内容" in capsys.readouterr().out and script.calls == []
    # 强制续跑：不报错（所有trial都已完成，所以什么都不跑）
    assert start(script, monkeypatch, env, "--resume", str(directory), "--resume-force") == 0
    # 目录不是运行目录
    assert start(script, monkeypatch, env, "--resume", str(tmp_path / "nope")) == 2
    assert "manifest.json" in capsys.readouterr().out


def test_two_consecutive_limit_errors_stop_the_run(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = Script({("case-a", 2): ["rate_limited"], ("case-b", 1): ["rate_limited"]})
    assert start(script, monkeypatch, env, "--profile", "relaxed") == 1
    directory = only_run(tmp_path)
    assert script.calls == [("case-a", 1), ("case-a", 2), ("case-b", 1)]  # (b,2)没有被烧掉
    out = capsys.readouterr().out
    assert (
        "quota_suspected:rate_limited" in out
        and "接着跑：uv run python scripts/dev.py eval-v3" in out
    )
    assert f"--resume {directory} --repeat 2 --profile relaxed" in out
    assert (
        json.loads((directory / "manifest.json").read_text())["stopped"]
        == "quota_suspected:rate_limited"
    )
    assert (directory / "report.md").exists() and len(lines(directory)) == 3
    # 续跑：两条限额行都会重跑，外加没跑过的(b,2)
    again = Script()
    assert start(again, monkeypatch, env, "--resume", str(directory), "--profile", "relaxed") == 0
    assert again.calls == [("case-a", 2), ("case-b", 1), ("case-b", 2)]


def test_non_consecutive_or_non_limit_errors_do_not_stop(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    separated = Script({("case-a", 1): ["rate_limited"], ("case-b", 1): ["service:429"]})
    assert start(separated, monkeypatch, env) == 0  # 中间有成功的trial，连击被打断
    assert len(separated.calls) == 4
    monkeypatch.setattr("eval.v3_run.RUNS_DIR", env.parent / "runs3")
    plain = Script({("case-a", 1): ["provider_error"], ("case-a", 2): ["timeout"]})
    assert start(plain, monkeypatch, env) == 0  # provider_error/timeout不当作限额
    assert len(plain.calls) == 4


def test_resume_command_carries_the_flags_that_matter() -> None:
    from eval.v3_run import build_parser

    args = build_parser().parse_args(
        ["--live", "--trace-cloud", "--repeat", "3", "--case-id", "x", "--case-id", "y",
         "--max-cny", "9", "--no-judge"]
    )  # fmt: skip
    command = resume_command(args, Path("/d"))
    assert command == (
        "uv run python scripts/dev.py eval-v3 --live --trace-cloud --resume /d --repeat 3 "
        "--profile human --case-id x --case-id y --max-cny 9.0 --no-judge"
    )
