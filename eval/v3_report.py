"""v3汇总：pass^k、Success@T、失败原因表、成本与耗时分位、scatter.csv、report.md。"""

import csv
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from backend.providers.claude_agent.response import cache_totals
from eval.report import distribution, reliability
from eval.v3_judge import judge_report

THRESHOLDS = (60, 120, 180)
SCATTER_COLUMNS = (
    "case_id",
    "category",
    "trial",
    "success",
    "total_s",
    "max_turn_s",
    "ttfua_s",
    "soft_score",
    "judge_yes_rate",
    "cost_cny",
    "reason",
)


def number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and type(value) is not bool else None


def cost_of(row: dict[str, object]) -> Decimal | None:
    try:
        return Decimal(str(row["cost_cny"]))
    except (KeyError, InvalidOperation):
        return None


def pass_power(rows: list[dict[str, object]], k: int, repeat: int) -> dict[str, object]:
    """只用前k次重复；重复数不足k时为None（不是0）。"""
    if repeat < k:
        return {"k": k, "pass_power_k": None, "cases": 0, "complete_cases": 0}
    return reliability([r for r in rows if int(str(r.get("repeat"))) <= k], k)


def success_at(rows: list[dict[str, object]], limit: int) -> float | None:
    """成功且最慢一轮不超过limit秒的trial占比。"""
    if not rows:
        return None
    return sum(
        bool(r["success"]) and (number(r.get("max_turn_s")) or 0.0) <= limit for r in rows
    ) / len(rows)


def failure_table(rows: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    table: dict[str, Counter[str]] = {}
    for row in rows:
        if row["success"]:
            continue
        table.setdefault(str(row.get("reason") or "unknown"), Counter())[str(row["category"])] += 1
    return {reason: dict(counts) for reason, counts in sorted(table.items())}


def cache_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    """trial级输入token合计的缓存命中率；有trial未知时合计为None，另给已测子集。"""
    known = [r["cache"] for r in rows if isinstance(r.get("cache"), dict)]
    measured = cache_totals(known) if known else None
    return {
        "measured_n": len(known),
        "unknown_n": len(rows) - len(known),
        "hit_rate": measured["cache_hit_rate"] if measured and len(known) == len(rows) else None,
        "measured_hit_rate": measured["cache_hit_rate"] if measured else None,
    }


def summarize(
    rows: list[dict[str, object]], repeat: int, stopped: str | None = None
) -> dict[str, object]:
    costs = [c for c in (cost_of(r) for r in rows) if c is not None]
    unknown_claims = sum(int(str(r.get("claim_unknown") or 0)) for r in rows)
    categories = sorted({str(r["category"]) for r in rows})
    return {
        "trials": len(rows),
        "repeat": repeat,
        "stopped": stopped,
        "success_rate": sum(bool(r["success"]) for r in rows) / len(rows) if rows else None,
        "pass_power_1": pass_power(rows, 1, repeat)["pass_power_k"],
        "pass_power_3": pass_power(rows, 3, repeat)["pass_power_k"],
        "success_at_note": "仅供参考：如果设了时间上限T会怎样；时延不参与success",
        "success_at": {str(t): success_at(rows, t) for t in THRESHOLDS},
        "by_category": {
            c: {
                "trials": sum(r["category"] == c for r in rows),
                "success_rate": sum(bool(r["success"]) for r in rows if r["category"] == c)
                / sum(r["category"] == c for r in rows),
            }
            for c in categories
        },
        "failures": failure_table(rows),
        "total_s": distribution([v for r in rows if (v := number(r.get("total_s"))) is not None]),
        "ttfua_s": distribution([v for r in rows if (v := number(r.get("ttfua_s"))) is not None]),
        "cost_cny": {
            "total": str(sum(costs, Decimal(0))) if len(costs) == len(rows) else None,
            "per_trial": str(sum(costs, Decimal(0)) / len(costs)) if costs else None,
        },
        "cache": cache_summary(rows),
        "judge": judge_report(rows),
        "claim_unknown": {
            "count": unknown_claims,
            "trials_with_unknown": sum(bool(r.get("claim_unknown")) for r in rows),
            "note": "unknown不判失败，单独显示",
        },
    }


def scatter_rows(rows: list[dict[str, object]]) -> list[list[object]]:
    return [
        [
            row["case_id"],
            row["category"],
            row["trial"],
            int(bool(row["success"])),
            row.get("total_s"),
            row.get("max_turn_s"),
            row.get("ttfua_s"),
            "" if row.get("soft_score") is None else row["soft_score"],
            "" if row.get("judge_yes_rate") is None else row["judge_yes_rate"],
            row.get("cost_cny", ""),
            row.get("reason") or "",
        ]
        for row in rows
    ]


def render_markdown(manifest: dict[str, object], summary: dict[str, object]) -> str:
    def pct(value: object) -> str:
        return "n/a" if value is None else f"{float(str(value)) * 100:.0f}%"

    lines = [
        f"# v3评测报告 {manifest.get('run_name')}",
        "",
        "- 模式：" + ("live（真实调用）" if manifest.get("live") else "离线夹具（只证明设施）"),
        f"- profile：{manifest.get('profile')}；git：{str(manifest.get('git_sha'))[:10]}",
        f"- trial数：{summary['trials']}（repeat={summary['repeat']}）",
    ]
    if summary["stopped"]:
        lines.append(f"- 提前停止：{summary['stopped']}")
    at = summary["success_at"]
    assert isinstance(at, dict)
    lines += [
        "",
        "## 成功率",
        f"- success：{pct(summary['success_rate'])}；pass^1：{pct(summary['pass_power_1'])}；"
        f"pass^3：{pct(summary['pass_power_3'])}",
        "- Success@T（仅供参考，时延不参与success；表示“若设上限T秒”的假想成功率）："
        + "，".join(f"@{t}s {pct(v)}" for t, v in at.items()),
        "",
        "## 失败原因 x 类别",
    ]
    failures = summary["failures"]
    assert isinstance(failures, dict)
    if not failures:
        lines.append("无失败。")
    for reason, counts in failures.items():
        lines.append(f"- {reason}：" + "，".join(f"{c}={n}" for c, n in counts.items()))
    cost = summary["cost_cny"]
    total, ttfua = summary["total_s"], summary["ttfua_s"]
    assert isinstance(cost, dict) and isinstance(total, dict) and isinstance(ttfua, dict)
    unknown = summary["claim_unknown"]
    cache = summary["cache"]
    assert isinstance(unknown, dict) and isinstance(cache, dict)
    lines += [
        "",
        "## 耗时与成本",
        f"- 总耗时 p50/p95：{total['p50']}/{total['p95']} s",
        f"- TTFUA p50/p95：{ttfua['p50']}/{ttfua['p95']} s",
        f"- 成本（CNY）合计 {cost['total']}，每trial {cost['per_trial']}",
        f"- 输入缓存命中率：{pct(cache['hit_rate'])}"
        f"（已测{cache['measured_n']}个trial {pct(cache['measured_hit_rate'])}，"
        f"未知{cache['unknown_n']}）",
        f"- 声明判定unknown：{unknown['count']}次（{unknown['trials_with_unknown']}个trial）",
        "",
    ]
    judge = summary["judge"]
    assert isinstance(judge, dict)
    lines.append("## Rubric评审（不参与success；yes率=yes/(yes+no)）")
    lines.append(
        f"- 已评审trial：{judge['trials_judged']}；评审失败（judge_error）：{judge['judge_errors']}"
    )
    for name, stat in judge["items"].items():
        lines.append(
            f"- {name}：yes {stat['yes']} / no {stat['no']} / unknown {stat['unknown']}，"
            f"yes率 {pct(stat['yes_rate'])}"
        )
    for name, stat in judge["by_case"].items():
        lines.append(f"- 题 {name}：yes率 {pct(stat['yes_rate'])}")
    for name, stat in judge["paraphrase_flip"].items():
        lines.append(f"- 措辞翻转 {name}：{stat['flips']}/{stat['comparable']}")
    lines.append("")
    return "\n".join(lines)


def write_reports(
    directory: Path,
    manifest: dict[str, object],
    rows: list[dict[str, object]],
    repeat: int,
    stopped: str | None,
) -> dict[str, object]:
    summary = summarize(rows, repeat, stopped)
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (directory / "report.md").write_text(render_markdown(manifest, summary), encoding="utf-8")
    with (directory / "scatter.csv").open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(SCATTER_COLUMNS)
        writer.writerows(scatter_rows(rows))
    return summary
