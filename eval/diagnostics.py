"""将私有调用事实与实际事件绑定后归因；错误码、completed及模型自述都不是根因证据。"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from backend.domain.booking import HoldHotelInput
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.travel_request import TravelConditions
from backend.tools.travel import SCHEMAS

type Cause = Literal[
    "request_understanding",
    "tool_selection_or_args",
    "supplier_failure",
    "stale_evidence",
    "state_commit",
    "unknown",
]


@dataclass(frozen=True)
class ConditionFact:
    context: RunContext
    tool_call_id: UUID
    expected: TravelConditions
    applied: TravelConditions
    applied_revision: int


@dataclass(frozen=True)
class ArgumentFact:
    context: RunContext
    tool_call_id: UUID
    arguments: dict[str, object]


@dataclass(frozen=True)
class SupplierAttempt:
    started_at: datetime
    finished_at: datetime
    status: int | None
    timed_out: bool = False


@dataclass(frozen=True)
class SupplierFact:
    context: RunContext
    tool_call_id: UUID
    attempts: tuple[SupplierAttempt, ...]


@dataclass(frozen=True)
class EvidenceFact:
    context: RunContext
    tool_call_id: UUID
    record: EvidenceRecord
    used_at: datetime
    request_revision: int
    arguments: dict[str, object]


@dataclass(frozen=True)
class CommitFact:
    context: RunContext
    tool_call_id: UUID
    expected_revision: int
    observed_revision: int
    rolled_back: bool


type Fact = ConditionFact | ArgumentFact | SupplierFact | EvidenceFact | CommitFact


@dataclass(frozen=True)
class Diagnosis:
    """仅固定标签/依据键/事件位置；不带附件、参数、输入或私有路径。"""

    cause: Cause | None
    event_index: int | None
    basis: tuple[str, ...]
    trace_id: str | None


def diagnose(
    events: tuple[RuntimeEvent, ...],
    facts: tuple[Fact, ...],
    *,
    business_passed: bool,
    trace_id: str | None = None,
) -> Diagnosis:
    trace = trace_id if trace_id and re.fullmatch(r"[0-9a-f]{32}", trace_id) else None
    unknown = Diagnosis("unknown", None, ("insufficient_evidence",), trace)
    if not events or any(e.context != events[0].context for e in events):
        return unknown
    if any(e.occurred_at.tzinfo is None for e in events) or any(
        a.occurred_at > b.occurred_at for a, b in zip(events, events[1:], strict=False)
    ):
        return unknown
    if business_passed:
        return Diagnosis(None, None, ("business_checks_passed",), trace)
    findings: list[Diagnosis] = []
    for fact in facts:
        bound = _bind(events, fact)
        if bound is None:
            return unknown
        index, start, end = bound
        try:
            finding = _finding(fact, start, end)
        except (ValueError, TypeError, ArithmeticError):
            return unknown
        if finding is None:
            return unknown
        findings.append(Diagnosis(finding[0], index, finding[1], trace))
    if not findings or len({f.cause for f in findings}) != 1:
        return unknown
    return min(findings, key=lambda f: f.event_index if f.event_index is not None else len(events))


def _bind(
    events: tuple[RuntimeEvent, ...], fact: Fact
) -> tuple[int, RuntimeEvent, RuntimeEvent] | None:
    if fact.context != events[0].context:
        return None
    matches = [(i, e) for i, e in enumerate(events) if e.tool_call_id == fact.tool_call_id]
    if len(matches) != 2:
        return None
    (index, start), (_, end) = matches
    if (
        start.kind != "tool_started"
        or end.kind != "tool_finished"
        or start.tool_name != end.tool_name
    ):
        return None
    return index, start, end


def _finding(
    fact: Fact, start: RuntimeEvent, end: RuntimeEvent
) -> tuple[Cause, tuple[str, ...]] | None:
    if isinstance(fact, ConditionFact):
        if (
            end.tool_name == "update_travel_request"
            and end.code is None
            and end.request_revision == fact.applied_revision
            and any(
                getattr(fact.expected, k) != getattr(fact.applied, k)
                for k in fact.expected.model_fields_set
            )
        ):
            return "request_understanding", (
                "explicit_conditions",
                "applied_conditions",
                "revision",
            )
    elif isinstance(fact, ArgumentFact):
        schema = SCHEMAS.get(str(end.tool_name))
        if schema is not None and end.code == "validation":
            try:
                schema.model_validate(fact.arguments)
            except ValidationError:
                return "tool_selection_or_args", ("submitted_arguments", "schema_validation")
    elif isinstance(fact, SupplierFact):
        if end.tool_name == "hold_hotel" and end.code in {
            "unavailable",
            "timeout",
            "provider_error",
            "rate_limited",
        }:
            attempts = fact.attempts
            if attempts and all(
                a.started_at.tzinfo is not None
                and a.finished_at.tzinfo is not None
                and start.occurred_at <= a.started_at <= a.finished_at <= end.occurred_at
                and (
                    (a.status is not None and 400 <= a.status <= 599)
                    or (a.status is None and a.timed_out)
                )
                for a in attempts
            ):
                return "supplier_failure", ("supplier_attempts", "final_tool_failure")
    elif isinstance(fact, EvidenceFact):
        # 当前仅归因已捕获提交参数的报价暂留；无消费引用的附件不能证明因果。
        if end.tool_name != "hold_hotel":
            return None
        submitted = HoldHotelInput.model_validate(fact.arguments)
        if (
            end.code in {"blocked", "conflict"}
            and fact.record.kind == "hotel_offer"
            and str(submitted.offer_id) == fact.record.entity_id
            and submitted.expected_revision == fact.request_revision
            and fact.used_at.tzinfo is not None
            and start.occurred_at <= fact.used_at <= end.occurred_at
            and (
                fact.record.valid_until <= fact.used_at
                or fact.record.request_revision != fact.request_revision
            )
        ):
            return "stale_evidence", ("evidence_validity", "use_time", "request_revision")
    elif (
        end.tool_name in {"update_travel_request", "stage_plan_change"}
        and end.code in {"conflict", "provider_error", "unavailable"}
        and fact.rolled_back
        and fact.expected_revision != fact.observed_revision
    ):
        return "state_commit", ("expected_revision", "observed_revision", "transaction_rollback")
    return None
