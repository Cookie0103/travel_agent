"""内容指标：引用/身份/时效/未知分母和漏事实，不能靠少说刷准确率。"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext
from backend.domain.itinerary import RouteEstimate
from backend.domain.travel_request import TravelRequest
from eval.content import (
    ROOT,
    AnswerRecord,
    Claim,
    ContentReview,
    Fact,
    Grounding,
    assess_content,
    main,
)
from eval.suites import load_suite


def sample() -> tuple[AnswerRecord, ContentReview]:
    now = datetime.now(UTC)
    context = RunContext(uuid4())
    fragment = "门票100日元"
    record = EvidenceRecord(
        entity_id="place-a",
        field_path="ticket",
        value=100,
        kind="place",
        request_revision=0,
        conditions={"city": "京都"},
        provider="fixture",
        source_ref="private-source",
        content_version="v1",
        data_mode="fixture",
        retrieved_at=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=1),
    )
    answer = AnswerRecord(
        case_id="kyoto-matcha",
        context=context,
        request=TravelRequest(city="京都"),
        observed_at=now,
        text=fragment + "。private-output",
        evidence=(Grounding(context=context, record=record, invalidated=False),),
    )
    claim = Claim(
        claim_id="ticket",
        entity_id="place-a",
        field_path="ticket",
        value=100,
        start=0,
        end=len(fragment),
        excerpt=fragment,
        evidence_id=record.evidence_id,
    )
    review = ContentReview(
        case_id=answer.case_id,
        context=context,
        answer_sha256=answer.answer_sha256,
        reviewer="private-reviewer",
        claims=(claim,),
        required_facts=(Fact(entity_id="place-a", field_path="ticket", value=100),),
        claims_complete=True,
        requirements_complete=True,
    )
    return answer, review


def metric(result: dict[str, object], key: str) -> dict[str, object]:
    value = result[key]
    assert isinstance(value, dict)
    return value


def test_matching_evidence_is_scored_and_missing_required_fact_reduces_coverage() -> None:
    answer, review = sample()
    review = review.model_copy(
        update={
            "required_facts": review.required_facts
            + (Fact(entity_id="place-a", field_path="hours", value="09:00"),)
        }
    )
    result = assess_content(answer, review)
    assert metric(result, "fact_accuracy")["accuracy"] == 1
    assert result["fact_coverage"] == {"covered": 1, "required": 2, "coverage": 0.5}
    assert result["content_quality"] is None
    assert all(
        value not in json.dumps(result)
        for value in ("private-output", "private-source", "private-reviewer", "门票100")
    )


@pytest.mark.parametrize(
    "change",
    [
        {"invalidated": True},
        {"value": 200},
        {"value": True},
        {"source_ref": None},
        {"conditions": {"city": None}},
        {"valid_until": datetime.now(UTC) - timedelta(seconds=1)},
    ],
)
def test_invalidated_stale_wrong_or_unsupported_assertions_do_not_score(
    change: dict[str, object],
) -> None:
    answer, review = sample()
    grounding = answer.evidence[0]
    altered = (
        grounding.model_copy(update=change)
        if "invalidated" in change
        else grounding.model_copy(update={"record": grounding.record.model_copy(update=change)})
    )
    result = assess_content(answer.model_copy(update={"evidence": (altered,)}), review)
    assert metric(result, "fact_accuracy")["accuracy"] == 0
    assert metric(result, "fact_coverage")["coverage"] == 0


@pytest.mark.parametrize("kind", ["missing", "foreign", "duplicate"])
def test_missing_or_foreign_evidence_has_unknown_accuracy(kind: str) -> None:
    answer, review = sample()
    grounding = answer.evidence[0]
    evidence = (
        ()
        if kind == "missing"
        else (grounding, grounding)
        if kind == "duplicate"
        else (grounding.model_copy(update={"context": replace(answer.context, user_id=uuid4())}),)
    )
    result = assess_content(answer.model_copy(update={"evidence": evidence}), review)
    assert result["fact_accuracy"] == {
        "correct": 0,
        "incorrect": 0,
        "unknown": 1,
        "denominator": 1,
        "accuracy": None,
    }
    assert metric(result, "fact_coverage")["coverage"] is None


@pytest.mark.parametrize("field", ["context", "answer_sha256", "case_id", "claims"])
def test_foreign_answer_changed_text_or_nonexistent_excerpt_rejects_review(field: str) -> None:
    answer, review = sample()
    changes = {
        "context": replace(review.context, run_id=uuid4()),
        "answer_sha256": "0" * 64,
        "case_id": "other",
        "claims": (review.claims[0].model_copy(update={"start": 1}),),
    }
    with pytest.raises(ValueError):
        assess_content(answer, review.model_copy(update={field: changes[field]}))


def test_incomplete_inventory_or_empty_claims_never_produces_perfect_accuracy() -> None:
    answer, review = sample()
    for changes in ({"claims_complete": False}, {"claims": ()}):
        result = assess_content(answer, review.model_copy(update=changes))
        assert metric(result, "fact_accuracy")["accuracy"] is None
    incomplete = assess_content(answer, review.model_copy(update={"claims_complete": False}))
    assert metric(incomplete, "fact_coverage")["coverage"] is None
    empty = assess_content(answer, review.model_copy(update={"claims": ()}))
    assert metric(empty, "fact_coverage")["coverage"] == 0
    with pytest.raises(ValueError):
        assess_content(answer, review.model_copy(update={"claims": review.claims * 2}))
    with pytest.raises(ValueError):
        assess_content(
            answer, review.model_copy(update={"required_facts": review.required_facts * 2})
        )


def test_correct_assertion_plus_unresolved_unknown_claim_has_no_overall_accuracy() -> None:
    answer, review = sample()
    extra = "时间未知"
    start = len(answer.text)
    answer = answer.model_copy(update={"text": answer.text + extra})
    unknown = Claim(
        claim_id="hours",
        start=start,
        end=len(answer.text),
        excerpt=extra,
        entity_id="place-a",
        field_path="hours",
        value=None,
        certainty="unknown",
        evidence_id=uuid4(),
    )
    review = review.model_copy(
        update={"answer_sha256": answer.answer_sha256, "claims": (*review.claims, unknown)}
    )
    result = assess_content(answer, review)
    assert metric(result, "fact_accuracy")["correct"] == 1
    assert metric(result, "fact_accuracy")["accuracy"] is None
    assert metric(result, "fact_coverage")["coverage"] is None


def test_explicit_unknown_is_covered_but_never_becomes_asserted_fact_accuracy() -> None:
    answer, review = sample()
    record = answer.evidence[0].record.model_copy(update={"value": None})
    answer = answer.model_copy(
        update={
            "text": "费用未知",
            "evidence": (Grounding(context=answer.context, record=record, invalidated=False),),
        }
    )
    claim = review.claims[0].model_copy(
        update={
            "certainty": "unknown",
            "value": None,
            "excerpt": answer.text,
            "start": 0,
            "end": len(answer.text),
        }
    )
    review = review.model_copy(
        update={
            "answer_sha256": answer.answer_sha256,
            "claims": (claim,),
            "required_facts": (
                Fact(
                    entity_id=record.entity_id,
                    field_path=record.field_path,
                    value=None,
                    certainty="unknown",
                ),
            ),
        }
    )
    result = assess_content(answer, review)
    assert metric(result, "fact_coverage")["coverage"] == 1
    assert metric(result, "fact_accuracy")["accuracy"] is None
    claims = result["claims"]
    assert isinstance(claims, list) and claims[0]["reason"] == "explicit_unknown"


def test_route_estimate_requires_qualification_and_missing_source_cannot_score() -> None:
    answer, review = sample()
    route = RouteEstimate(
        from_place_id="a",
        to_place_id="b",
        transport="walk",
        departure=answer.observed_at,
        minutes=30,
        confidence="estimate",
    )
    request = answer.request.model_copy(update={"transport": "walk"})
    record = answer.evidence[0].record.model_copy(
        update={
            "field_path": "route",
            "kind": "route",
            "conditions": evidence_conditions(request, "route"),
            "value": route.model_dump(mode="json"),
        }
    )
    answer = answer.model_copy(
        update={
            "request": request,
            "text": "估算30分钟",
            "evidence": (Grounding(context=answer.context, record=record, invalidated=False),),
        }
    )
    claim = review.claims[0].model_copy(
        update={
            "field_path": "minutes",
            "value": 30,
            "excerpt": answer.text,
            "end": len(answer.text),
        }
    )
    review = review.model_copy(
        update={
            "answer_sha256": answer.answer_sha256,
            "claims": (claim,),
            "required_facts": (
                Fact(
                    entity_id=record.entity_id, field_path="minutes", value=30, certainty="estimate"
                ),
            ),
        }
    )
    assert assess_content(answer, review)["claims"] == [
        {"claim_id": "ticket", "result": "incorrect", "reason": "unlabelled_estimate"}
    ]
    qualified = review.model_copy(
        update={"claims": (claim.model_copy(update={"certainty": "estimate"}),)}
    )
    assert metric(assess_content(answer, qualified), "fact_accuracy")["accuracy"] == 1
    unsupported = answer.model_copy(
        update={
            "evidence": (
                Grounding(
                    context=answer.context,
                    record=record.model_copy(update={"provider": None}),
                    invalidated=False,
                ),
            )
        }
    )
    assert metric(assess_content(unsupported, qualified), "fact_accuracy")["accuracy"] == 0


def test_invalid_structured_evidence_and_unknown_paths_are_not_false_failures() -> None:
    answer, review = sample()
    record = answer.evidence[0].record.model_copy(
        update={"field_path": "catalog", "value": {"private-invalid": True}}
    )
    altered = answer.model_copy(
        update={"evidence": (Grounding(context=answer.context, record=record, invalidated=False),)}
    )
    assert metric(assess_content(altered, review), "fact_accuracy")["accuracy"] is None
    unknown_path = review.model_copy(
        update={"claims": (review.claims[0].model_copy(update={"field_path": "not-a-field"}),)}
    )
    assert metric(assess_content(answer, unknown_path), "fact_accuracy")["accuracy"] is None


def test_human_quality_is_only_from_explicit_valid_independent_input() -> None:
    answer, review = sample()
    payload = review.model_dump(mode="json")
    payload["human_quality"] = {
        "relevance": 4,
        "explanation": 3,
        "tradeoffs": 2,
        "reason": "private-human-reason",
        "rater": "private-human-rater",
    }
    result = assess_content(answer, ContentReview.model_validate(payload))
    assert result["content_quality"] == {
        "source": "human",
        "relevance": 4,
        "explanation": 3,
        "tradeoffs": 2,
    }
    assert "private-human" not in json.dumps(result)
    for invalid in (True, 6, -1):
        payload["human_quality"]["relevance"] = invalid
        with pytest.raises(ValidationError):
            ContentReview.model_validate(payload)


def test_private_cli_binds_original_case_keeps_inputs_and_redacts_invalid_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answer, review = sample()
    paths = [tmp_path / name for name in ("answer.json", "review.json")]
    for path, model in zip(paths, (answer, review), strict=True):
        path.write_text(model.model_dump_json(), encoding="utf-8")
    before = [p.read_bytes() for p in paths]
    monkeypatch.setattr(
        "sys.argv", ["content", "--answer", str(paths[0]), "--review", str(paths[1])]
    )
    assert main() == 0 and "private-" not in capsys.readouterr().out
    assert [p.read_bytes() for p in paths] == before
    paths[1].write_text("private-invalid-json", encoding="utf-8")
    assert main() == 1 and "private-invalid-json" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "corrupt", [None, "text", "context", "duplicate", "manifest", "missing_capture"]
)
def test_results_cli_requires_original_manifest_attempt_and_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    corrupt: str | None,
) -> None:
    answer, review = sample()
    cases, metadata = load_suite(ROOT, "legacy", "dev")
    case = next(c for c in cases if c.case_id == answer.case_id)
    manifest: dict[str, object] = {
        "selected_cases": [case.model_dump(mode="json")],
        "evaluation_suite": metadata,
    }
    row: dict[str, object] = {
        "case_id": answer.case_id,
        "repeat": 1,
        "text": answer.text,
        "content_record": answer.model_dump(mode="json"),
    }
    binding: dict[str, object] = {
        "case_id": answer.case_id,
        "repeat": 1,
        "context": answer.model_dump(mode="json")["context"],
    }
    if corrupt == "text":
        row["text"] = "private-changed-answer"
    if corrupt == "context":
        binding["context"] = {
            "user_id": str(uuid4()),
            "session_id": str(uuid4()),
            "run_id": str(uuid4()),
        }
    if corrupt == "manifest":
        manifest["selected_cases"] = None
    if corrupt == "missing_capture":
        row["content_record"] = None
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps(row) + "\n", encoding="utf-8")
    (tmp_path / "attempts.jsonl").write_text(
        (json.dumps(binding) + "\n") * (2 if corrupt == "duplicate" else 1), encoding="utf-8"
    )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    annotation = tmp_path / "review.json"
    annotation.write_text(review.model_dump_json(), encoding="utf-8")
    before = [p.read_bytes() for p in (results, annotation)]
    monkeypatch.setattr(
        "sys.argv",
        [
            "content",
            "--results",
            str(results),
            "--case-id",
            answer.case_id,
            "--review",
            str(annotation),
        ],
    )
    assert main() == (0 if corrupt is None else 1)
    output = capsys.readouterr().out
    assert "private-" not in output
    assert [p.read_bytes() for p in (results, annotation)] == before
    if corrupt is None:
        assert json.loads(output)["record_source"] == "evaluation_result"
