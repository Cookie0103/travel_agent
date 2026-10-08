"""三维内容评分复用SDK/温度/持久日志，非法或缺真人配对不能冒充校准。"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.agent.persona import JudgeKind
from backend.domain.execution import RunContext
from backend.limits import ProbeError
from backend.providers.claude_agent.live import run_live
from backend.providers.claude_agent.worker import run as run_worker
from eval.content import HumanQuality, QualityScore
from eval.judge import evaluate, load_samples, main, score_report
from eval.persona import Sample, content_calibration
from eval.persona import main as calibration_main
from tests.test_persona_judge import report, sample

SCORE = QualityScore(relevance=4, explanation=3, tradeoffs=2, reason="test-auxiliary-rating")


@pytest.mark.parametrize("kind,enabled", [("unknown", True), ("", True), ("content", False)])
def test_invalid_judge_kind_is_rejected_before_budget_and_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: JudgeKind,
    enabled: bool,
) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-flash")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("非法评审不读付费设置")

    monkeypatch.setattr("backend.providers.claude_agent.live.load_runtime_settings", forbidden)
    with pytest.raises(ProbeError):
        run_live("data", RunContext(uuid4()), tmp_path, persona_judge=enabled, judge_kind=kind)
    result = asyncio.run(
        run_worker(
            {
                "prompts": ["data"],
                "user_id": str(uuid4()),
                "session_id": str(uuid4()),
                "run_id": str(uuid4()),
                "cli_version": "2.1.114",
                "persona_judge": enabled,
                "judge_kind": kind,
            },
            tmp_path / "unused",
        )
    )
    assert result == {"status": "error", "code": "validation"}
    assert not (tmp_path / ".cache").exists()


@pytest.mark.parametrize(
    "response",
    [
        SCORE.model_dump_json(),
        '{"score":4,"reason":"persona"}',
        '{"relevance":true,"explanation":3,"tradeoffs":2,"reason":"invalid"}',
        "not JSON",
    ],
)
def test_content_json_has_three_strict_dimensions_and_preserves_human(response: str) -> None:
    human = HumanQuality(
        relevance=3, explanation=2, tradeoffs=1, reason="human-reason", rater="human"
    )
    original = sample().model_copy(update={"human_quality": human})
    actual = {**report(), "results": [{"outcome": {"text": response, "code": None}}]}
    scored, status = score_report(original, actual, "deepseek-flash", kind="content")
    assert status == ("scored" if response == SCORE.model_dump_json() else "judge_error")
    assert scored.human_quality == human and scored.human_score is None
    assert original.judge_response is None


def test_content_calibration_projects_each_dimension_and_invalid_persona_json_is_error() -> None:
    human = HumanQuality(
        relevance=3, explanation=2, tradeoffs=1, reason="human-reason", rater="human"
    )
    samples = [
        Sample(
            case_id=f"case-{i}",
            user_input="京都",
            text="answer",
            human_quality=human,
            judge_response=SCORE.model_dump_json(),
            judge_model="deepseek-flash",
            judge_temperature=0,
        )
        for i in range(20)
    ]
    result = content_calibration(samples)
    assert result["status"] == "calibrated"
    dimensions = result["dimensions"]
    assert isinstance(dimensions, dict)
    for dimension in dimensions.values():
        assert dimension["paired"] == 20 and dimension["within_one_rate"] == 1
    for changes in (
        {"human_quality": None},
        {"judge_response": '{"score":4,"reason":"wrong-schema"}'},
        {"judge_temperature": 1},
    ):
        invalid = content_calibration([s.model_copy(update=changes) for s in samples])
        assert invalid["status"] == "pending"
        if "judge_response" in changes:
            metrics = invalid["dimensions"]
            assert isinstance(metrics, dict) and metrics["relevance"]["judge_errors"] == 20
    assert samples[0].judge_response == SCORE.model_dump_json()


def test_mixed_human_scales_or_replayed_samples_stop_before_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("非法批次不能预检额度")

    monkeypatch.setattr("eval.judge.check_evaluation_size", forbidden)
    for data in (
        sample().model_copy(update={"human_score": 2}),
        sample().model_copy(update={"judge_model": "already-rated"}),
    ):
        with pytest.raises(ValueError):
            evaluate([data], tmp_path, kind="content")
    path = tmp_path / "samples.jsonl"
    path.write_text(sample().model_dump_json(), encoding="utf-8")
    assert load_samples(path, kind="content") == [sample()]


def test_content_cli_default_preparation_makes_no_model_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "samples.jsonl"
    path.write_text(sample().model_dump_json(), encoding="utf-8")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("默认只准备，不调用评审")

    monkeypatch.setattr("eval.judge.evaluate", forbidden)
    monkeypatch.setattr("sys.argv", ["judge", str(path), "--kind", "content"])
    assert main() == 0 and json.loads(capsys.readouterr().out)["http_attempts"] == 0


def test_existing_content_score_accepts_later_human_annotation_without_new_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    human = HumanQuality(
        relevance=3, explanation=2, tradeoffs=1, reason="annotation", rater="human"
    )
    rows = [
        sample(str(i)).model_copy(
            update={
                "judge_response": SCORE.model_dump_json(),
                "judge_model": "deepseek-flash",
                "judge_temperature": 0,
                "human_quality": human,
            }
        )
        for i in range(20)
    ]
    path = tmp_path / "scored.jsonl"
    path.write_text("\n".join(s.model_dump_json() for s in rows), encoding="utf-8")
    before = path.read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("后补真人分只离线校准，不能重新请求模型")

    monkeypatch.setattr("eval.judge.run_live", forbidden)
    monkeypatch.setattr("sys.argv", ["persona", str(path), "--kind", "content"])
    assert calibration_main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "calibrated" and path.read_bytes() == before
    with pytest.raises(ValueError):
        load_samples(path, kind="content")  # 同一已评分数据不能重新付费。
