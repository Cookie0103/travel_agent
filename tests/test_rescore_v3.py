"""F5：全量重算只写新文件；每轮说法必须由本轮事件支持。"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from eval.rescore_simulator import write_rescore
from eval.simulator_metrics import claims_pass, dialogue_claims


def test_cards_in_another_run_cannot_support_this_answer() -> None:
    user, session = uuid4(), uuid4()
    first, second = RunContext(user, session, uuid4()), RunContext(user, session, uuid4())
    events = (
        RuntimeEvent(
            first,
            "presentation",
            presentation={"data": {"component": "choice", "kind": "budget_relaxation"}},
        ),
        RuntimeEvent(second, "text"),
    )
    turns: list[dict[str, object]] = [
        {"status": "completed", "session_id": str(session), "answer": answer, "presentations": []}
        for answer in ("预算确认卡已展示。", "请点击预算确认卡。")
    ]
    claims = dialogue_claims(turns, events)
    assert claims[0]["passed"] is True
    assert claims[1]["card"] is False
    assert claims_pass(claims) is False
    assert claims_pass(dialogue_claims(turns[:1], events)) is None


def test_all_rows_rescored_without_changing_original_or_overwriting_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("eval.rescore_simulator.ROOT", tmp_path)
    source = tmp_path / "results.jsonl"
    rows = [
        {
            "case_id": "v2-user-pace",
            "trial": i,
            "status": "passed",
            "checks": {"hotel_delivery": True},
            "steps": [],
            "dialogue": [],
        }
        for i in range(1, 4)
    ]
    source.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    hashes = tmp_path / "hashes.json"
    hashes.write_text(json.dumps({"results.jsonl": digest}), encoding="utf-8")
    summary = write_rescore(source, hashes)
    assert summary["n"] == 3 and summary["original_passed"] == 3 and summary["passed"] == 0
    output = tmp_path / "rescored-v3-results.jsonl"
    rescored = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [r["trial"] for r in rescored] == [1, 2, 3]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    unchanged = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_rescore(source, hashes)
    assert output.read_bytes() == unchanged
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        write_rescore(source, hashes)


def test_unfrozen_input_cannot_borrow_another_files_frozen_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("eval.rescore_simulator.ROOT", tmp_path)
    frozen = tmp_path / "frozen.jsonl"
    frozen.write_text("{}\n", encoding="utf-8")
    hashes = tmp_path / "hashes.json"
    hashes.write_text(
        json.dumps({"frozen.jsonl": hashlib.sha256(frozen.read_bytes()).hexdigest()}),
        encoding="utf-8",
    )
    candidate = tmp_path / "modified-copy.jsonl"
    candidate.write_text('{"different": true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="冻结输入hash"):
        write_rescore(candidate, hashes)


def test_new_turn_uses_finished_time_and_current_card_expiry_but_old_time_stays_unknown() -> None:
    now = datetime.now(UTC)
    context = RunContext(uuid4(), uuid4(), uuid4())
    events = (
        RuntimeEvent(
            context,
            "presentation",
            presentation={
                "data": {
                    "component": "hotel_comparison",
                    "cards": [{"expires_at": (now + timedelta(minutes=5)).isoformat()}],
                }
            },
        ),
    )
    turn: dict[str, object] = {
        "status": "completed",
        "session_id": str(context.session_id),
        "run_id": str(context.run_id),
        "answer": "报价已过期。",
        "presentations": [],
    }
    assert dialogue_claims([turn], events)[0]["expiry"] is None
    assert dialogue_claims([{**turn, "answered_at": now.isoformat()}], events)[0]["expiry"] is False
