"""同一次版本化评测的重复与测量摘要；失败/未跑/未知成本分别记录，不混币种。"""

import math
from decimal import Decimal, InvalidOperation

from backend.providers.claude_agent.response import cache_hit_rate
from eval.business_metrics import business_summary


def rate(rows: list[dict[str, object]]) -> dict[str, object]:
    evaluated = sum(row["status"] in {"passed", "failed"} for row in rows)
    passed = sum(row["status"] == "passed" for row in rows)
    return {
        "expected": len(rows),
        "evaluated": evaluated,
        "passed": passed,
        "errors": sum(row["status"] == "error" for row in rows),
        "not_run": sum(row["status"] == "not_run" for row in rows),
        "rule_pass_rate": passed / evaluated if evaluated else None,
    }


def distribution(values: list[float]) -> dict[str, object]:
    ordered = sorted(values)
    return {
        "measured_n": len(values),
        "p50": ordered[math.ceil(len(ordered) * 0.50) - 1] if ordered else None,
        "p95": ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None,
        "method": "nearest-rank",
    }


def measured_summary(rows: list[dict[str, object]], repeats: int) -> dict[str, object]:
    per_repeat = [
        {"repeat": index, **rate([r for r in rows if r["repeat"] == index])}
        for index in range(1, repeats + 1)
    ]
    rates = [
        float(r["rule_pass_rate"])
        for r in per_repeat
        if isinstance(r["rule_pass_rate"], (int, float))
    ]
    attempted = [r for r in rows if r["status"] != "not_run"]
    latency = latency_values(attempted, "elapsed_seconds")
    progress = latency_values(attempted, "first_progress_seconds")
    groups: dict[str, list[dict[str, object]]] = {}
    for row in attempted:
        currency = row.get("accounting_currency")
        if isinstance(currency, str) and currency in {"CNY", "USD"}:
            groups.setdefault(currency, []).append(row)
    identities = {
        str(row.get("identity")): row["identity"]
        for row in attempted
        if isinstance(row.get("identity"), dict)
    }
    requests = [
        r["http_attempts"]
        for r in attempted
        if type(r.get("http_attempts")) is int
        and isinstance(r["http_attempts"], int)
        and r["http_attempts"] >= 0
    ]
    return {
        "per_repeat": per_repeat,
        "reliability": reliability(rows, repeats),
        "rule_rate_range": {
            "min": min(rates) if rates else None,
            "max": max(rates) if rates else None,
        },
        "latency_seconds": distribution(latency),
        "latency_unknown_n": len(attempted) - len(latency),
        "first_progress_seconds": distribution(progress),
        "first_progress_unknown_n": len(attempted) - len(progress),
        "tool_call_accuracy": tool_summary(attempted),
        "original_currency_cost": {
            currency: cost_summary(group) for currency, group in groups.items()
        },
        "currency_unknown_n": len(attempted) - sum(map(len, groups.values())),
        "runtime_identities": list(identities.values()),
        "http_attempts": {
            "total": sum(requests) if len(requests) == len(attempted) else None,
            "measured_subtotal": sum(requests),
            "unknown_n": len(attempted) - len(requests),
        },
        "tokens": token_summary(attempted),
        "semantic_fact_quality": None,
        "semantic_quality_reason": "规则/结构断言不能替代语义与人工校准",
        "business_metrics": business_summary(rows),
        "v2_metrics": v2_summary(rows),
    }


def latency_values(rows: list[dict[str, object]], key: str) -> list[float]:
    return [
        float(value)
        for row in rows
        if isinstance(value := row.get(key), (int, float))
        and type(value) is not bool
        and math.isfinite(value)
        and value >= 0
    ]


def tool_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    measured: list[dict[str, object]] = []
    for row in rows:
        value = row.get("tool_call_accuracy")
        if (
            isinstance(value, dict)
            and all(
                type(value.get(k)) is int and value[k] >= 0
                for k in ("total", "correct", "incorrect", "unknown")
            )
            and value["total"] == value["correct"] + value["incorrect"] + value["unknown"]
        ):
            measured.append(value)
    counts = {
        k: sum(int(str(v[k])) for v in measured)
        for k in ("total", "correct", "incorrect", "unknown")
    }
    complete = len(measured) == len(rows) and all(
        v.get("events_consistent") is True for v in measured
    )
    return {
        **{k: v if len(measured) == len(rows) else None for k, v in counts.items()},
        "measured_subtotal": counts,
        "unknown_cases": len(rows) - len(measured),
        "accuracy": counts["correct"] / counts["total"]
        if complete and counts["total"] and not counts["unknown"]
        else None,
        "scope": "all started calls; unknown semantic parameters remain unscored",
    }


def token_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    keys = (
        "input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
    )
    measured: list[dict[str, int]] = []
    for row in rows:
        value = row.get("tokens")
        if isinstance(value, dict) and all(
            type(value.get(key)) is int and value[key] >= 0 for key in keys
        ):
            measured.append({key: value[key] for key in keys})
    totals = (
        {key: sum(v[key] for v in measured) for key in keys}
        if measured and len(measured) == len(rows)
        else None
    )
    return {
        "measured_n": len(measured),
        "unknown_n": len(rows) - len(measured),
        "totals": totals,
        "cache_hit_rate": cache_hit_rate(totals) if totals else None,
    }


def cost_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    values: list[Decimal] = []
    for row in rows:
        raw = row.get("run_accounted")
        try:
            value = Decimal(raw) if isinstance(raw, str) else None
        except InvalidOperation:
            value = None
        if value is not None and value.is_finite() and value >= 0:
            values.append(value)
    return {
        "n": len(rows),
        "measured_n": len(values),
        "unknown_n": len(rows) - len(values),
        "total": str(sum(values, Decimal(0))) if len(values) == len(rows) else None,
        "measured_subtotal": str(sum(values, Decimal(0))) if values else None,
        "distribution": distribution([float(v) for v in values]),
        "cost_per_success": str(
            sum(values, Decimal(0)) / sum(r.get("status") == "passed" for r in rows)
        )
        if len(values) == len(rows) and any(r.get("status") == "passed" for r in rows)
        else None,
    }


def reliability(rows: list[dict[str, object]], k: int) -> dict[str, object]:
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        if isinstance(name := row.get("case_id"), str):
            groups.setdefault(name, []).append(row)
    complete = [
        group
        for group in groups.values()
        if len(group) == k
        and {r.get("repeat") for r in group} == set(range(1, k + 1))
        and all(r.get("status") in {"passed", "failed"} for r in group)
    ]
    observed = len(complete) == len(groups) and bool(groups)
    return {
        "k": k,
        "cases": len(groups),
        "complete_cases": len(complete),
        "pass_at_1": sum(r["status"] == "passed" for g in complete for r in g) / (len(complete) * k)
        if observed
        else None,
        "pass_at_k": sum(any(r["status"] == "passed" for r in g) for g in complete) / len(complete)
        if observed
        else None,
        "pass_power_k": sum(all(r["status"] == "passed" for r in g) for g in complete)
        / len(complete)
        if observed
        else None,
        "basis": "predeclared independent trials; errors/missing trials remain unknown",
    }


def simulation_summary(rows: list[dict[str, object]], repeats: int) -> dict[str, object]:
    """只汇总实际末态：交付分母是要求保存的场景，未知约束不算满足。"""
    requested = [r for r in rows if r.get("case_id") == "v2-user-three-segments"]
    measurements = [
        value for r in requested if isinstance(value := r.get("saved_constraints"), dict)
    ]
    delivered = [r for r in measurements if r.get("delivered") is True]
    checks = [value for r in delivered if isinstance(value := r.get("checks"), list) and value]
    valid = [
        group
        for group in checks
        if all(
            isinstance(c, dict) and c.get("status") in {"verified", "unknown", "conflict"}
            for c in group
        )
    ]
    flat = [c for group in valid for c in group]
    complete = bool(delivered) and len(valid) == len(delivered)
    process = {}
    for key in (
        "tool_calls",
        "duplicate_calls",
        "recovered_without_user",
        "user_visible_errors",
        "user_visible_first_errors",
    ):
        values = [p.get(key) for row in rows if isinstance(p := row.get("process"), dict)]
        counts = [v for v in values if isinstance(v, int) and not isinstance(v, bool) and v >= 0]
        process[key] = (
            sum(counts) if len(values) == len(rows) and len(counts) == len(values) else None
        )
    costs = cost_summary([{**r, "run_accounted": r.get("cost_cny")} for r in rows])
    durations = latency_values(rows, "elapsed_seconds")
    return {
        "n": len(rows),
        "passed": sum(r.get("status") == "passed" for r in rows),
        **rate(rows),
        "cost_cny": costs["total"],
        "original_currency_cost": {"currency": "CNY", **costs},
        "reliability": reliability(
            [{**r, "repeat": r.get("repeat", r.get("trial"))} for r in rows], repeats
        ),
        "saved_constraints": {
            "requested": len(requested),
            "delivered": len(delivered),
            "delivery_rate": len(delivered) / len(requested)
            if requested
            and len(measurements) == len(requested)
            and all(type(m.get("delivered")) is bool for m in measurements)
            else None,
            "verified_checks": sum(c["status"] == "verified" for c in flat),
            "unknown_checks": sum(c["status"] == "unknown" for c in flat),
            "conflict_checks": sum(c["status"] == "conflict" for c in flat),
            "micro": sum(c["status"] == "verified" for c in flat) / len(flat) if complete else None,
            "macro": sum(
                sum(c["status"] == "verified" for c in group) / len(group) for group in valid
            )
            / len(valid)
            if complete
            else None,
            "all_constraints_rate": sum(
                all(c["status"] == "verified" for c in group) for group in valid
            )
            / len(valid)
            if complete
            else None,
            "scope": "independent validation of saved content only; "
            "partial has unknowns; delivery is separate",
        },
        "process": process,
        "elapsed_seconds": distribution(durations),
        "elapsed_unknown_n": len(rows) - len(durations),
        "basis": "synthetic goals; actual SDK+PG; no real suppliers; uncalibrated semantics",
    }


def memory_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    measured = [m for row in rows if isinstance((m := row.get("memory_metrics")), dict)]
    categories: dict[str, object] = {}
    for category in (
        "extraction",
        "trip",
        "negation",
        "third_party",
        "update",
        "abstain",
        "poison",
    ):
        values = [m for m in measured if m.get("category") == category]
        counts = {
            key: sum(int(str(m[key])) for m in values)
            for key in ("true_positive", "false_positive", "false_negative")
        }
        tp, fp, fn = counts["true_positive"], counts["false_positive"], counts["false_negative"]
        categories[category] = {
            "n": len(values),
            **counts,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "exact_rate": sum(m.get("exact") is True for m in values) / len(values)
            if values
            else None,
            "invalid_attempts": sum(int(str(m["invalid_attempts"])) for m in values),
        }
    tp = sum(int(str(m["true_positive"])) for m in measured)
    fp = sum(int(str(m["false_positive"])) for m in measured)
    fn = sum(int(str(m["false_negative"])) for m in measured)
    return {
        "status": "measured_uncalibrated" if measured else "pending_real_suite",
        "categories": categories,
        "n": len(measured),
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "cross_user_leaks": sum(m.get("cross_user_leakage") is True for m in measured)
        if measured
        else None,
        "deleted_residuals": sum(m.get("deletion_residue") is True for m in measured)
        if measured
        else None,
        "basis": "synthetic cases/aliases; model extraction/server probes; uncalibrated",
    }


def v2_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    states = [
        check["expected_state"]
        for row in rows
        if isinstance(check := row.get("checks"), dict)
        and type(check.get("expected_state")) is bool
    ]
    process = [value for row in rows if isinstance(value := row.get("process_metrics"), dict)]
    saved = [value for row in rows if isinstance(value := row.get("saved_constraints"), dict)]
    measured = [
        value for value in saved if isinstance(value.get("checks"), list) and value["checks"]
    ]
    checks = [check for value in measured for check in value["checks"] if isinstance(check, dict)]
    return {
        "terminal_state_n": len(states),
        "terminal_state_pass_rate": sum(states) / len(states) if states else None,
        "process": {
            name: sum(int(str(value[name])) for value in process)
            if process and len(process) == len(rows)
            else None
            for name in (
                "tool_calls",
                "recovered_without_user",
                "user_visible_errors",
                "user_visible_first_errors",
            )
        },
        "saved_plan_delivery_rate": sum(value.get("delivered") is True for value in saved)
        / len(saved)
        if saved
        else None,
        "constraint_micro": sum(c.get("passed") is True for c in checks) / len(checks)
        if checks
        else None,
        "constraint_macro": sum(value.get("all_constraints") is True for value in measured)
        / len(measured)
        if measured
        else None,
        "constraint_measured_n": len(measured),
        "memory": memory_summary(rows),
        "triage": {
            "status": "pending_model_reference",
            "accuracy": None,
            "regression_candidates": [
                {
                    "case_id": row.get("case_id"),
                    "trial": row.get("repeat"),
                    "failed_checks": row.get("failed_checks"),
                }
                for row in rows
                if row.get("status") == "failed"
            ],
        },
    }
