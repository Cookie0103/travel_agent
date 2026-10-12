"""内容评审必须在真实PG销毁前捕获本人事实；失效/依赖错误不伪装成完整验证。"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import URL

from backend.domain.catalog import Place
from backend.domain.hotels import HotelOffer
from backend.domain.travel_request import RequestPatch
from backend.services.common import ServiceError
from backend.services.hotels import HotelService
from backend.tools.travel import TravelToolExecutor
from eval.content import AnswerRecord, Claim, ContentReview, Fact, assess_content
from eval.database import database_evaluation, selector_runner
from eval.run import run_cases
from tests.integration.test_database_eval import search_case
from tests.integration.test_eval_state import REQUEST

pytestmark = pytest.mark.integration


def review_fact(
    answer: AnswerRecord,
    evidence_id: object,
    entity: str,
    field: str,
    value: object,
    certainty: str = "asserted",
) -> dict[str, object]:
    claim = Claim.model_validate(
        {
            "claim_id": "field",
            "start": 0,
            "end": len(answer.text),
            "excerpt": answer.text,
            "entity_id": entity,
            "field_path": field,
            "value": value,
            "certainty": certainty,
            "evidence_id": evidence_id,
        }
    )
    review = ContentReview(
        case_id=answer.case_id,
        context=answer.context,
        answer_sha256=answer.answer_sha256,
        reviewer="independent-test-annotation",
        claims=(claim,),
        required_facts=(
            Fact.model_validate(
                {"entity_id": entity, "field_path": field, "value": value, "certainty": certainty}
            ),
        ),
        claims_complete=True,
        requirements_complete=True,
    )
    return assess_content(answer, review)


def test_real_catalog_subfield_correct_wrong_unknown_and_unavailable_paths(
    postgres_url: URL,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            case = search_case()
            context = await business.prepare(case)
            result = await TravelToolExecutor(business.travel).execute(
                context, "search_places", {"city": "京都"}
            )
            assert result.code is None
            captured = await business.content_record(case, context, "景点陈述由独立标注核对")
            source = next(
                g.record
                for g in captured.evidence
                if Place.model_validate(g.record.value).opening_hours is None
            )
            place = Place.model_validate(source.value)
            good = await business.content_record(case, context, place.name)
            correct = review_fact(good, source.evidence_id, source.entity_id, "name", place.name)
            assert correct["fact_accuracy"] == {
                "correct": 1,
                "incorrect": 0,
                "unknown": 0,
                "denominator": 1,
                "accuracy": 1,
            }
            wrong = await business.content_record(case, context, "不同景点名称")
            bad = review_fact(wrong, source.evidence_id, source.entity_id, "name", wrong.text)
            assert bad["claims"] == [
                {"claim_id": "field", "result": "incorrect", "reason": "wrong_value"}
            ]
            unknown = await business.content_record(case, context, "营业时间未知")
            explicit = review_fact(
                unknown, source.evidence_id, source.entity_id, "opening_hours", None, "unknown"
            )
            assert explicit["fact_coverage"] == {"covered": 1, "required": 1, "coverage": 1}
            absent = review_fact(
                good, source.evidence_id, source.entity_id, "nonexistent", place.name
            )
            assert absent["fact_accuracy"] == {
                "correct": 0,
                "incorrect": 0,
                "unknown": 1,
                "denominator": 1,
                "accuracy": None,
            }

    with selector_runner() as runner:
        runner.run(exercise())


def test_real_hotel_total_uses_existing_card_and_missing_tax_remains_unknown(
    postgres_url: URL,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            case = search_case(initial_state={"request": REQUEST})
            context = await business.prepare(case)
            records = await HotelService(business.travel).search(context, 1, limit=6)
            known = next(r for r in records if HotelOffer.model_validate(r.value).total is not None)
            offer = HotelOffer.model_validate(known.value)
            total = offer.card()["total"]
            answer = await business.content_record(case, context, f"模拟含税费总价{total}日元")
            assert review_fact(answer, known.evidence_id, known.entity_id, "total", total)[
                "fact_accuracy"
            ] == {"correct": 1, "incorrect": 0, "unknown": 0, "denominator": 1, "accuracy": 1}
            missing = next(r for r in records if HotelOffer.model_validate(r.value).total is None)
            partial = await business.content_record(case, context, "税费不全，含税费总价未知")
            assert review_fact(
                partial, missing.evidence_id, missing.entity_id, "total", None, "unknown"
            )["fact_coverage"] == {"covered": 1, "required": 1, "coverage": 1}
            fabricated = await business.content_record(case, context, "含税费总价10000日元")
            wrong = review_fact(
                fabricated, missing.evidence_id, missing.entity_id, "total", "10000"
            )
            assert wrong["claims"] == [
                {"claim_id": "field", "result": "incorrect", "reason": "wrong_value"}
            ]

    with selector_runner() as runner:
        runner.run(exercise())


def test_capture_keeps_only_owner_facts_and_preserves_invalidated_rows(postgres_url: URL) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            case = search_case(initial_state={"request": REQUEST})
            first, other = await business.prepare(case), await business.prepare(case)
            for context in (first, other):
                result = await TravelToolExecutor(business.travel).execute(
                    context, "search_places", {"city": "京都", "query": "京都"}
                )
                assert result.code is None
            await HotelService(business.travel).search(first, 1)
            a = await business.content_record(case, first, "private-first-answer")
            b = await business.content_record(case, other, "private-other-answer")
            assert a.evidence and b.evidence
            assert {g.record.evidence_id for g in a.evidence}.isdisjoint(
                g.record.evidence_id for g in b.evidence
            )
            assert all(g.context == first and not g.invalidated for g in a.evidence)
            await business.travel.patch_request(
                first, RequestPatch(expected_revision=1, clear=("city",))
            )
            stale = await business.content_record(case, first, a.text)
            assert stale.request.revision == 2
            assert {g.record.evidence_id for g in a.evidence} == {
                g.record.evidence_id for g in stale.evidence
            }
            assert any(g.invalidated for g in stale.evidence)
            assert all(
                not g.record.applicable(stale.request, stale.observed_at) for g in stale.evidence
            )
            with pytest.raises(ServiceError):
                await business.content_record(case, replace(first, user_id=other.user_id), "bad")

    with selector_runner() as runner:
        runner.run(exercise())


def test_eval_captures_answer_and_dependency_failure_keeps_verification_incomplete(
    postgres_url: URL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            case = search_case(input="京都景点")
            result_dir = tmp_path / "success"
            summary = await run_cases([case], result_dir, business=business)
            assert summary["errors"] == 0
            row = json.loads((result_dir / "results.jsonl").read_text(encoding="utf-8"))
            captured = AnswerRecord.model_validate(row["content_record"])
            attempt = json.loads((result_dir / "attempts.jsonl").read_text(encoding="utf-8"))
            assert captured.context.run_id.hex == attempt["context"]["run_id"].replace("-", "")
            assert captured.text == row["text"] and captured.evidence

            async def unavailable(*args: object) -> AnswerRecord:
                raise ServiceError(503, "unavailable", "私有评审事实暂不可用")

            monkeypatch.setattr(business, "content_record", unavailable)
            failure_dir = tmp_path / "failure"
            failed = await run_cases([case], failure_dir, business=business, repeats=3)
            assert failed["errors"] == 1 and failed["not_run"] == 2
            rows = [
                json.loads(line)
                for line in (failure_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            assert rows[0]["content_record"] is None
            assert rows[0]["checks"]["business_verification_available"] is False
            assert rows[0]["http_attempts"] == 0 and rows[0]["tool_count"] == 2

    with selector_runner() as runner:
        runner.run(exercise())
