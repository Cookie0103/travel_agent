"""M0.7：固定温度实际转发、错误与断电记录，不用假人工分数证明校准。"""

import asyncio
import json
import os
import shutil
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext
from backend.providers.claude_agent.budget import Budget
from backend.providers.claude_agent.environment import find_cli, worker_environment
from backend.providers.claude_agent.guard import Guard, serve
from backend.providers.claude_agent.live import run_live
from backend.providers.claude_agent.process import invoke_worker
from backend.providers.claude_agent.request import validate_request
from backend.providers.claude_agent.worker import run as run_worker
from backend.providers.probe.settings import ProbeError, Settings
from backend.tools.workflow import WorkflowName
from eval.judge import evaluate, load_samples, score_report
from eval.persona import Sample
from tests.test_sdk_cli_offline import scripted_response
from tests.test_sdk_guard import request_body, response_body


def sample(case_id: str = "one") -> Sample:
    return Sample(case_id=case_id, user_input="京都", text="目前只支持京都。")


@pytest.mark.parametrize(
    "extra",
    [
        {"database_dsn": "private database"},
        {"supplier_url": "http://127.0.0.1"},
        {"workflow": "search"},
        {"provider": "anthropic"},
        {"persona_judge": "true"},
        {"prompts": ["one", "two"]},
    ],
)
def test_judge_worker_rejects_business_or_foreign_provider_before_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: dict[str, object]
) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-flash")

    async def forbidden(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("无效评审不能启动SDK")

    monkeypatch.setattr("backend.providers.claude_agent.worker.run_prompts", forbidden)
    actual = asyncio.run(
        run_worker(
            {
                "user_id": str(uuid4()),
                "session_id": str(uuid4()),
                "run_id": str(uuid4()),
                "cli_version": "2.1.114",
                "prompts": ["one"],
                "persona_judge": True,
                **extra,
            },
            tmp_path / "unused-cli",
        )
    )
    assert actual == {"status": "error", "code": "validation"}


@pytest.mark.parametrize(
    "database_dsn,supplier_url,workflow,persona_judge",
    [
        ("private database", None, None, True),
        (None, "http://127.0.0.1", None, True),
        (None, None, "search", True),
        (None, None, None, "true"),
    ],
)
def test_judge_live_rejects_business_before_budget_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_dsn: str | None,
    supplier_url: str | None,
    workflow: WorkflowName | None,
    persona_judge: bool,
) -> None:
    def forbidden(*args: object) -> Settings:
        raise AssertionError("无效评审不能读取收费配置")

    monkeypatch.setattr("backend.providers.claude_agent.live.load_runtime_settings", forbidden)
    with pytest.raises(ProbeError):
        run_live(
            "one",
            RunContext(uuid4()),
            tmp_path,
            persona_judge=persona_judge,
            database_dsn=database_dsn,
            supplier_url=supplier_url,
            workflow=workflow,
        )
    assert not (tmp_path / ".cache").exists()


def report() -> dict[str, object]:
    return {
        "status": "success",
        "guard_failures": [],
        "events": [],
        "identity": {"provider": "deepseek", "model": "deepseek-flash"},
        "requests": [{"temperature": 0}],
        "http_attempts": 1,
        "results": [{"outcome": {"text": '{"score":4,"reason":"自然"}', "code": None}}],
    }


def test_normal_travel_bytes_unchanged_and_judge_temperature_proved(tmp_path: Path) -> None:
    body = request_body(temperature=1)
    assert validate_request(body, "deepseek-flash").body == body
    captured: list[bytes] = []

    def forward(body: bytes) -> tuple[int, bytes]:
        captured.append(body)
        return 200, response_body()

    guard = Guard(
        Settings("synthetic", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5)),
        forward,
        allowed_tools=frozenset(),
        temperature=0,
    )
    body = request_body(tools=[], thinking={"type": "disabled"}, temperature=1)
    status, _ = guard.accept("/v1/messages", "Bearer " + guard.token, body)
    assert status == 200 and guard.attempts == 1
    assert json.loads(captured[0])["temperature"] == 0
    assert guard.observations[0]["temperature"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"thinking": {"type": "enabled", "budget_tokens": 100}},
        {"thinking": None},
        {"top_p": 1},
        {"top_k": 4},
        {"tools": [{"name": "Bash"}]},
    ],
)
def test_judge_invalid_sampling_or_tools_rejected_before_charge(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    settings = {"tools": [], "thinking": {"type": "disabled"}, **changes}
    budget = Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5))
    guard = Guard(
        Settings("synthetic", "deepseek-flash", Decimal(5), Decimal(0)),
        budget,
        lambda b: (_ for _ in ()).throw(AssertionError()),
        allowed_tools=frozenset(),
        temperature=0,
    )
    status, _ = guard.accept("/v1/messages", "Bearer " + guard.token, request_body(**settings))
    assert status == 400 and guard.attempts == budget.totals()[0] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"status": "error"},
        {"guard_failures": ["blocked"]},
        {"requests": [{"temperature": True}]},
        {"requests": [{}]},
        {"http_attempts": 2},
        {"identity": {"provider": "deepseek", "model": "other"}},
        {"events": [{"kind": "tool_started"}]},
    ],
)
def test_missing_runtime_proof_is_not_a_score(change: dict[str, object]) -> None:
    original = sample()
    scored, status = score_report(original, {**report(), **change}, "deepseek-flash")
    assert status == "runtime_error" and scored == original


def test_score_json_parse_error_separate_and_human_not_modified() -> None:
    original = sample().model_copy(update={"human_score": 2, "human_rater": "test-person"})
    scored, status = score_report(original, report(), "deepseek-flash")
    assert status == "scored" and scored.human_score == 2 and scored.judge_temperature == 0
    bad = {**report(), "results": [{"outcome": {"text": "not JSON", "code": None}}]}
    scored, status = score_report(original, bad, "deepseek-flash")
    assert status == "judge_error" and scored.judge_response == "not JSON"
    assert scored.human_score == 2


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [sample(), sample()],
        [sample().model_copy(update={"judge_response": "old"})],
        [sample(str(i)) for i in range(31)],
    ],
)
def test_invalid_or_previously_scored_batch_not_replayed(
    tmp_path: Path, rows: list[Sample]
) -> None:
    path = tmp_path / "samples.jsonl"
    path.write_text("\n".join(s.model_dump_json() for s in rows), encoding="utf-8")
    with pytest.raises(ValueError):
        load_samples(path)


def test_runtime_error_stops_later_samples_after_durable_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("eval.judge.check_evaluation_size", lambda root, size: None)
    monkeypatch.setattr(
        "eval.judge.load_runtime_settings",
        lambda env: Settings("synthetic", "deepseek-flash", Decimal(5), Decimal(0)),
    )
    calls = 0

    def fail(prompt: str, context: object, root: Path, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        assert list((root / ".cache/persona").glob("*/attempts.jsonl"))[0].read_text(
            encoding="utf-8"
        )
        raise ProbeError("unavailable", "private-error")

    monkeypatch.setattr("eval.judge.run_live", fail)
    directory = evaluate([sample(), sample("two")], tmp_path)
    rows = [
        json.loads(line)
        for line in (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert calls == 1 and [r["status"] for r in rows] == ["runtime_error", "not_run"]
    assert "private-error" not in (directory / "results.jsonl").read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("claude"), reason="真实CLI未安装，不冒充SDK验证")
@pytest.mark.parametrize("response_kind", ["score", "invalid_json", "unauthorized_tool"])
def test_real_sdk_judge_has_no_tools_and_guard_sets_temperature_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response_kind: str
) -> None:
    def forward(body: bytes) -> tuple[int, bytes]:
        request = json.loads(body)
        assert request.get("tools", []) == [] and request["temperature"] == 0
        if response_kind == "unauthorized_tool":
            request["messages"] = []
            return scripted_response(json.dumps(request).encode(), tool_calls=(("Bash", {}),))
        request["messages"] = [{"content": [{"type": "tool_result", "content": "synthetic"}]}]
        status, content = scripted_response(json.dumps(request).encode())
        text = "not JSON" if response_kind == "invalid_json" else '{"score":4,"reason":"brief"}'
        return status, content.replace(
            b'"text": "[\\"synthetic\\"]"', ('"text": ' + json.dumps(text)).encode()
        )

    guard = Guard(
        Settings("synthetic", "deepseek-flash", Decimal(5), Decimal(0)),
        Budget(tmp_path / "ledger", tmp_path / "old", Decimal(5)),
        forward,
        allowed_tools=frozenset(),
        temperature=0,
    )
    sampling: list[dict[str, object]] = []
    accept = guard.accept

    def inspect(path: str, token: str, body: bytes) -> tuple[int, bytes]:
        raw = json.loads(body)
        sampling.append({k: raw.get(k) for k in ("thinking", "temperature", "top_p", "top_k")})
        return accept(path, token, body)

    monkeypatch.setattr(guard, "accept", inspect)
    with serve(guard) as endpoint:
        directory = tmp_path / "worker"
        env = worker_environment(
            os.environ,
            directory,
            Path(__file__).resolve().parents[1],
            endpoint,
            guard.token,
            "deepseek-flash",
        )
        actual = invoke_worker(
            find_cli(os.environ),
            directory,
            env,
            module="backend.providers.claude_agent.worker",
            payload={
                "prompts": ['{"candidate":"brief"}'],
                "user_id": str(uuid4()),
                "session_id": str(uuid4()),
                "run_id": str(uuid4()),
                "cli_version": "2.1.114",
                "persona_judge": True,
            },
        )
    actual.update(
        requests=guard.observations, http_attempts=guard.attempts, guard_failures=guard.failures
    )
    scored, status = score_report(sample(), actual, "deepseek-flash")
    expected = {
        "score": "scored",
        "invalid_json": "judge_error",
        "unauthorized_tool": "runtime_error",
    }
    assert status == expected[response_kind], (
        guard.failure_details,
        sampling,
        actual.get("reason"),
    )
    assert guard.attempts == 1
    if response_kind == "unauthorized_tool":
        assert actual["status"] == "error" and scored.judge_response is None
    else:
        assert scored.judge_response is not None
