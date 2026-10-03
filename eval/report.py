"""同一次版本化评测的重复与测量摘要；失败/未跑/未知成本分别记录，不混币种。"""

import math
from decimal import Decimal, InvalidOperation


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
    return {
        "measured_n": len(measured),
        "unknown_n": len(rows) - len(measured),
        "totals": {key: sum(v[key] for v in measured) for key in keys}
        if measured and len(measured) == len(rows)
        else None,
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
    }
