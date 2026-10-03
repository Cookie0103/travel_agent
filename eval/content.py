"""私有回答/Evidence与独立标注的内容评审；不提取模型自述为真值，不生成真人分。"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    model_validator,
)

from backend.domain.catalog import Article, Place
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext
from backend.domain.hotels import HotelOffer
from backend.domain.itinerary import RouteEstimate
from backend.domain.travel_request import TravelRequest
from eval.suites import load_suite

ROOT = Path(__file__).resolve().parents[1]


class PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Grounding(PrivateModel):
    context: RunContext
    record: EvidenceRecord
    invalidated: bool = Field(strict=True)


class AnswerRecord(PrivateModel):
    case_id: str = Field(pattern=r"^[a-z0-9-]+$")
    context: RunContext
    request: TravelRequest
    observed_at: AwareDatetime
    text: str
    evidence: tuple[Grounding, ...]

    @property
    def answer_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class Fact(PrivateModel):
    entity_id: str = Field(min_length=1, max_length=100)
    field_path: str = Field(min_length=1, max_length=100)
    value: JsonValue
    certainty: Literal["asserted", "unknown", "estimate"] = "asserted"


class Claim(Fact):
    claim_id: str = Field(pattern=r"^[a-z0-9-]+$")
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)
    excerpt: str = Field(min_length=1)
    evidence_id: UUID | None = None


class HumanQuality(PrivateModel):
    relevance: int = Field(strict=True, ge=0, le=5)
    explanation: int = Field(strict=True, ge=0, le=5)
    tradeoffs: int = Field(strict=True, ge=0, le=5)
    reason: str = Field(min_length=1, max_length=1000)
    rater: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def nonblank(self) -> Self:
        if not self.reason.strip() or not self.rater.strip():
            raise ValueError("人工理由/评审人不能为空白")
        return self


class ContentReview(PrivateModel):
    case_id: str
    context: RunContext
    answer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1, max_length=100)
    claims: tuple[Claim, ...]
    required_facts: tuple[Fact, ...]
    claims_complete: bool = Field(default=False, strict=True)
    requirements_complete: bool = Field(default=False, strict=True)
    human_quality: HumanQuality | None = None


def canonical(value: JsonValue) -> str:
    # JSON保留bool/int区别；Python的True == 1不能用作事实相等。
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def project_fact(record: EvidenceRecord, path: str) -> tuple[JsonValue, str]:
    """只投影已有领域契约的字段；对象来源已知不等于其中每个字段已知。"""
    if not isinstance(record.value, dict):
        return (record.value, record.status) if path == record.field_path else (None, "missing")
    model: Place | Article | HotelOffer | RouteEstimate
    if record.field_path == "catalog" and record.kind in {"place", "article"}:
        model = (
            Place.model_validate(record.value)
            if record.kind == "place"
            else Article.model_validate(record.value)
        )
    elif record.field_path == "hotel_offer" and record.kind == "hotel_offer":
        model = HotelOffer.model_validate(record.value)
    elif record.field_path == "route" and record.kind == "route":
        model = RouteEstimate.model_validate(record.value)
    else:
        return None, "missing"
    payload = model.card() if isinstance(model, HotelOffer) else model.model_dump(mode="json")
    relative = path
    value: object = payload
    for part in relative.split("."):
        if not isinstance(value, dict) or part not in value:
            return None, "missing"
        value = value[part]
    state = "unknown" if value is None or record.status == "unknown" else "verified"
    if (
        state != "unknown"
        and value is not None
        and (
            isinstance(model, RouteEstimate)
            and relative in {"minutes", "fare"}
            or isinstance(model, Place)
            and model.coordinate_kind == "bounding_box_center"
            and relative in {"latitude", "longitude"}
        )
    ):
        state = "estimate"
    return TypeAdapter(JsonValue).validate_python(value), state


def claim_result(claim: Claim, answer: AnswerRecord) -> tuple[str, str]:
    matches = [g for g in answer.evidence if g.record.evidence_id == claim.evidence_id]
    if claim.evidence_id is None:
        return "incorrect", "no_evidence"
    if len(matches) != 1 or matches[0].context != answer.context:
        return "unknown", "missing_or_ambiguous_evidence"
    grounding = matches[0]
    record = grounding.record
    if grounding.invalidated or not record.applicable(answer.request, answer.observed_at):
        return "incorrect", "stale_evidence"
    if record.entity_id != claim.entity_id:
        return "incorrect", "wrong_fact"
    try:
        value, state = project_fact(record, claim.field_path)
    except ValueError:
        return "unknown", "invalid_evidence_payload"
    if state == "missing":
        return "unknown", "unavailable_field"
    if canonical(value) != canonical(claim.value):
        return "incorrect", "wrong_value"
    if claim.certainty == "unknown":
        return (
            ("correct", "explicit_unknown")
            if state == "unknown"
            else ("incorrect", "wrong_qualification")
        )
    if state == "unknown":
        return "incorrect", "unsupported_assertion"
    if state == "estimate" and claim.certainty != "estimate":
        return "incorrect", "unlabelled_estimate"
    return "correct", "matching_applicable_evidence"


def assess_content(answer: AnswerRecord, review: ContentReview) -> dict[str, object]:
    if (
        review.case_id != answer.case_id
        or review.context != answer.context
        or review.answer_sha256 != answer.answer_sha256
        or not review.reviewer.strip()
    ):
        raise ValueError("标注与原回答不匹配")
    ids = [c.claim_id for c in review.claims]
    spans = [(c.start, c.end, c.entity_id, c.field_path) for c in review.claims]
    required = [(f.entity_id, f.field_path) for f in review.required_facts]
    if (
        len(set(ids)) != len(ids)
        or len(set(spans)) != len(spans)
        or len(set(required)) != len(required)
    ):
        raise ValueError("重复事实标注不能扩大分母")
    for fact in (*review.claims, *review.required_facts):
        canonical(fact.value)
    rows: list[dict[str, object]] = []
    correct_claims: list[Claim] = []
    counts = {"correct": 0, "incorrect": 0, "unknown": 0}
    for claim in review.claims:
        if answer.text[claim.start : claim.end] != claim.excerpt or claim.end > len(answer.text):
            raise ValueError("事实标注必须引用原回答位置")
        result, reason = claim_result(claim, answer)
        rows.append({"claim_id": claim.claim_id, "result": result, "reason": reason})
        if result == "correct":
            correct_claims.append(claim)
        if claim.certainty != "unknown":
            counts[result] += 1
    covered = sum(
        any(
            c.entity_id == f.entity_id
            and c.field_path == f.field_path
            and canonical(c.value) == canonical(f.value)
            and c.certainty == f.certainty
            for c in correct_claims
        )
        for f in review.required_facts
    )
    total = sum(counts.values())
    unresolved = any(row["result"] == "unknown" for row in rows)
    quality = review.human_quality
    return {
        "case_id": answer.case_id,
        "answer_sha256": answer.answer_sha256,
        "fact_accuracy": {
            **counts,
            "denominator": total,
            "accuracy": counts["correct"] / total
            if total and review.claims_complete and not unresolved
            else None,
        },
        "fact_coverage": {
            "covered": covered,
            "required": len(required),
            "coverage": covered / len(required)
            if required
            and review.requirements_complete
            and review.claims_complete
            and not unresolved
            else None,
        },
        "claims": rows,
        "content_quality": {
            "source": "human",
            "relevance": quality.relevance,
            "explanation": quality.explanation,
            "tradeoffs": quality.tradeoffs,
        }
        if quality
        else None,
        "limitations": "仅独立标注覆盖的陈述；原文含义/估算标记须由评审独立核对；"
        "Evidence一致性不等于独立现实核验；"
        "必需事实依据原需求预先填写，完整性由评审负责；未评分不填零",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--answer", type=Path, help="独立快照JSON；不冒充原评测运行")
    source.add_argument("--results", type=Path, help="原私有results.jsonl；绑定manifest/attempts")
    parser.add_argument("--case-id", help="results中原case_id")
    parser.add_argument("--repeat", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--review", type=Path, required=True, help="独立ContentReview JSON")
    parser.add_argument("--suite", choices=["legacy", "frozen"], default="legacy")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    args = parser.parse_args()
    try:
        answer = (
            AnswerRecord.model_validate_json(args.answer.read_bytes())
            if args.answer
            else answer_from_results(args.results, args.case_id, args.repeat)
        )
        review = ContentReview.model_validate_json(args.review.read_bytes())
        cases, metadata = load_suite(ROOT, args.suite, args.split)
        if answer.case_id not in {c.case_id for c in cases}:
            raise ValueError("案例必须来自原版本化用例集")
        if args.results:
            manifest = json.loads(
                (args.results.parent / "manifest.json").read_text(encoding="utf-8")
            )
            expected = next(c.model_dump(mode="json") for c in cases if c.case_id == answer.case_id)
            selected = manifest.get("selected_cases") if isinstance(manifest, dict) else None
            if (
                not isinstance(manifest, dict)
                or manifest.get("evaluation_suite") != metadata
                or not isinstance(selected, list)
                or expected not in selected
            ):
                raise ValueError("原案例/用例版本不匹配")
        result = {**assess_content(answer, review), "evaluation_suite": metadata}
        path = args.results or args.answer
        result["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result["record_source"] = "evaluation_result" if args.results else "standalone_snapshot"
    except (ValueError, OSError):
        print("内容评审未完成：案例/回答/标注无效；不输出原文。")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def answer_from_results(path: Path, case_id: str | None, repeat: int) -> AnswerRecord:
    if not case_id:
        raise ValueError("原results需要指定case_id")
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("case_id") == case_id
        and type(row.get("repeat")) is int
        and row.get("repeat") == repeat
    ]
    if len(matches) != 1:
        raise ValueError("原结果缺失或重复")
    row = matches[0]
    answer = AnswerRecord.model_validate(row.get("content_record"))
    attempts = [
        json.loads(line)
        for line in (path.parent / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    bindings = [
        a
        for a in attempts
        if isinstance(a, dict)
        and a.get("case_id") == case_id
        and type(a.get("repeat")) is int
        and a.get("repeat") == repeat
    ]
    if (
        answer.case_id != case_id
        or answer.text != row.get("text")
        or len(bindings) != 1
        or TypeAdapter(RunContext).validate_python(bindings[0].get("context")) != answer.context
    ):
        raise ValueError("回答与原持久开始/结果不匹配")
    return answer


if __name__ == "__main__":
    raise SystemExit(main())
