"""从已落盘的实际评测补写数值分数；不调用模型、不上传回答或评语。"""

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from uuid import uuid4

from backend.adapters.tracing import push_scores
from eval.report import reliability
from eval.run import ROOT, manifest
from eval.triage import Triage


def trial_scores(row: dict[str, object]) -> dict[str, float]:
    scores: dict[str, float] = {}

    def add(name: str, value: object) -> None:
        if type(value) in (int, float) and isinstance(value, (int, float)):
            if math.isfinite(value) and value >= 0:
                scores["v2." + name] = float(value)

    if row.get("status") in {"passed", "failed"}:
        add("rule_pass", int(row["status"] == "passed"))
    add("elapsed_seconds", row.get("elapsed_seconds"))
    raw_cost = row.get("cost_cny", row.get("run_accounted_cny"))
    if isinstance(raw_cost, str):
        try:
            add("cost_cny", float(raw_cost))
        except ValueError:
            pass
    process = row.get("process", row.get("process_metrics"))
    if isinstance(process, dict):
        for name in (
            "tool_calls",
            "duplicate_calls",
            "recovered_without_user",
            "user_visible_errors",
            "user_visible_first_errors",
        ):
            add(name, process.get(name))
    constraints = row.get("saved_constraints")
    if isinstance(constraints, dict):
        add("constraints_micro", constraints.get("micro_pass_rate"))
        if type(constraints.get("all_constraints")) is bool:
            add("all_constraints", int(constraints["all_constraints"]))
        if (
            row.get("case_id") == "v2-user-three-segments"
            and type(constraints.get("delivered")) is bool
        ):
            add("saved_delivery", int(constraints["delivered"]))
    memory = row.get("memory_metrics")
    if isinstance(memory, dict):
        for name in ("precision", "recall"):
            add("memory_" + name, memory.get(name))
        for name in ("exact",):
            if type(memory.get(name)) is bool:
                add("memory_" + name, int(memory[name]))
    checks = row.get("checks")
    if isinstance(checks, dict):
        for name in (
            "expected_state",
            "request_unchanged",
            "budget_answered",
            "pace_clicked",
            "confirmed_scope",
            "injected_scope",
            "saved_three",
            "no_orders",
        ):
            if type(checks.get(name)) is bool:
                add("state_" + name, int(checks[name]))
    return scores


def triage_scores(row: dict[str, object]) -> dict[str, float]:
    try:
        reference = Triage.model_validate(row.get("reference"))
    except ValueError:
        return {"v2.triage_valid_output": 0.0}
    scores = {"v2.triage_valid_output": 1.0, "v2.triage_" + reference.label + "_unverified": 1.0}
    if reference.first_step is not None:
        scores["v2.triage_first_step_unverified"] = float(reference.first_step)
    return scores


def read_rows(path: Path) -> list[dict[str, object]]:
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("实际评测行必须是JSON对象")
    return rows


def match_triage(
    original: list[dict[str, object]], references: list[dict[str, object]]
) -> list[tuple[dict[str, object], dict[str, object]]]:
    failed = [row for row in original if row.get("status") == "failed"]
    counts = Counter(str(row.get("case_id")) for row in failed)
    pairs = []
    for row, reference in zip(failed, references, strict=True):
        left = row.get("trial") if type(row.get("trial")) is int else row.get("repeat")
        right = (
            reference.get("trial")
            if type(reference.get("trial")) is int
            else reference.get("repeat")
        )
        # 旧分诊未写repeat；只有该case恰好一个失败来源时才能无歧义绑定。
        legacy_unique = right is None and counts[str(row.get("case_id"))] == 1
        if row.get("case_id") != reference.get("case_id") or (
            not legacy_unique and (right is None or left != right)
        ):
            raise ValueError("分诊与实际来源轮次不匹配")
        pairs.append((row, reference))
    return pairs


def main() -> int:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--triage", type=Path)
    parser.add_argument("--trace-cloud", action="store_true")
    args = parser.parse_args()
    targets: list[tuple[str, dict[str, float]]] = []
    for path in args.results:
        rows = read_rows(path)
        source = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
        repeats = source.get("repeat", source.get("repetitions"))
        for row in rows:
            if not isinstance(trace_id := row.get("trace_id"), str):
                continue
            scores = trial_scores(row)
            if type(repeats) is int and 1 <= repeats <= 3:
                group = [r for r in rows if r.get("case_id") == row.get("case_id")]
                measures = reliability(
                    [{**r, "repeat": r.get("repeat", r.get("trial"))} for r in group], repeats
                )
                for key, suffix in (
                    ("pass_at_1", "pass_at_1"),
                    ("pass_at_k", f"pass_at_{repeats}"),
                    ("pass_power_k", f"pass_power_{repeats}"),
                ):
                    value = measures[key]
                    if isinstance(value, float):
                        scores["v2.case_" + suffix] = value
            targets.append((trace_id, scores))
    if args.triage:
        original = read_rows(args.triage.parent / "results.jsonl")
        references = read_rows(args.triage)
        for row, reference in match_triage(original, references):
            if isinstance(trace_id := row.get("trace_id"), str):
                targets.append((trace_id, triage_scores(reference)))
    if not args.trace_cloud:
        print(json.dumps({"prepared": len(targets), "model_calls": 0, "network_calls": 0}))
        return 0
    load_dotenv(ROOT / ".env", override=False)
    directory = ROOT / ".cache" / "published-v2" / uuid4().hex
    directory.mkdir(parents=True)
    source_paths = list(
        dict.fromkeys(
            [
                *args.results,
                *[p.parent / "manifest.json" for p in args.results],
                *([args.triage, args.triage.parent / "results.jsonl"] if args.triage else []),
            ]
        )
    )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                **manifest([]),
                "input_sha256": {
                    str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths
                },
                "scope": "numeric scores of existing traces only; "
                "ingestion acceptance is not readback; legacy memory privacy probes omitted",
                "model_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    accepted = 0
    with (directory / "attempts.jsonl").open("x", encoding="utf-8") as output:
        for trace_id, scores in targets:
            receipt = push_scores(trace_id, scores, batch=True)
            accepted += receipt
            output.write(
                json.dumps({"trace_id": trace_id, "scores": scores, "accepted": receipt}) + "\n"
            )
            output.flush()
    print(
        json.dumps(
            {
                "targets": len(targets),
                "accepted": accepted,
                "model_calls": 0,
                "receipts": str(directory),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
