"""离线私有参数评审入口：绑定原案例，不公开附件，不改原评分。"""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from eval.assess import assess, main
from eval.diagnostics import ArgumentFact
from tests.test_eval_metrics import setup


def test_assessment_uses_private_facts_without_exporting_arguments(tmp_path: Path) -> None:
    _, context, events = setup()
    call_id = events[0].tool_call_id
    assert call_id is not None
    paths = [tmp_path / name for name in ("events.jsonl", "actual.json", "expected.json")]
    paths[0].write_text(
        "\n".join(json.dumps(asdict(e), default=str) for e in events), encoding="utf-8"
    )
    fact = ArgumentFact(context, call_id, {"city": "京都", "query": "private-parameter"})
    for path in paths[1:]:
        path.write_text(json.dumps([asdict(fact)], default=str), encoding="utf-8")
    before = [path.read_bytes() for path in paths]
    result = assess(*paths, suite="legacy", split="dev", case_id="kyoto-matcha")
    metric = result["tool_call_accuracy"]
    assert isinstance(metric, dict) and metric["accuracy"] == 1
    assert "private-parameter" not in json.dumps(result)
    assert [path.read_bytes() for path in paths] == before
    with pytest.raises(ValueError):
        assess(*paths, suite="legacy", split="dev", case_id="not-in-suite")


def test_assessment_cli_invalid_attachment_does_not_print_private_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("private-not-json", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "assess",
            "--events",
            str(path),
            "--actual",
            str(path),
            "--expected",
            str(path),
            "--case-id",
            "kyoto-matcha",
        ],
    )
    assert main() == 1
    assert "private-not-json" not in capsys.readouterr().out
