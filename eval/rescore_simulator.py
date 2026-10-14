"""补强后的同批统一重算；只读原始回答/事件，不再调用模型。"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import TypeAdapter

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.plans import SavedPlan
from eval.cases import Case
from eval.claims import CLAIM_SCORER_VERSION, claim_consistency
from eval.content import AnswerRecord
from eval.graders import memory_presentations_allowed
from eval.memory_metrics import SCORER_VERSION, memory_scores
from eval.report import reliability
from eval.run import manifest
from eval.simulator import hotel_delivered, recalled
from eval.simulator_metrics import (
    claims_pass,
    dialogue_claims,
    no_reoffer_after_decline,
    saved_items_cover_segments,
)
from eval.suites import load_suite

ROOT = Path(__file__).resolve().parents[1]


def event_path(context: RunContext) -> Path:
    return (
        ROOT
        / ".cache"
        / "sessions"
        / str(context.user_id)
        / str(context.session_id)
        / f"events-{context.run_id}.jsonl"
    )


def source_events(rows: list[dict[str, object]]) -> set[Path]:
    paths: set[Path] = set()
    for row in rows:
        content = row.get("content_record")
        if isinstance(content, dict):
            paths.add(event_path(TypeAdapter(RunContext).validate_python(content["context"])))
        steps = row.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and isinstance(step.get("external"), str):
                    paths.add(event_path(TypeAdapter(RunContext).validate_python(step["context"])))
    return paths


def original_events(row: dict[str, object]) -> tuple[RuntimeEvent, ...]:
    values = row.get("steps")
    if not isinstance(values, list):
        raise ValueError("缺少原始步骤")
    restored = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("步骤格式无效")
        item = dict(item)
        if isinstance(item.get("external"), str):
            # 首批asdict未递归Pydantic子对象：从同一实际SDK事件文件恢复，绝不猜字符串。
            context = TypeAdapter(RuntimeEvent).validate_python({**item, "external": None}).context
            path = event_path(context)
            matches = [
                json.loads(line)
                for line in (path.read_text(encoding="utf-8").splitlines() if path.exists() else [])
                if line.strip()
            ]
            matched = [
                event
                for event in matches
                if event.get("kind") == item.get("kind")
                and event.get("tool_call_id") == item.get("tool_call_id")
                and event.get("context") == item.get("context")
            ]
            item["external"] = (
                matched[0]["external"]
                if len(matched) == 1 and isinstance(matched[0].get("external"), dict)
                else None
            )
        restored.append(item)
    return TypeAdapter(tuple[RuntimeEvent, ...]).validate_python(restored)


def rescore(row: dict[str, object]) -> dict[str, object]:
    original = row.get("checks")
    if not isinstance(original, dict) or any(type(v) is not bool for v in original.values()):
        raise ValueError("缺少原始确定性终态")
    checks = dict(original)
    events = original_events(row)
    case = row.get("case_id")
    if case in {"v2-user-pace", "v2-user-429"}:
        checks["hotel_delivery"] = hotel_delivered(events)
    if case == "v2-user-429":
        checks["recovered"] = any(
            e.kind == "tool_finished"
            and e.tool_name == "search_hotel_offers"
            and e.code is None
            and e.external
            and e.external.recovered_from
            for e in events
        )
    if case in {"v2-user-memory-cross", "v2-user-memory-trip"}:
        dialogue = row.get("dialogue")
        if not isinstance(dialogue, list) or not dialogue or not isinstance(dialogue[-1], dict):
            raise ValueError("缺少实际末轮回答")
        checks["recall"] = recalled(
            str(dialogue[-1]["answer"]), long_term=case == "v2-user-memory-cross"
        )
    dialogue = TypeAdapter(list[dict[str, object]]).validate_python(row.get("dialogue"))
    declined: bool | None = None
    if case == "v2-user-budget-reject":
        declined = no_reoffer_after_decline(dialogue)
        if declined is not None:
            checks["no_reoffer_after_decline"] = declined
    if case == "v2-user-three-segments":
        saved = SavedPlan.model_validate(row["saved_plan"]) if row.get("saved_plan") else None
        checks["saved_items_cover_segments"] = saved_items_cover_segments(
            saved, TypeAdapter(dict[str, object]).validate_python(row["conditions"])
        )
    claims = dialogue_claims(dialogue, events)
    claim_result = claims_pass(claims)
    if claim_result is not None:
        checks["claim_consistency"] = claim_result
    return {
        **row,
        "checks": checks,
        "claim_consistency": claims,
        "no_reoffer_after_decline": declined,
        "repeat": row.get("trial"),
        "steps": TypeAdapter(tuple[RuntimeEvent, ...]).dump_python(events, mode="json"),
        "status": "passed" if all(checks.values()) else "failed",
        "rescore_basis": "F5 v3: all original trials; target-clause recall; saved dates; "
        "same-revision amount reoffer; per-run claims; missing evidence unknown; no model rerun",
    }


def record_events(row: dict[str, object]) -> tuple[AnswerRecord, tuple[RuntimeEvent, ...] | None]:
    record = AnswerRecord.model_validate(row["content_record"])
    path = event_path(record.context)
    if not path.exists():
        return record, None
    events = TypeAdapter(tuple[RuntimeEvent, ...]).validate_python(
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    )
    if any(e.context != record.context for e in events):
        raise ValueError("原始SDK事件不属于本轮回答")
    return record, events


def rescore_interaction(row: dict[str, object]) -> dict[str, object]:
    record, events = record_events(row)
    if events is None:
        return {
            **row,
            "claim_consistency": {"passed": None, "card": None, "retry": None, "expiry": None},
            "rescore_basis": "F5 v3: SDK events unavailable; unknown",
        }
    claims = claim_consistency(
        record.text,
        events,
        answered_at=record.observed_at,
        valid_until=tuple(
            g.record.valid_until for g in record.evidence if g.record.kind == "hotel_offer"
        ),
    )
    checks = TypeAdapter(dict[str, bool]).validate_python(row["checks"])
    if claims["passed"] is not None:
        checks["claim_consistency"] = claims["passed"]
    return {
        **row,
        "checks": checks,
        "claim_consistency": claims,
        "failed_checks": [name for name, ok in checks.items() if not ok],
        "status": "passed" if all(checks.values()) else "failed",
        "rescore_basis": "F5 v3: all original E5 answers and identity-matched SDK events; "
        "no model rerun",
    }


def rescore_memory(row: dict[str, object], case: Case) -> dict[str, object]:
    metrics = TypeAdapter(dict[str, object]).validate_python(row["memory_metrics"])
    predictions = TypeAdapter(list[dict[str, object]]).validate_python(metrics["predictions"])
    score = memory_scores(
        [item.model_dump(mode="json") for item in case.expected_memory],
        predictions,
        invalid_attempts=TypeAdapter(int).validate_python(metrics["invalid_attempts"]),
    )
    checks = TypeAdapter(dict[str, bool]).validate_python(row["checks"])
    checks["memory_exact"] = score["exact"] is True
    _, events = record_events(row)
    display: bool | None = None
    if events is not None:
        names = {e.tool_name for e in events if e.kind == "tool_started"}
        allowed = set(case.allowed_tools)
        if "present_travel_result" in names:
            display = memory_presentations_allowed(events)
            if display:
                allowed.add("present_travel_result")
        checks["no_unnecessary_tools"] = names <= allowed
    return {
        **row,
        "checks": checks,
        "memory_metrics": {**metrics, **score},
        "memory_presentation_allowed": display,
        "failed_checks": [name for name, ok in checks.items() if not ok],
        "status": "passed" if all(checks.values()) else "failed",
        "rescore_basis": "F6 memory-v3: all original source-valid predictions; unchanged gold; "
        "normalized free text and polarity; verified same-run memory presentation only",
    }


def changed_checks(old: dict[str, object], new: dict[str, object]) -> dict[str, object]:
    old_checks = TypeAdapter(dict[str, bool]).validate_python(old["checks"])
    new_checks = TypeAdapter(dict[str, bool]).validate_python(new["checks"])
    return {
        "case_id": new["case_id"],
        "trial": new.get("trial", new.get("repeat")),
        "checks": {
            k: {"old": old_checks.get(k), "new": v}
            for k, v in new_checks.items()
            if old_checks.get(k) != v
        },
    }


def verify_originals(hashes: Path) -> dict[str, str]:
    frozen = TypeAdapter(dict[str, str]).validate_json(hashes.read_bytes())
    for relative, digest in frozen.items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            raise ValueError(f"原始文件hash改变：{relative}")
    return frozen


def write_rescore(results: Path, hashes: Path, out: Path | None = None) -> dict[str, object]:
    frozen = verify_originals(hashes)
    original_digest = hashlib.sha256(results.read_bytes()).hexdigest()
    if original_digest not in frozen.values():
        raise ValueError("待重算文件不属于冻结输入hash")
    original = TypeAdapter(list[dict[str, object]]).validate_python(
        [
            json.loads(line)
            for line in results.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    )
    source_hashes = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        if path.exists()
        else None
        for path in source_events(original)
    }
    source_frozen_at = datetime.now(UTC).isoformat()
    memory_cases: dict[str, Case] = {}
    gold_hashes: dict[str, str] = {}
    if any(str(row.get("case_id")).startswith("v2-mem-") for row in original):
        cases, suite = load_suite(ROOT, "v2-memory", "dev")
        metadata_path = results.parent / "manifest.json"
        if hashlib.sha256(metadata_path.read_bytes()).hexdigest() not in frozen.values():
            raise ValueError("原始记忆manifest不属于冻结输入hash")
        metadata = TypeAdapter(dict[str, object]).validate_json(metadata_path.read_bytes())
        old_suite = TypeAdapter(dict[str, object]).validate_python(metadata["evaluation_suite"])
        if old_suite.get("sha256") != suite["sha256"]:
            raise ValueError("记忆金标文件与原始manifest的hash不符")
        memory_cases = {case.case_id: case for case in cases}
        gold_hashes = TypeAdapter(dict[str, str]).validate_python(suite["sha256"])
    rows = [
        rescore_memory(row, memory_cases[str(row["case_id"])])
        if str(row.get("case_id")).startswith("v2-mem-")
        else rescore(row)
        if str(row.get("case_id")).startswith("v2-user-")
        else rescore_interaction(row)
        for row in original
    ]
    for relative, source_digest in source_hashes.items():
        path = ROOT / relative
        if (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        ) != source_digest:
            raise ValueError("重算中SDK原始事件变化")
    directory = out or results.parent
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "rescored-v3-results.jsonl"
    summary_path = directory / "rescored-v3-summary.json"
    manifest_path = directory / "rescored-v3-manifest.json"
    if target.exists() or summary_path.exists() or manifest_path.exists():
        raise FileExistsError("v3重算输出已存在，不覆盖")
    previous_path = results.parent / "rescored-results.jsonl"
    previous = (
        TypeAdapter(list[dict[str, object]]).validate_python(
            [
                json.loads(line)
                for line in previous_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        )
        if previous_path.exists()
        else None
    )
    summary: dict[str, object] = {
        "n": len(rows),
        "original_passed": sum(r["status"] == "passed" for r in original),
        "previous_passed": sum(r["status"] == "passed" for r in previous)
        if previous is not None
        else None,
        "passed": sum(r["status"] == "passed" for r in rows),
        "unknown_reoffer_n": sum(
            r.get("no_reoffer_after_decline") is None
            for r in rows
            if r.get("case_id") == "v2-user-budget-reject"
        ),
        "unknown_claim_n": sum(
            claims_pass(
                TypeAdapter(list[dict[str, bool | None]]).validate_python(r["claim_consistency"])
            )
            is None
            if isinstance(r.get("claim_consistency"), list)
            else TypeAdapter(dict[str, bool | None]).validate_python(r["claim_consistency"])[
                "passed"
            ]
            is None
            for r in rows
            if "claim_consistency" in r
        ),
        "unknown_memory_presentation_n": sum(
            r.get("memory_presentation_allowed") is None
            for r in rows
            if "present_travel_result" in TypeAdapter(list[str]).validate_python(r.get("tools", []))
            and str(r.get("case_id")).startswith("v2-mem-")
        ),
        "scorer_version": SCORER_VERSION if memory_cases else "interaction-v4-scoped-claims",
        "gold_sha256": gold_hashes,
        "cost_cny": str(
            sum(
                (Decimal(str(r.get("cost_cny", r.get("run_accounted_cny", "0")))) for r in rows),
                Decimal(0),
            )
        ),
        "reliability": reliability(
            [{**r, "repeat": r.get("repeat", r.get("trial"))} for r in rows], 3
        ),
        "original_sha256": hashlib.sha256(results.read_bytes()).hexdigest(),
        "source_event_sha256": source_hashes,
        "source_events_frozen_at": source_frozen_at,
        "source_events_basis": "本次重算首次读取前补充冻结，非F0的55项；重算后逐项复核",
        "changed": [
            changed_checks(old, new)
            for old, new in zip(original, rows, strict=True)
            if old["checks"] != new["checks"]
        ],
        "scope": "全部原始轨迹统一重算；saved_three仅检查酒店段数；语义未人工校准；未知未判失败",
    }
    with target.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    with summary_path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    with manifest_path.open("x", encoding="utf-8") as output:
        output.write(
            json.dumps(
                {
                    **manifest([]),
                    "scorer_version": summary["scorer_version"],
                    "claim_scorer_version": CLAIM_SCORER_VERSION,
                    "gold_sha256": gold_hashes,
                    "input_sha256": original_digest,
                    "source_events_frozen_at": source_frozen_at,
                    "scope": "uniform offline rescore; original files unchanged; no model calls",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument(
        "--hashes", type=Path, default=ROOT / ".cache/batch-2026-10-14/f0-original-hashes.json"
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    summary = write_rescore(args.results, args.hashes, args.out)
    print((args.out or args.results.parent) / "rescored-v3-results.jsonl")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
