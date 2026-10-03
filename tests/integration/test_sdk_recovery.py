"""R02/R12：实际CLI分进程恢复私有SDK会话，损坏/丢失/条件变化安全新建。"""

import asyncio
import json
import shutil
from dataclasses import replace
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from backend.domain.execution import RunContext, RunResult
from backend.domain.travel_request import RequestPatch
from backend.mcp.bridge import sdk_tool_name
from backend.persistence.database import Database
from backend.services.travel import TravelService
from tests.integration.sdk_helper import run_database_worker
from tests.integration.test_travel import travel_setup as travel_setup
from tests.test_sdk_cli_offline import scripted_response

pytestmark = pytest.mark.integration


def sdk_id(report: dict[str, object]) -> str:
    results = TypeAdapter(list[RunResult]).validate_python(report["results"])
    identity = results[0].outcome.sdk_session_id
    assert identity is not None
    return identity


@pytest.mark.skipif(not shutil.which("claude"), reason="需要实际CLI，不访问真实模型")
def test_native_sdk_process_restart_and_snapshot_fallbacks(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
) -> None:
    runner, travel, context = travel_setup
    forward = partial(
        scripted_response, tool_calls=((sdk_tool_name("load_skill"), {"name": "hotel-comparison"}),)
    )
    first, guard = run_database_worker(travel, context, tmp_path, forward, "读取条件")
    assert first["status"] == "success" and not guard.failures, (
        first.get("reason"),
        first.get("code"),
        guard.failures,
    )
    assert first["checkpoint_persisted"] is True
    previous_id = sdk_id(first)
    checkpoint = tmp_path / "worker" / "checkpoint.json"
    for mutation in ("none", "missing", "corrupt", "revision", "identity"):
        if mutation in {"missing", "corrupt"}:
            transcripts = list(
                (tmp_path / "worker" / "config" / "projects").glob(f"*/{previous_id}.jsonl")
            )
            assert len(transcripts) == 1
            if mutation == "missing":
                transcripts[0].unlink()
            else:
                with transcripts[0].open("ab") as stream:
                    stream.write(b'{"half_record":')
        elif mutation == "revision":
            revision = runner.run(travel.get_request(context)).revision
            runner.run(
                travel.patch_request(
                    context,
                    RequestPatch.model_validate(
                        {"expected_revision": revision, "set": {"rooms": 2}}
                    ),
                )
            )
        elif mutation == "identity":
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            payload["reference"]["identity"]["cli_version"] = "different"
            checkpoint.write_text(json.dumps(payload), encoding="utf-8")
        report, guard = run_database_worker(
            travel, replace(context, run_id=uuid4()), tmp_path, forward, "继续读取最新条件"
        )
        assert report["status"] == "success" and not guard.failures, (
            mutation,
            report.get("code"),
            report.get("reason"),
            guard.failures,
        )
        assert report["checkpoint_persisted"] is True
        actual_id = sdk_id(report)
        assert report["resume_mode"] == ("sdk" if mutation == "none" else "business_snapshot")
        assert (actual_id == previous_id) is (mutation == "none")
        previous_id = actual_id


@pytest.mark.skipif(not shutil.which("claude"), reason="需要实际CLI，不访问真实模型")
def test_condition_change_during_sdk_round_does_not_certify_old_context_as_new_revision(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
) -> None:
    runner, travel, context = travel_setup
    calls = 0
    scripted = partial(
        scripted_response, tool_calls=((sdk_tool_name("load_skill"), {"name": "hotel-comparison"}),)
    )

    def forward(body: bytes) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:

            async def change() -> None:
                database = Database(travel.database.engine.url)
                try:
                    await TravelService(database).patch_request(
                        context,
                        RequestPatch.model_validate({"expected_revision": 1, "set": {"rooms": 2}}),
                    )
                finally:
                    await database.close()

            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as loop:
                loop.run(change())
        return scripted(body)

    first, guard = run_database_worker(travel, context, tmp_path, forward, "读取酒店比较步骤")
    assert first["status"] == "success" and not guard.failures
    assert first["checkpoint_persisted"] is False
    assert not (tmp_path / "worker" / "checkpoint.json").exists()
    assert runner.run(travel.get_request(context)).revision == 2
    second, guard = run_database_worker(
        travel, replace(context, run_id=uuid4()), tmp_path, scripted, "读取最新条件"
    )
    assert second["status"] == "success" and not guard.failures
    assert second["resume_mode"] == "business_snapshot" and sdk_id(second) != sdk_id(first)
