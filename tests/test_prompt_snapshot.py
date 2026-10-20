"""prompt快照：三道门缺一不落盘，内容只写入worker工作目录文件。"""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import make_url

from backend.adapters.evaluation_faults import is_eval_database
from backend.domain.execution import RunContext
from backend.providers.claude_agent.live import prompt_snapshot_enabled
from backend.providers.claude_agent.worker import snapshot_prompt

EVAL_DSN = "postgresql://u:p@localhost:5432/travel_agent_eval_" + "a" * 32
ON = {"TRAVEL_EVAL_PROMPT_SNAPSHOT": "1"}


def test_worker_writes_only_when_payload_flag_is_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    context = RunContext(uuid4(), uuid4(), uuid4())
    for payload in (
        {},
        {"prompt_snapshot": False},
        {"prompt_snapshot": "true"},
        {"prompt_snapshot": 1},
    ):
        snapshot_prompt(dict[str, object](payload), context, "SECRET")
    assert list(tmp_path.iterdir()) == []
    snapshot_prompt({"prompt_snapshot": True}, context, "SYSTEM 慢节奏")
    written = tmp_path / f"system-prompt-{context.run_id}.txt"
    assert written.read_text(encoding="utf-8") == "SYSTEM 慢节奏"


@pytest.mark.parametrize(
    ("requested", "dsn", "environ", "expected"),
    [
        (True, EVAL_DSN, ON, True),
        (False, EVAL_DSN, ON, False),
        (True, EVAL_DSN, {}, False),
        (True, EVAL_DSN, {"TRAVEL_EVAL_PROMPT_SNAPSHOT": "0"}, False),
        (True, None, ON, False),
        (True, "postgresql://u:p@localhost:5432/travel_agent", ON, False),
        (True, "postgresql://u:p@prod.example.com:5432/travel_agent_eval_" + "a" * 32, ON, False),
        (True, EVAL_DSN + "?sslmode=require", ON, False),
    ],
)
def test_all_three_gates_are_required(
    requested: bool, dsn: str | None, environ: dict[str, str], expected: bool
) -> None:
    assert prompt_snapshot_enabled(requested, dsn, environ) is expected


def test_is_eval_database_matches_fault_validation_rules() -> None:
    assert is_eval_database(EVAL_DSN)
    assert not is_eval_database("postgresql://localhost/travel_agent_eval_xyz")


def test_guarded_runtime_default_is_off_and_run_service_never_enables_it() -> None:
    import inspect

    from backend.agent.fixture_runtime import FixtureRuntime
    from backend.providers.claude_agent.application import GuardedRuntime
    from backend.services.runs import RunService
    from backend.tools.travel import TravelToolExecutor

    assert (
        GuardedRuntime(Path("."), "postgresql://localhost/x", provider="deepseek").prompt_snapshot
        is False
    )
    assert "prompt_snapshot" not in inspect.getsource(RunService)
    service = RunService.__new__(RunService)
    service.runtime_factory = None
    service.database = SimpleNamespace(engine=SimpleNamespace(url=make_url(EVAL_DSN)))  # type: ignore[assignment]
    runtime = service._runtime("deepseek", TravelToolExecutor.__new__(TravelToolExecutor))
    assert isinstance(runtime, GuardedRuntime) and runtime.prompt_snapshot is False
    assert isinstance(
        service._runtime("offline", TravelToolExecutor.__new__(TravelToolExecutor)), FixtureRuntime
    )
