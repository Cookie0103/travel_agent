"""v3评分：从观测（轮次事件+终态事实）确定性地得出success与失败原因；judge不参与。"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from backend.domain.execution import RuntimeEvent
from eval.claims import ClaimFacts, claim_consistency
from eval.memory_metrics import normalized_surface
from eval.metrics import subset_matches
from eval.v3_cases import (
    TOOL_NAMES,
    CardCheck,
    Check,
    DbCheck,
    ReplyCheck,
    StateCheck,
    TurnToolCheck,
    V3Case,
    ValidatorCheck,
)
from eval.v3_tiers import DEFAULT_TIER, VALIDATOR_TIER, Tier

type Outcome = Literal["pass", "fail", "unknown"]

PRESENTATION_OVERLAY = ("trip_ask", "form")


@dataclass(frozen=True)
class CardObs:
    kind: str  # trip_ask/form/pace/budget_relaxation/memory_confirm/hotel_assign
    groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnObs:
    index: int  # 1起，仅计产生run的轮次
    user: str
    session_id: str
    run_id: str
    status: str
    error_code: str | None
    answer: str
    created_at: datetime
    finished_at: datetime | None
    events: tuple[RuntimeEvent, ...] = ()
    cards: tuple[CardObs, ...] = ()
    fresh_session: bool = False
    prompt_text: str | None = None  # L3来源文本；绝不进报告/trace
    claim_facts: ClaimFacts | None = None  # 该轮结束时的服务端事实；None时退回Observation的终态
    abandoned: bool = False
    user_text: str = ""  # 该轮用户消息（含点击卡片的说明），供评审与人工阅读

    @property
    def latency_s(self) -> float:
        end = self.finished_at or max((e.occurred_at for e in self.events), default=self.created_at)
        return max(0.0, (end - self.created_at).total_seconds())

    @property
    def ttfua_s(self) -> float:
        """run创建到第一个presentation事件；没有则取到结束。"""
        first = next((e.occurred_at for e in self.events if e.kind == "presentation"), None)
        if first is None:
            return self.latency_s
        return max(0.0, (first - self.created_at).total_seconds())


@dataclass(frozen=True)
class DbFacts:
    draft_exists: bool = False
    draft_conflicts: int = 0  # 最后一份草稿validation中status=conflict的check数
    # 最后一份草稿按日期(行程自带的+09:00本地日)去重后的景点数；None=无草稿。
    # draft_trip_dates是请求的start..end全部日期；首尾日(到达/离开)不算整天。
    draft_places_by_day: Mapping[str, int] | None = None
    draft_trip_dates: tuple[str, ...] = ()
    plan_saved: bool = False
    new_orders: int = 0
    hotel_selected_segments: int = 0
    memory_current: tuple[Mapping[str, object], ...] = ()  # 末位用户的记忆事实
    memory_owner: tuple[Mapping[str, object], ...] = ()  # 第一个用户(A)的记忆事实，供L2


@dataclass(frozen=True)
class Observation:
    turns: tuple[TurnObs, ...] = ()
    validation: tuple[Mapping[str, object], ...] | None = None  # 最后一份草稿；None=无草稿
    state: Mapping[str, object] = field(default_factory=dict)
    db: DbFacts = field(default_factory=DbFacts)
    memory_l1: Mapping[str, object] | None = None  # eval.memory_metrics.memory_scores结果
    l3_source: str | None = None
    claim_facts: ClaimFacts = field(default_factory=ClaimFacts)
    step_unavailable: int | None = None
    infra_error: str | None = None


@dataclass(frozen=True)
class CheckResult:
    id: str
    tier: Tier
    outcome: Outcome
    detail: str = ""


@dataclass(frozen=True)
class Score:
    success: bool
    hard_pass: bool
    false_claim: bool
    within_time: bool | None  # None=题目没设时限；仅记录，不参与success
    tool_ok: bool
    memory_ok: bool
    abandoned: bool
    soft_score: float | None
    reason: str | None
    metrics: dict[str, float]
    claim_violations: tuple[str, ...]
    claim_unknown: int
    checks: tuple[CheckResult, ...]
    memory_layers: dict[str, bool]
    tool_summary: dict[str, object]
    l3_source: str | None = None  # prompt_snapshot | service_snapshot | missing | None(未声明L3)
    infra_error: str | None = None


def tool_names(turns: Sequence[TurnObs]) -> list[str]:
    return [
        e.tool_name for t in turns for e in t.events if e.kind == "tool_started" and e.tool_name
    ]


def validation_metrics(turns: Sequence[TurnObs]) -> dict[str, float]:
    started = {
        e.tool_call_id or id(e): e
        for t in turns
        for e in t.events
        if e.kind == "tool_started" and e.tool_name == "validate_itinerary"
    }
    duration = 0.0
    for t in turns:
        for e in t.events:
            if e.kind == "tool_finished" and e.tool_name == "validate_itinerary":
                begin = started.get(e.tool_call_id or -1)
                if begin is not None:
                    duration += max(0.0, (e.occurred_at - begin.occurred_at).total_seconds())
    rounds = len(started)
    return {
        "validation_rounds": float(rounds),
        "repair_rounds": float(max(0, rounds - 1)),
        "validation_time_s": duration,
    }


def latency_metrics(turns: Sequence[TurnObs]) -> dict[str, float]:
    latencies = [t.latency_s for t in turns]
    return {
        "ttfua_s": max((t.ttfua_s for t in turns), default=0.0),
        "turn_latency_max_s": max(latencies, default=0.0),
        "turn_latency_total_s": sum(latencies),
    }


def last_turn(turns: Sequence[TurnObs], which: int | str) -> list[TurnObs]:
    if which == "any":
        return list(turns)
    if which == "last":
        return list(turns[-1:])
    assert isinstance(which, int)
    return [t for t in turns if t.index == which]


def run_check(check: Check, obs: Observation) -> tuple[Outcome, str]:
    if isinstance(check, ValidatorCheck):
        return validator_outcome(check, obs.validation)
    if isinstance(check, StateCheck):
        if not obs.state:
            return "unknown", "无终态快照"
        ok = all(subset_matches(obs.state.get(k), v) for k, v in check.expect.items())
        return ("pass" if ok else "fail"), ""
    if isinstance(check, DbCheck):
        return db_outcome(check, obs.db)
    if isinstance(check, TurnToolCheck):
        picked = last_turn(obs.turns, check.turn)
        if not picked:
            return "unknown", "该轮不存在"
        names = set(tool_names(picked))
        ok = set(check.called) <= names and not (set(check.not_called) & names)
        return ("pass" if ok else "fail"), ""
    if isinstance(check, ReplyCheck):
        picked = last_turn(obs.turns, check.turn)
        if not picked:
            return "unknown", "该轮不存在"
        texts = [t.answer for t in picked]

        def hit(pattern: str) -> bool:
            return any(re.search(pattern, text) for text in texts)

        ok = (check.matches is None or hit(check.matches)) and (
            check.not_matches is None or not hit(check.not_matches)
        )
        return ("pass" if ok else "fail"), ""
    assert isinstance(check, CardCheck)
    picked = last_turn(obs.turns, check.turn)
    if not picked:
        return "unknown", "该轮不存在"
    cards = [c for t in picked for c in t.cards if c.kind == check.kind]
    ok = bool(cards) and (
        check.has_group is None or any(check.has_group in c.groups for c in cards)
    )
    if ok and check.lacks_group is not None:
        ok = all(check.lacks_group not in c.groups for c in cards)
    return ("pass" if ok else "fail"), ""


def validator_outcome(
    check: ValidatorCheck, validation: Sequence[Mapping[str, object]] | None
) -> tuple[Outcome, str]:
    if validation is None:
        return "unknown", "无计划草稿"
    found = [
        c
        for c in validation
        if c.get("code") == check.code
        and (check.subject is None or c.get("subject") == check.subject)
    ]
    if not found:
        return "unknown", "草稿中没有该项"
    statuses = {c.get("status") for c in found}
    if "conflict" in statuses:
        return "fail", "conflict"
    if statuses == {"verified"}:
        return "pass", ""
    # 只剩unknown：min_status=not_conflict也不能当通过（allow_unknown恒为false）。
    return "unknown", "unknown"


def db_outcome(check: DbCheck, db: DbFacts) -> tuple[Outcome, str]:
    match check.assert_:
        case "hotel_selected":
            return _flag(db.hotel_selected_segments >= (check.segments or 1))
        case "draft_exists":
            return _flag(db.draft_exists)
        case "draft_no_conflict":
            return _flag(db.draft_exists and db.draft_conflicts == 0)
        case "draft_min_places":
            return _flag(draft_has_min_places(db, check.min_per_day or 1))
        case "plan_saved":
            return _flag(db.plan_saved)
        case "no_plan_saved":
            return _flag(not db.plan_saved)
        case "no_new_orders":
            return _flag(db.new_orders == 0)
        case "memory_active":
            return _flag(
                any(
                    f.get("key") == check.key
                    and f.get("scope") == check.scope
                    and f.get("status") == "active"
                    and (
                        check.value_contains is None
                        or check.value_contains in str(f.get("value") or "")
                    )
                    for f in db.memory_current
                )
            )
        case "memory_absent":
            # 只看 active 时这条永远通过（没有确认点击就不可能 active）；
            # proposed 也算“已经提出了不该提的记忆”，scope 给了就一并限定。
            return _flag(
                not any(
                    f.get("key") == check.key
                    and f.get("status") in {"proposed", "active"}
                    and (check.scope is None or f.get("scope") == check.scope)
                    for f in db.memory_current
                )
            )
    raise AssertionError(check.assert_)


def draft_has_min_places(db: DbFacts, minimum: int) -> bool:
    """整天=请求日期范围去掉首尾日；每个整天的去重景点数都须>=minimum。

    草稿items全是景点(酒店走hotel_stays、交通走route_evidence_id，都不是item)，
    按place_evidence_id去重。没有整天(行程<=2天)时退化为全草稿去重景点总数>=minimum。
    无草稿/无日期信息一律不通过。
    """
    counts = db.draft_places_by_day
    if counts is None or not db.draft_trip_dates:
        return False
    full_days = db.draft_trip_dates[1:-1]
    if not full_days:
        return sum(counts.values()) >= minimum
    return all(counts.get(day, 0) >= minimum for day in full_days)


def _flag(value: bool) -> tuple[Outcome, str]:
    return ("pass" if value else "fail"), ""


def auto_validator_results(
    validation: Sequence[Mapping[str, object]] | None,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for number, entry in enumerate(validation or ()):
        code = str(entry.get("code"))
        tier = VALIDATOR_TIER.get(code, DEFAULT_TIER)
        status = entry.get("status")
        outcome: Outcome = (
            "pass" if status == "verified" else "fail" if status == "conflict" else "unknown"
        )
        results.append(CheckResult(f"validator_{code}_{number}", tier, outcome, str(status)))
    return results


def memory_layers(case: V3Case, obs: Observation) -> dict[str, bool]:
    """只返回该题声明了的层；未声明的层不出现（Langfuse也不推）。"""
    layers: dict[str, bool] = {}
    spec = case.memory
    if spec.l1:
        layers["l1"] = bool(obs.memory_l1 and obs.memory_l1.get("exact") is True)
    if spec.l2:
        owner = obs.db.memory_owner
        layers["l2"] = all(
            any(
                f.get("key") == e.key
                and f.get("scope") == e.scope
                and f.get("status") == e.status
                and (e.value_contains is None or e.value_contains in str(f.get("value") or ""))
                for f in owner
            )
            for e in spec.l2
        )
    if spec.l3.present or spec.l3.absent:
        fresh = [t for t in obs.turns if t.fresh_session and t.prompt_text is not None]
        if not fresh:
            layers["l3"] = False
        else:
            text = normalized_surface(fresh[-1].prompt_text or "")
            layers["l3"] = all(normalized_surface(w) in text for w in spec.l3.present) and not any(
                normalized_surface(w) in text for w in spec.l3.absent
            )
    if spec.l4:
        layers["l4"] = all(run_check(c, obs)[0] == "pass" for c in spec.l4)
    return layers


def claim_summary(obs: Observation) -> tuple[tuple[str, ...], int, dict[str, bool]]:
    """返回(违规类别, unknown数, 各类别是否出现过断言)。unknown不判失败。"""
    violations: list[str] = []
    unknown = 0
    claimed: dict[str, bool] = {}
    for turn in obs.turns:
        verdict = claim_consistency(
            turn.answer, turn.events, facts=turn.claim_facts or obs.claim_facts
        )
        for kind, value in verdict.items():
            if kind == "passed":
                continue
            if kind.endswith("_claimed"):
                claimed[kind.removesuffix("_claimed")] = claimed.get(
                    kind.removesuffix("_claimed"), False
                ) or bool(value)
            elif value is False and kind not in violations:
                violations.append(kind)
            elif value is None:
                unknown += 1
    return tuple(violations), unknown, claimed


def tool_summary(case: V3Case, obs: Observation) -> dict[str, object]:
    started = tool_names(obs.turns)
    names = set(started)
    unregistered = {n for n in names if n not in TOOL_NAMES} | {
        e.tool_name or "?"
        for t in obs.turns
        for e in t.events
        if e.kind == "tool_finished" and e.reason == "unregistered_tool"
    }
    return {
        "started": sorted(names),
        "missing_required": [n for n in case.required_tools if n not in names],
        "forbidden_used": [n for n in case.forbidden_tools if n in names],
        "hallucinated": sorted(unregistered),
        "blocked": any(t.error_code == "blocked" for t in obs.turns),
        "calls": len(started),
    }


def score_trial(case: V3Case, obs: Observation) -> Score:
    explicit: list[CheckResult] = []
    for check in case.hard_checks:
        outcome, detail = run_check(check, obs)
        explicit.append(CheckResult(check.id, "hard", outcome, detail))
    for check in case.soft_checks:
        outcome, detail = run_check(check, obs)
        explicit.append(CheckResult(check.id, "soft", outcome, detail))
    auto = auto_validator_results(obs.validation)
    checks = tuple(explicit + auto)
    # 硬：显式硬检查必须pass（unknown不算通过）；自动HARD validator只有conflict才失败。
    hard_failures = [c for c in explicit if c.tier == "hard" and c.outcome != "pass"] + [
        c for c in auto if c.tier == "hard" and c.outcome == "fail"
    ]
    hard_pass = not hard_failures
    weights = {c.id: c.weight for c in (*case.hard_checks, *case.soft_checks)}
    soft_items = [(c, weights.get(c.id, 1)) for c in checks if c.tier == "soft"]
    soft_score = (
        sum(w for c, w in soft_items if c.outcome == "pass") / sum(w for _, w in soft_items)
        if soft_items
        else None
    )
    violations, claim_unknown, claimed = claim_summary(obs)
    empty_reply = any(not t.answer.strip() for t in obs.turns)
    tools = tool_summary(case, obs)
    tool_ok = not (
        tools["missing_required"]
        or tools["forbidden_used"]
        or tools["hallucinated"]
        or tools["blocked"]
    )
    layers = memory_layers(case, obs)
    declares_l3 = bool(case.memory.l3.present or case.memory.l3.absent)
    l3_source = obs.l3_source if declares_l3 else None
    infra_error = obs.infra_error
    if (
        declares_l3
        and obs.l3_source == "prompt_snapshot"
        and any(t.fresh_session and t.prompt_text is None for t in obs.turns)
    ):
        # live下快照文件缺失是设施问题（门没开/评测库不符），不能算成记忆失败。
        l3_source, infra_error = "missing", infra_error or "prompt_snapshot_missing"
    memory_ok = all(layers.values())
    # 延迟默认只记录：只有题目显式设置patience_s才会有放弃；within_time仅在设了上限时有意义。
    patience = float(case.patience_s) if case.patience_s is not None else None
    abandoned = any(
        t.abandoned or (patience is not None and t.latency_s > patience) for t in obs.turns
    )
    limits = [float(v) for v in (case.ttfua_s, case.patience_s) if v is not None]
    within_time: bool | None = all(t.ttfua_s <= min(limits) for t in obs.turns) if limits else None
    false_claim = bool(violations)
    step_ok = obs.step_unavailable is None
    success = (
        hard_pass
        and not false_claim
        and tool_ok
        and memory_ok
        and not abandoned
        and not empty_reply
        and step_ok
        and infra_error is None
    )
    reason: str | None = None
    if not success:
        reason = failure_reason(
            case, infra_error, obs, abandoned, tools, violations, hard_failures, layers
        )
    metrics = {**latency_metrics(obs.turns), **validation_metrics(obs.turns)}
    metrics["tool_calls"] = float(tools["calls"])  # type: ignore[arg-type]
    for name, flag in claimed.items():
        if flag:
            metrics["claim_" + name] = float(name in violations)
    return Score(
        success,
        hard_pass,
        false_claim,
        within_time,
        tool_ok,
        memory_ok,
        abandoned,
        soft_score,
        reason,
        metrics,
        violations,
        claim_unknown,
        checks,
        layers,
        tools,
        l3_source,
        infra_error,
    )


def failure_reason(
    case: V3Case,
    infra_error: str | None,
    obs: Observation,
    abandoned: bool,
    tools: Mapping[str, object],
    violations: Sequence[str],
    hard_failures: Sequence[CheckResult],
    layers: Mapping[str, bool],
) -> str:
    """每个失败trial只取一个原因，按固定优先级。"""
    if infra_error is not None:
        return "infra_error"
    if abandoned:
        return "abandoned"
    if tools["blocked"] or tools["hallucinated"]:
        return "blocked_or_hallucinated_tool"
    if violations:
        return f"false_claim:{violations[0]}"
    if any(not t.answer.strip() for t in obs.turns):
        return "empty_reply"
    if hard_failures:
        return f"hard:{hard_failures[0].id}"
    if obs.step_unavailable is not None:
        return f"step_unavailable:{obs.step_unavailable}"
    missing = [*tools["missing_required"], *tools["forbidden_used"]]  # type: ignore[misc]
    if missing:
        return f"tool:{missing[0]}"
    failed = next((name for name, ok in layers.items() if not ok), None)
    if failed:
        return f"memory:L{failed[1:]}"
    return "unknown"
