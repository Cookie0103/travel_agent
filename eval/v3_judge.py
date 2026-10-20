"""v3 rubric评审：每个trial一次结构化调用，逐项yes/no/unknown；不参与success。

python -m eval.v3_judge sheet <run_dir>              # 导出两位人工评审的打分表
python -m eval.v3_judge agree <run_dir> <sheet.csv>  # 评审与人工、人工之间的一致性
"""

import argparse
import csv
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from eval.v3_cases import V3Case
from eval.v3_score import Observation, TurnObs

type Verdict = Literal["yes", "no", "unknown"]
VERDICTS = ("yes", "no", "unknown")
REASON_MAX = 40
AGREEMENT_TARGET = 0.8
MIN_PAIRS = 5

# 通用评审项（所有题共用）。ALT是同义改写，仅用于 --judge-check 的措辞稳定性自检。
GENERIC: tuple[tuple[str, str], ...] = (
    (
        "g-disclose",
        "没能满足的约束（超预算、营业时间未知、查不到等）是否都明确告诉了用户？不适用请答unknown。",
    ),
    ("g-no-reask", "卡片已经问过的内容，助手是否没有在文字里重复追问？没有相关卡片请答unknown。"),
    ("g-next-step", "回复是否能直接推进下一步（给出方案，或给出明确的选项）？"),
    ("g-tone", "语气是否礼貌简洁、没有空话？"),
)
GENERIC_ALT: tuple[tuple[str, str], ...] = (
    (
        "g-disclose",
        "凡是助手没做到或没查到的要求（比如预算不够、开放时间不明、没有结果），它有没有如实对用户说明？与本对话无关请答unknown。",
    ),
    (
        "g-no-reask",
        "对于卡片里已经让用户选过的事项，助手有没有避免在文字里再问一遍？对话里没有卡片请答unknown。",
    ),
    ("g-next-step", "读完这条回复，用户是否清楚下一步该做什么（有具体方案或明确可选项）？"),
    ("g-tone", "回复是否客气、简短、不啰嗦也不说套话？"),
)


class ItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    verdict: Verdict
    reason: str = Field(default="", max_length=400)


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    results: tuple[ItemResult, ...]


def items_for(case: V3Case, *, alt: bool = False) -> list[dict[str, str]]:
    generic = GENERIC_ALT if alt else GENERIC
    return [{"id": r.id, "q": r.q} for r in case.rubric] + [{"id": i, "q": q} for i, q in generic]


def tool_summary(turn: TurnObs) -> list[dict[str, object]]:
    """每个工具调用的精简摘要：只有名称与状态，不含参数和结果正文。"""
    started = {
        e.tool_call_id: e for e in turn.events if e.kind == "tool_started" and e.tool_call_id
    }
    rows: list[dict[str, object]] = []
    for event in turn.events:
        if event.kind != "tool_finished":
            continue
        status = "error" if event.code else "empty" if event.result_empty else "ok"
        rows.append(
            {
                "tool": event.tool_name,
                "status": status,
                "code": event.code,
                "result_empty": event.result_empty,
                "started": event.tool_call_id in started,
            }
        )
    return rows


def db_summary(obs: Observation) -> dict[str, object]:
    request = obs.state.get("request")
    keep = (
        "city",
        "start_date",
        "end_date",
        "adults",
        "child_ages",
        "rooms",
        "currency",
        "transport",
        "lodging_budget",
        "pace",
    )
    checks = obs.validation or ()
    return {
        "request": {k: request.get(k) for k in keep if k in request}
        if isinstance(request, Mapping)
        else {},
        "hotel_picks": obs.db.hotel_selected_segments,
        "draft_exists": obs.db.draft_exists,
        "validation": None
        if obs.validation is None
        else {
            "conflict": sum(c.get("status") == "conflict" for c in checks),
            "unknown": sum(c.get("status") == "unknown" for c in checks),
            "verified": sum(c.get("status") == "verified" for c in checks),
        },
        "plan_saved": obs.db.plan_saved,
        "active_memory": [
            {"key": f.get("key"), "value": f.get("value"), "scope": f.get("scope")}
            for f in obs.db.memory_current
            if f.get("status") == "active"
        ],
    }


def judge_payload(case: V3Case, obs: Observation, *, alt: bool = False) -> dict[str, object]:
    return {
        "items": items_for(case, alt=alt),
        "transcript": [
            {"turn": t.index, "user": t.user_text, "assistant": t.answer} for t in obs.turns
        ],
        "tools": [{"turn": t.index, "calls": tool_summary(t)} for t in obs.turns],
        "cards": [
            {
                "turn": t.index,
                "issued": [{"kind": c.kind, "groups": list(c.groups)} for c in t.cards],
            }
            for t in obs.turns
        ],
        "db": db_summary(obs),
    }


def parse_output(text: str, items: Sequence[Mapping[str, str]]) -> dict[str, dict[str, str]]:
    """严格校验：每个item恰好一条、id匹配、verdict合法；reason截断到40字。"""
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    output = JudgeOutput.model_validate_json(body)
    ids = [r.id for r in output.results]
    wanted = [i["id"] for i in items]
    if sorted(ids) != sorted(wanted):
        raise ValueError(f"评审项不一致：期望{wanted}，得到{ids}")
    questions = {i["id"]: i["q"] for i in items}
    return {
        r.id: {"q": questions[r.id], "verdict": r.verdict, "reason": r.reason[:REASON_MAX]}
        for r in output.results
    }


type JudgeCall = Callable[..., tuple[str, dict[str, object]]]


def judge_once(
    case: V3Case, obs: Observation, call: JudgeCall, root: Path, *, alt: bool = False
) -> dict[str, dict[str, str]]:
    """同步调用（由调用方放进线程）。DeepSeek温度0的结构化路径：call("rubric", payload, root)。"""
    payload = judge_payload(case, obs, alt=alt)
    text, _ = call("rubric", payload, root)
    return parse_output(text, payload["items"])  # type: ignore[arg-type]


def summarize_items(items: Mapping[str, Mapping[str, str]]) -> dict[str, object]:
    verdicts = Counter(v["verdict"] for v in items.values())
    decided = verdicts["yes"] + verdicts["no"]
    return {
        "yes_rate": verdicts["yes"] / decided if decided else None,
        "unknown_n": verdicts["unknown"],
    }


def judge_trial(
    case: V3Case, obs: Observation, call: JudgeCall, root: Path, *, check: bool = False
) -> dict[str, object]:
    """评审失败只记judge_error，绝不抛出、不改success。"""
    result: dict[str, object] = {"items": None, "yes_rate": None, "unknown_n": None, "error": None}
    try:
        items = judge_once(case, obs, call, root)
    except Exception as error:  # 调用失败/输出无效都不影响trial
        result["error"] = f"judge_error:{type(error).__name__}"
        return result
    result.update(items=items, **summarize_items(items))
    if check:
        try:
            other = judge_once(case, obs, call, root, alt=True)
            result["paraphrase"] = {
                i: {"first": items[i]["verdict"], "second": other[i]["verdict"]} for i, _ in GENERIC
            }
        except Exception as error:
            result["paraphrase_error"] = f"judge_error:{type(error).__name__}"
    return result


def flip_rates(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    """两种措辞下同一通用项的翻转率；任一为unknown的配对不计入分母。"""
    tally: dict[str, list[int]] = {}
    for row in rows:
        judge = row.get("judge")
        pairs = judge.get("paraphrase") if isinstance(judge, dict) else None
        if not isinstance(pairs, dict):
            continue
        for item, pair in pairs.items():
            first, second = pair["first"], pair["second"]
            if "unknown" in (first, second):
                continue
            stat = tally.setdefault(item, [0, 0])
            stat[0] += 1
            stat[1] += first != second
    return {
        item: {"comparable": n, "flips": f, "flip_rate": f / n if n else None}
        for item, (n, f) in sorted(tally.items())
    }


def judge_scores(judge: Mapping[str, object] | None) -> dict[str, float]:
    """只推数值：yes=1 / no=0，unknown省略；judge_error时什么都不推。"""
    if not judge or judge.get("error") or not isinstance(judge.get("items"), dict):
        return {}
    scores: dict[str, float] = {}
    rate = judge.get("yes_rate")
    if isinstance(rate, (int, float)):
        scores["judge_yes_rate"] = float(rate)
    unknown = judge.get("unknown_n")
    if isinstance(unknown, int):
        scores["judge_unknown_n"] = float(unknown)
    items = judge["items"]
    assert isinstance(items, dict)
    for item, entry in items.items():
        if entry["verdict"] in {"yes", "no"}:
            scores[f"judge_{item}"[:64]] = float(entry["verdict"] == "yes")
    return scores


def judge_report(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """逐项yes率（跨trial）与逐题yes率；judge_error单独计数。"""
    by_item: dict[str, Counter[str]] = {}
    by_case: dict[str, Counter[str]] = {}
    errors = judged = 0
    for row in rows:
        judge = row.get("judge")
        if not isinstance(judge, dict):
            continue
        if judge.get("error"):
            errors += 1
            continue
        judged += 1
        for item, entry in (judge.get("items") or {}).items():
            by_item.setdefault(item, Counter())[entry["verdict"]] += 1
            by_case.setdefault(str(row["case_id"]), Counter())[entry["verdict"]] += 1

    def rate(counter: Counter[str]) -> dict[str, object]:
        decided = counter["yes"] + counter["no"]
        return {
            "yes": counter["yes"],
            "no": counter["no"],
            "unknown": counter["unknown"],
            "yes_rate": counter["yes"] / decided if decided else None,
        }

    return {
        "trials_judged": judged,
        "judge_errors": errors,
        "items": {k: rate(v) for k, v in sorted(by_item.items())},
        "by_case": {k: rate(v) for k, v in sorted(by_case.items())},
        "paraphrase_flip": flip_rates(rows),
    }


# ---- 人工校准 ----


def render_transcript(case: V3Case, obs: Observation) -> str:
    lines = [f"# {case.case_id}：{case.title}", ""]
    for turn in obs.turns:
        lines += [
            f"## 第{turn.index}轮（用户{turn.user}，{turn.status}）",
            f"用户：{turn.user_text}",
            f"助手：{turn.answer}",
        ]
        tools = tool_summary(turn)
        if tools:
            lines.append("工具：" + "；".join(f"{t['tool']}={t['status']}" for t in tools))
        if turn.cards:
            lines.append("发出卡片：" + "、".join(c.kind for c in turn.cards))
        lines.append("")
    lines += ["## 服务器状态", json.dumps(db_summary(obs), ensure_ascii=False, indent=2), ""]
    return "\n".join(lines)


def write_transcript(directory: Path, case: V3Case, trial: int, obs: Observation) -> str:
    """写入私有run目录（.cache）；返回相对路径。"""
    folder = directory / "transcripts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{case.case_id}-{trial}.txt"
    path.write_text(render_transcript(case, obs), encoding="utf-8")
    return str(path.relative_to(directory))


SHEET_COLUMNS = (
    "run",
    "case_id",
    "trial",
    "item_id",
    "question",
    "transcript_path",
    "rater_a",
    "rater_b",
)


def load_rows(run_dir: Path) -> list[dict[str, object]]:
    path = run_dir / "trials.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def export_sheet(run_dir: Path, out: Path | None = None) -> Path:
    """不含评审结论，避免锚定；rater列留空。"""
    target = out or run_dir / "judge_sheet.csv"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHEET_COLUMNS)
        for row in load_rows(run_dir):
            judge = row.get("judge")
            if not isinstance(judge, dict) or not judge.get("items"):
                continue
            for item, entry in judge["items"].items():
                writer.writerow(
                    [
                        run_dir.name,
                        row["case_id"],
                        row["trial"],
                        item,
                        entry["q"],
                        row.get("transcript_path") or "",
                        "",
                        "",
                    ]
                )
    return target


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[v] * cb[v] for v in set(a) | set(b)) / (n * n)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def pair_stats(a: Sequence[str], b: Sequence[str]) -> dict[str, object]:
    n = len(a)
    return {
        "n": n,
        "agreement": sum(x == y for x, y in zip(a, b, strict=True)) / n if n else None,
        "kappa": cohen_kappa(a, b),
    }


def compute_agreement(run_dir: Path, sheet: Path) -> dict[str, object]:
    """逐项：评审-人A、评审-人B、人A-人B的一致率与kappa；unknown与空白一律忽略。"""
    judged: dict[tuple[str, int, str], str] = {}
    for row in load_rows(run_dir):
        judge = row.get("judge")
        if isinstance(judge, dict) and judge.get("items"):
            for item, entry in judge["items"].items():
                judged[(str(row["case_id"]), int(str(row["trial"])), item)] = entry["verdict"]
    columns: dict[str, dict[str, list[str]]] = {}
    with sheet.open(encoding="utf-8", newline="") as handle:
        for line in csv.DictReader(handle):
            key = (line["case_id"], int(line["trial"]), line["item_id"])
            verdict = judged.get(key)
            a, b = line["rater_a"].strip().lower(), line["rater_b"].strip().lower()
            bucket = columns.setdefault(
                line["item_id"], {"j_a": [], "a": [], "j_b": [], "b": [], "ra": [], "rb": []}
            )
            ok = {"yes", "no"}
            if verdict in ok and a in ok:
                bucket["j_a"].append(verdict)
                bucket["a"].append(a)
            if verdict in ok and b in ok:
                bucket["j_b"].append(verdict)
                bucket["b"].append(b)
            if a in ok and b in ok:
                bucket["ra"].append(a)
                bucket["rb"].append(b)
    items: dict[str, dict[str, object]] = {}
    for item, bucket in sorted(columns.items()):
        stats: dict[str, dict[str, Any]] = {
            "judge_vs_a": pair_stats(bucket["j_a"], bucket["a"]),
            "judge_vs_b": pair_stats(bucket["j_b"], bucket["b"]),
            "a_vs_b": pair_stats(bucket["ra"], bucket["rb"]),
        }
        enough = all(stats[k]["n"] >= MIN_PAIRS for k in ("judge_vs_a", "judge_vs_b"))
        reached = enough and all(
            (stats[k]["agreement"] or 0) >= AGREEMENT_TARGET for k in ("judge_vs_a", "judge_vs_b")
        )
        items[item] = {**stats, "reaches_80": reached, "enough_pairs": enough}
    return {"items": items, "candidates": [i for i, v in items.items() if v["reaches_80"]]}


def fmt(value: float | None, spec: str) -> str:
    return "n/a" if value is None else format(value, spec)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sheet = sub.add_parser("sheet")
    sheet.add_argument("run_dir", type=Path)
    agree = sub.add_parser("agree")
    agree.add_argument("run_dir", type=Path)
    agree.add_argument("sheet", type=Path)
    args = parser.parse_args()
    if args.command == "sheet":
        print(export_sheet(args.run_dir))
        return 0
    report: Any = compute_agreement(args.run_dir, args.sheet)
    (args.run_dir / "agreement.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for item, stats in report["items"].items():
        parts = [
            f"{name}: n={s['n']} 一致={fmt(s['agreement'], '.0%')} kappa={fmt(s['kappa'], '.2f')}"
            for name, s in stats.items()
            if isinstance(s, dict)
        ]
        print(f"{item}  " + " | ".join(parts) + ("  ✔≥80%" if stats["reaches_80"] else ""))
    print("达到80%一致、可考虑纳入success的项：", report["candidates"] or "无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
