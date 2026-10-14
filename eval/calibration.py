"""实际回答盲标30条与固定温度模型参考；真人列始终由用户填写。"""

import argparse
import csv
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.execution import RuntimeEvent
from eval.calibrate_v2 import agreement, prepare
from eval.content import QualityScore
from eval.event_summary import JudgeEvents, event_summary
from eval.persona import content_reference
from eval.rescore_simulator import original_events, record_events
from eval.run import manifest
from eval.simulator_metrics import dialogue_event_groups
from eval.structured import structured_call
from eval.suites import load_suite
from scripts.dev import configure_environment

ROOT = Path(__file__).resolve().parents[1]


class ComparisonScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    preferred: Literal["A", "B", "tie"]
    reason: str = Field(max_length=300)


def varied_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered: list[dict[str, object]] = []
    for status in ("passed", "failed"):
        remaining = [r for r in rows if r.get("status") == status and r.get("text")]
        while remaining:
            seen: set[str] = set()
            next_round = []
            for row in remaining:
                key = str(row.get("case_id"))
                if key in seen:
                    next_round.append(row)
                else:
                    ordered.append(row)
                    seen.add(key)
            remaining = next_round
    return ordered


def task_context(row: dict[str, object]) -> str:
    """多轮末回复应结合实际用户动作评审，不把隐藏目标当作用户原话。"""
    parts = [str(row.get("user_input", ""))]
    dialogue = row.get("dialogue")
    if isinstance(dialogue, list):
        for turn in dialogue[:8]:
            if not isinstance(turn, dict) or not isinstance(turn.get("user"), dict):
                continue
            user = turn["user"]
            parts.append(
                f"用户动作 {user.get('kind')}: {user.get('text', '')}"
                + (f"；选项 {user['option_id']}" if user.get("option_id") else "")
            )
    return "\n".join(parts)[:12000]


def comparison_pairs(
    rows: list[dict[str, object]],
) -> list[tuple[dict[str, object], dict[str, object]]]:
    """顺序偏差只比较同任务、同条件；同case的不同用户动作不能混配。"""
    pairs = []
    for case_id in sorted({str(r.get("case_id")) for r in rows}):
        positives = [
            r
            for r in rows
            if r.get("case_id") == case_id and r.get("status") == "passed" and r.get("text")
        ]
        negatives = [
            r
            for r in rows
            if r.get("case_id") == case_id and r.get("status") == "failed" and r.get("text")
        ]
        for positive in positives:
            task = positive.get("user_input")
            if (
                not isinstance(task, str)
                or not task.strip()
                or len(task) >= 12000
                or not isinstance(positive.get("conditions"), dict)
            ):
                continue  # 缺失/截断上下文不能作为相同实际任务的证明。
            signature = json.dumps(
                [positive.get("user_input"), positive.get("conditions")],
                sort_keys=True,
                ensure_ascii=False,
            )
            negative = next(
                (
                    r
                    for r in negatives
                    if json.dumps(
                        [r.get("user_input"), r.get("conditions")],
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    == signature
                ),
                None,
            )
            if negative is not None:
                pairs.append((positive, negative))
                break
        if len(pairs) == 2:
            break
    return pairs


def row_event_summary(
    row: dict[str, object], events: tuple[RuntimeEvent, ...] | None
) -> JudgeEvents:
    if events is None:
        return event_summary(None)
    dialogue = row.get("dialogue")
    if not isinstance(dialogue, list):
        # 单轮AnswerRecord已由record_events核对context。
        return event_summary(events)
    turns = [turn for turn in dialogue if isinstance(turn, dict) and "status" in turn]
    groups = dialogue_event_groups(turns, events)
    if not turns or len(groups) != len(turns) or row.get("text") != turns[-1].get("answer"):
        return event_summary(None)
    return event_summary(groups[-1])


def main() -> int:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--threshold", type=int, choices=range(1, 6), default=3)
    args = parser.parse_args()
    cases = {}
    for suite in ("v2", "v2-memory"):
        loaded, _ = load_suite(ROOT, suite, "dev")
        cases.update({case.case_id: case for case in loaded})
    rows = []
    for path in args.results:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            case = cases.get(row.get("case_id"))
            if case:
                row["user_input"] = case.input
                row["conditions"] = {
                    "initial_state": case.initial_state,
                    "expected_memory": [m.model_dump(mode="json") for m in case.expected_memory],
                }
            events = (
                original_events(row)
                if isinstance(row.get("steps"), list)
                else record_events(row)[1]
                if isinstance(row.get("content_record"), dict)
                else None
            )
            row["event_summary"] = row_event_summary(row, events).model_dump(mode="json")
            row["origin"] = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
            row["user_input"] = task_context(row)
            rows.append(row)
    selected = varied_rows(rows)
    directory = ROOT / ".cache" / "calibration" / uuid4().hex
    target = prepare(selected, directory)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                **manifest([]),
                "purpose": "balanced_rule_outcomes_blind_calibration",
                "sources": [str(p) for p in args.results],
                "model_binary_threshold": args.threshold,
                "content_score_title": "未校准参考分",
                "task_pass_gate": False,
                "selection": "unique case first; subsequent trials round-robin; "
                "fixed shuffle; not representative success rate",
                "human_labels": "empty until user labels",
            },
            ensure_ascii=False,
            default=str,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not args.live:
        print(target)
        return 0
    configure_environment()
    load_dotenv(ROOT / ".env", override=False)
    reference_path = directory / "hidden-reference.json"
    references = json.loads(reference_path.read_text(encoding="utf-8"))
    with target.open(encoding="utf-8-sig", newline="") as handle:
        samples = list(csv.DictReader(handle))
    with (directory / "model-attempts.jsonl").open("x", encoding="utf-8") as attempts:
        for sample in samples:
            response, report = structured_call(
                "content",
                {
                    "task": sample["task"],
                    "conditions": sample["conditions"],
                    "candidate": sample["answer"],
                    "event_summary": references["references"][sample["sample_id"]]["event_summary"],
                },
                ROOT,
            )
            try:
                quality = QualityScore.model_validate_json(response)
                fields = quality.model_dump()
                reference = content_reference(quality, threshold=args.threshold)
                value = int(reference["binary_reference"] is True)
                references["references"][sample["sample_id"]].update(
                    model_reference=value,
                    model_quality=fields,
                    content_score_title="未校准参考分",
                    task_pass_gate=False,
                    model_binary_threshold=args.threshold,
                )
            except ValueError:
                value = None
            attempts.write(
                json.dumps(
                    {
                        "sample_id": sample["sample_id"],
                        "model_reference": value,
                        "trace_id": report.get("trace_id"),
                        "cost_cny": report.get("run_accounted_cny"),
                        "http_attempts": report.get("http_attempts"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            attempts.flush()
            reference_path.write_text(
                json.dumps(references, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    # 配对样本必须同一case，A/B交换仅比较位置，不让不同任务互相比。
    pairs = comparison_pairs(rows)
    position = []
    for positive, negative in pairs:
        measured = []
        for reverse in (False, True):
            left, right = (negative, positive) if reverse else (positive, negative)
            response, report = structured_call(
                "comparison",
                {
                    "task": positive.get("user_input"),
                    "conditions": positive.get("conditions"),
                    "A": left["text"],
                    "B": right["text"],
                },
                ROOT,
            )
            preference = ComparisonScore.model_validate_json(response).preferred
            normalized = (
                "tie"
                if preference == "tie"
                else ("positive" if (preference == "A") != reverse else "negative")
            )
            measured.append(
                {
                    "reverse": reverse,
                    "normalized": normalized,
                    "trace_id": report.get("trace_id"),
                    "cost_cny": report.get("run_accounted_cny"),
                    "http_attempts": report.get("http_attempts"),
                }
            )
        position.append(
            {
                "case_id": positive["case_id"],
                "judgments": measured,
                "consistent": measured[0]["normalized"] == measured[1]["normalized"],
            }
        )
    (directory / "position-bias.json").write_text(
        json.dumps(
            {
                "pairs": position,
                "requested_pairs": 2,
                "matched_pairs": len(pairs),
                "matching": "same case, actual task context and conditions; shortage not filled",
                "limitation": "small synthetic text comparison; "
                "not proof of general absence of position bias",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "calibration-status.json").write_text(
        json.dumps(agreement([]), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
