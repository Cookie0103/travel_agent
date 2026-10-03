"""评测规则保护失败样本；离线与真实模型的分母、标签及费用入口不能混淆。"""

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from eval.cases import Case, load_cases
from eval.graders import Observation, grade, response_matches
from eval.run import ROOT, run_cases


def example(**changes: object) -> Case:
    return Case.model_validate(
        {
            "case_id": "example",
            "source": "test",
            "adaptation": "test",
            "input": "京都攻略",
            "required_tools": ["search_content"],
            "allowed_tools": ["search_content"],
            "should_have_results": True,
            **changes,
        }
    )


def observation(*, empty: bool = False, unfinished: bool = False) -> Observation:
    context, call_id = RunContext(uuid4()), uuid4()
    start = RuntimeEvent(context, "tool_started", tool_name="search_content", tool_call_id=call_id)
    events = (
        (start,)
        if unfinished
        else (
            start,
            replace(
                start,
                kind="tool_finished",
                result_empty=empty,
            ),
        )
    )
    return Observation("completed", "有来源的回答", events)


def test_21_ids_are_unique_and_keep_unimplemented_planning_expectation() -> None:
    cases = load_cases(ROOT / "eval" / "cases" / "datamind_adapted.jsonl", "dev")
    assert len(cases) == 21
    plan = next(c for c in cases if c.case_id == "plan-kyoto-2nights")
    assert "stage_plan_change" in plan.required_tools
    assert sum(c.response_rule == "unsupported" for c in cases) == 5


def test_m1_suite_adds_nine_business_specs_with_normal_and_clarification_controls() -> None:
    cases = load_cases(
        tuple(
            ROOT / "eval" / "cases" / name for name in ("datamind_adapted.jsonl", "travel_m1.jsonl")
        ),
        "dev",
    )
    assert len(cases) == 30 and len({case.case_id for case in cases}) == 30
    ids = {case.case_id for case in cases}
    assert {
        "hotel-complete-control",
        "hotel-missing-ages",
        "plan-complete-control",
        "plan-missing-dates",
        "claim-confirmation-blocked",
    } <= ids
    for case in cases:
        if case.case_id in {"hotel-missing-ages", "plan-missing-dates"}:
            assert case.allowed_tools == ["update_travel_request"]
            assert case.response_rule == "clarify" and not case.required_tools


@pytest.mark.parametrize("empty,unfinished", [(True, False), (False, True)])
def test_empty_or_unfinished_tools_do_not_pass_result_rule(empty: bool, unfinished: bool) -> None:
    checks = grade(example(), observation(empty=empty, unfinished=unfinished))
    assert checks["has_results"] is False
    assert not all(checks.values())


def test_legal_tool_path_passes_but_additional_forbidden_call_fails() -> None:
    actual = observation()
    assert all(grade(example(), actual).values())
    extra = replace(actual.events[0], tool_name="book_hotel", tool_call_id=uuid4())
    checks = grade(example(), replace(actual, events=(*actual.events, extra)))
    assert not checks["no_forbidden_tool"] and not checks["no_unnecessary_tools"]


def test_orphan_tool_result_is_not_evidence_of_success() -> None:
    actual = observation()
    actual = replace(actual, events=(actual.events[-1],))
    checks = grade(example(), actual)
    assert not checks["has_results"] and not checks["tool_success"]


def test_unsupported_rule_does_not_accept_affirmative_support_claim() -> None:
    assert not response_matches("unsupported", "箱根位于京都服务范围，我可以直接推荐。")
    assert response_matches("unsupported", "目前只支持京都旅行，暂不支持箱根，想看看京都吗？")


def test_case_loader_rejects_duplicate_or_unsupported_state(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    raw = example().model_dump_json()
    path.write_text(raw + "\n" + raw, encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        load_cases(path, "dev")
    path.write_text(
        example(initial_state={"unimplemented": True}).model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="尚不支持"):
        load_cases(path, "dev")


@pytest.mark.asyncio
async def test_default_eval_runs_real_fixture_tools_and_reports_failure_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("offline must not call live")

    monkeypatch.setattr("eval.run.run_live", forbidden)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured-but-not-authorized")
    directory = tmp_path / "result"
    summary = await run_cases(
        [example(required_tools=[], allowed_tools=[], should_have_results=False)], directory
    )
    assert summary["mode"] == "offline_fixture" and summary["passed"] == 0
    row = json.loads((directory / "results.jsonl").read_text(encoding="utf-8"))
    assert row["status"] == "failed" and row["http_attempts"] == 0
    assert "no_unnecessary_tools" in row["failed_checks"]
    metadata = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert metadata["code_commit"] and metadata["schema_sha256"]
    assert not any(".env" in path or "vendor" in path for path in metadata["sha256"])


@pytest.mark.asyncio
async def test_runtime_error_stops_suite_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def fail(*args: object) -> object:
        nonlocal calls
        calls += 1
        raise ValueError("private downstream failure")

    monkeypatch.setattr("eval.run.observe", fail)
    summary = await run_cases(
        [example(), example(case_id="second")], tmp_path / "result", live=True
    )
    assert calls == 1 and summary["errors"] == 1 and summary["not_run"] == 1
    assert summary["rule_pass_rate"] is None


@pytest.mark.asyncio
async def test_interruption_keeps_started_case_and_private_session_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "interrupted"

    async def interrupt(case: Case, live: bool, context: RunContext) -> object:
        started = json.loads((directory / "attempts.jsonl").read_text(encoding="utf-8"))
        assert started["case_id"] == case.case_id
        assert started["context"]["session_id"] == str(context.session_id)
        raise KeyboardInterrupt

    monkeypatch.setattr("eval.run.observe", interrupt)
    with pytest.raises(KeyboardInterrupt):
        await run_cases([example()], directory, live=True)
    assert (directory / "results.jsonl").read_text(encoding="utf-8") == ""
    assert (directory / "attempts.jsonl").read_text(encoding="utf-8")
