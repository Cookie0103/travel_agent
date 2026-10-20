"""v3 rubric评审：载荷含证据、严格解析、失败不影响trial、翻转率、人工校准表与一致性。"""

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from backend.agent.persona import evaluation_judge_prompt
from backend.domain.execution import RunContext, RuntimeEvent
from backend.providers.claude_agent.evaluation import judge_combo_invalid
from eval.v3_cases import V3Case
from eval.v3_judge import (
    GENERIC,
    cohen_kappa,
    compute_agreement,
    export_sheet,
    flip_rates,
    items_for,
    judge_payload,
    judge_report,
    judge_scores,
    judge_trial,
    parse_output,
    write_transcript,
)
from eval.v3_score import CardObs, DbFacts, Observation, TurnObs

T0 = datetime(2026, 10, 20, tzinfo=UTC)
CONTEXT = RunContext(uuid4(), uuid4(), uuid4())
CASE = V3Case.model_validate(
    {
        "case_id": "unit",
        "category": "main_flow",
        "title": "t",
        "user_script": [{"say": "你好"}],
        "rubric": [{"id": f"r{i}", "q": f"问题{i}"} for i in range(3)],
    }
)
ALL_IDS = ["r0", "r1", "r2", *[i for i, _ in GENERIC]]


def obs() -> Observation:
    call = uuid4()
    events = (
        RuntimeEvent(CONTEXT, "tool_started", tool_name="search_hotel_offers", tool_call_id=call),
        RuntimeEvent(
            CONTEXT,
            "tool_finished",
            tool_name="search_hotel_offers",
            tool_call_id=call,
            result_empty=True,
            occurred_at=T0 + timedelta(seconds=1),
        ),
        RuntimeEvent(CONTEXT, "tool_finished", tool_name="estimate_routes", code="validation"),
    )
    turn = TurnObs(
        1, "A", "s", "r", "completed", None, "没有找到酒店", T0, T0 + timedelta(seconds=3),
        events=events, cards=(CardObs("trip_ask", ("pace",)),),
        user_text="找酒店（点击trip_ask卡：confirm）",
    )  # fmt: skip
    return Observation(
        turns=(turn,),
        validation=({"status": "conflict", "code": "x"}, {"status": "unknown", "code": "y"}),
        state={"request": {"city": "京都", "secret_note": "不应出现"}},
        db=DbFacts(
            draft_exists=True,
            hotel_selected_segments=1,
            memory_current=(
                {"key": "pace", "value": "慢节奏", "scope": "long_term", "status": "active"},
            ),
        ),
    )


def reply(verdicts: dict[str, str]) -> str:
    return json.dumps(
        {"results": [{"id": i, "verdict": v, "reason": "理由" * 30} for i, v in verdicts.items()]},
        ensure_ascii=False,
    )


def test_rubric_is_a_registered_judge_kind_with_a_prompt() -> None:
    assert "unknown" in evaluation_judge_prompt("rubric")
    assert not judge_combo_invalid("rubric", True, database=False, supplier=False, workflow=False)
    assert judge_combo_invalid("rubric", False, database=False, supplier=False, workflow=False)


def test_payload_carries_transcript_tools_cards_and_db_without_leaking_extra_fields() -> None:
    payload = judge_payload(CASE, obs())
    assert [i["id"] for i in payload["items"]] == ALL_IDS  # type: ignore[attr-defined]
    text = json.dumps(payload, ensure_ascii=False)
    assert "找酒店（点击trip_ask卡：confirm）" in text and "没有找到酒店" in text
    tools = payload["tools"][0]["calls"]  # type: ignore[index]
    assert {(t["tool"], t["status"], t["code"]) for t in tools} == {
        ("search_hotel_offers", "empty", None),
        ("estimate_routes", "error", "validation"),
    }
    assert payload["cards"][0]["issued"] == [{"kind": "trip_ask", "groups": ["pace"]}]  # type: ignore[index]
    db = payload["db"]
    assert db["validation"] == {"conflict": 1, "unknown": 1, "verified": 0}  # type: ignore[index]
    assert db["hotel_picks"] == 1 and db["active_memory"][0]["value"] == "慢节奏"  # type: ignore[index]
    assert "secret_note" not in text


def test_parse_accepts_fences_truncates_reason_and_rejects_bad_output() -> None:
    items = items_for(CASE)
    good = reply(dict.fromkeys(ALL_IDS, "yes") | {"g-tone": "unknown"})
    parsed = parse_output("```json\n" + good + "\n```", items)
    assert parsed["g-tone"]["verdict"] == "unknown" and len(parsed["r0"]["reason"]) == 40
    for bad in (
        "不是json",
        reply({**dict.fromkeys(ALL_IDS, "yes"), "r0": "maybe"}),
        reply({k: "yes" for k in ALL_IDS[:-1]}),  # 缺一项
        reply({**dict.fromkeys(ALL_IDS, "yes"), "extra": "yes"}),
    ):
        with pytest.raises(ValueError):
            parse_output(bad, items)


def test_judge_failure_is_recorded_not_raised() -> None:
    def broken(kind: str, payload: object, root: Path) -> tuple[str, dict[str, object]]:
        raise RuntimeError("boom")

    result = judge_trial(CASE, obs(), broken, Path("."))
    assert result["error"] == "judge_error:RuntimeError" and result["items"] is None
    garbage = judge_trial(CASE, obs(), lambda k, p, r: ("垃圾", {}), Path("."))
    assert str(garbage["error"]).startswith("judge_error:")
    assert judge_scores(result) == {} and judge_scores(None) == {}


def test_yes_rate_unknown_count_and_numeric_scores() -> None:
    verdicts = dict.fromkeys(ALL_IDS, "yes") | {
        "r1": "no",
        "g-disclose": "unknown",
        "g-no-reask": "unknown",
    }
    seen: list[Any] = []

    def call(kind: str, payload: object, root: Path) -> tuple[str, dict[str, object]]:
        seen.append((kind, payload))
        return reply(verdicts), {}

    result = judge_trial(CASE, obs(), call, Path("."))
    assert seen[0][0] == "rubric" and len(seen) == 1  # 每个trial一次调用
    assert result["error"] is None and result["unknown_n"] == 2
    assert result["yes_rate"] == pytest.approx(4 / 5)
    scores = judge_scores(result)
    assert scores["judge_yes_rate"] == pytest.approx(0.8) and scores["judge_unknown_n"] == 2.0
    assert scores["judge_r1"] == 0.0 and scores["judge_r0"] == 1.0
    assert "judge_g-disclose" not in scores  # unknown不推
    assert all(type(v) is float for v in scores.values())


def test_paraphrase_check_reports_flip_rate_ignoring_unknown() -> None:
    calls = iter(
        [
            reply(dict.fromkeys(ALL_IDS, "yes")),
            reply(dict.fromkeys(ALL_IDS, "yes") | {"g-tone": "no", "g-disclose": "unknown"}),
        ]
    )
    result = judge_trial(CASE, obs(), lambda k, p, r: (next(calls), {}), Path("."), check=True)
    rows: list[dict[str, Any]] = [
        {"judge": result},
        {"judge": {"paraphrase": {"g-tone": {"first": "no", "second": "no"}}}},
    ]
    flips = flip_rates(rows)
    assert flips["g-tone"] == {"comparable": 2, "flips": 1, "flip_rate": 0.5}
    assert "g-disclose" not in flips  # 含unknown的配对不计
    second_fails = iter([reply(dict.fromkeys(ALL_IDS, "yes"))])

    def once(kind: str, payload: object, root: Path) -> tuple[str, dict[str, object]]:
        return next(second_fails), {}

    partial = judge_trial(CASE, obs(), once, Path("."), check=True)
    assert partial["error"] is None and "paraphrase_error" in partial  # 自检失败不影响主评审


def test_report_aggregates_items_cases_and_errors() -> None:
    ok = judge_trial(
        CASE, obs(), lambda k, p, r: (reply(dict.fromkeys(ALL_IDS, "yes")), {}), Path(".")
    )
    rows: list[dict[str, Any]] = [
        {"case_id": "unit", "judge": ok},
        {"case_id": "unit", "judge": {"error": "judge_error:X", "items": None}},
        {"case_id": "unit", "judge": None},
    ]
    report = judge_report(rows)
    assert report["trials_judged"] == 1 and report["judge_errors"] == 1
    assert report["items"]["g-tone"]["yes_rate"] == 1.0  # type: ignore[index]
    assert report["by_case"]["unit"]["yes"] == 7  # type: ignore[index]


def test_transcript_is_written_to_the_private_run_dir(tmp_path: Path) -> None:
    relative = write_transcript(tmp_path, CASE, 2, obs())
    text = (tmp_path / relative).read_text(encoding="utf-8")
    assert (
        relative == "transcripts/unit-2.txt"
        and "没有找到酒店" in text
        and "search_hotel_offers=empty" in text
    )


def test_kappa_basics() -> None:
    assert cohen_kappa(["yes", "no", "yes"], ["yes", "no", "yes"]) == 1.0
    assert cohen_kappa([], []) is None
    assert cohen_kappa(["yes", "no"], ["no", "yes"]) == -1.0


def make_run(tmp_path: Path) -> Path:
    rows = []
    for trial in range(1, 7):
        verdict = "yes" if trial % 2 else "no"
        rows.append(
            {
                "case_id": "unit",
                "trial": trial,
                "transcript_path": f"transcripts/unit-{trial}.txt",
                "judge": {
                    "items": {
                        "g-tone": {"q": "语气？", "verdict": verdict, "reason": ""},
                        "g-disclose": {"q": "披露？", "verdict": "unknown", "reason": ""},
                    }
                },
            }
        )
    rows.append({"case_id": "unit", "trial": 7, "judge": {"error": "judge_error:X", "items": None}})
    run = tmp_path / "run1"
    run.mkdir()
    (run / "trials.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
    )
    return run


def test_sheet_export_hides_judge_verdicts_and_agreement_ignores_unknown(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    sheet = export_sheet(run)
    with sheet.open(encoding="utf-8") as handle:
        lines = list(csv.DictReader(handle))
    assert len(lines) == 12  # 6个评审成功的trial x 2项；judge_error的trial不出表
    assert list(lines[0]) == [
        "run",
        "case_id",
        "trial",
        "item_id",
        "question",
        "transcript_path",
        "rater_a",
        "rater_b",
    ]
    assert all(line["rater_a"] == "" and line["run"] == "run1" for line in lines)
    assert "yes" not in sheet.read_text(encoding="utf-8").replace("g-", "")  # 没有泄露评审结论
    for line in lines:
        if line["item_id"] == "g-tone":
            truth = "yes" if int(line["trial"]) % 2 else "no"
            line["rater_a"] = truth  # A全对
            line["rater_b"] = (
                truth if int(line["trial"]) < 6 else ("yes" if truth == "no" else "no")
            )  # B错1个
        else:
            line["rater_a"] = line["rater_b"] = "yes"  # judge是unknown：忽略
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(lines[0]))
        writer.writeheader()
        writer.writerows(lines)
    report = compute_agreement(run, sheet)
    tone = report["items"]["g-tone"]  # type: ignore[index]
    assert tone["judge_vs_a"]["agreement"] == 1.0 and tone["judge_vs_a"]["n"] == 6
    assert tone["judge_vs_b"]["agreement"] == pytest.approx(5 / 6)
    assert tone["a_vs_b"]["kappa"] is not None and tone["reaches_80"] is True
    disclose = report["items"]["g-disclose"]  # type: ignore[index]
    assert disclose["judge_vs_a"]["n"] == 0 and disclose["reaches_80"] is False
    assert report["candidates"] == ["g-tone"]


def test_agreement_needs_enough_pairs(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    sheet = export_sheet(run)
    with sheet.open(encoding="utf-8") as handle:
        lines = [line for line in csv.DictReader(handle) if line["item_id"] == "g-tone"][:3]
    for line in lines:
        line["rater_a"] = line["rater_b"] = "yes"
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(lines[0]))
        writer.writeheader()
        writer.writerows(lines)
    assert compute_agreement(run, sheet)["candidates"] == []  # 少于5对不能算达标
