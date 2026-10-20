"""实际回答盲标30条与固定温度模型参考；真人列始终由用户填写。"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from backend.domain.execution import RunContext, RuntimeEvent
from backend.providers.claude_agent.structured import structured_call
from eval.content import AnswerRecord, QualityScore
from eval.event_summary import JudgeEvents, event_summary
from eval.guard import refuse_live_under_pytest
from eval.persona import content_reference
from eval.run import manifest
from eval.simulator_metrics import dialogue_event_groups
from eval.suites import load_suite
from scripts.dev import configure_environment

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


def agreement(
    pairs: list[tuple[int, int]], *, minimum_pairs: int = 30, allow_partial: bool = True
) -> dict[str, object]:
    if any(
        type(a) is not int or type(b) is not int or a not in (0, 1) or b not in (0, 1)
        for a, b in pairs
    ):
        raise ValueError("校准标签必须是0/1")
    matrix = [[sum(a == i and b == j for a, b in pairs) for j in range(2)] for i in range(2)]
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n if n else None
    chance = (
        sum(sum(matrix[i]) * sum(row[i] for row in matrix) for i in range(2)) / n**2 if n else None
    )
    if n < minimum_pairs and not allow_partial:
        observed, chance = None, None
    return {
        "status": "pending" if n < minimum_pairs else "paired",
        "paired": n,
        "exact_rate": observed,
        "kappa": (observed - chance) / (1 - chance)
        if observed is not None and chance is not None and chance < 1
        else None,
        "confusion": matrix,
        "basis": "actual human labels only; model reference remains uncalibrated until paired",
    }


def human_pairs(rows: list[dict[str, str]], references: dict[str, object]) -> list[tuple[int, int]]:
    pairs = []
    for row in rows:
        if "编号" in row:
            answers = [
                row.get(key, "").strip()
                for key in ("Q1按要求做了吗", "Q2说得清楚不矛盾吗", "Q3知道下一步吗")
            ]
            if row.get("不确定", "").strip() not in ("", "否", "0") or any(
                a not in ("是", "否") for a in answers
            ):
                continue
            identifier, value = row["编号"], int(all(a == "是" for a in answers))
        else:
            if not row.get("human_rater", "").strip() or row.get("human_pass") not in ("0", "1"):
                continue
            identifier, value = row["sample_id"], int(row["human_pass"])
        reference = references.get(identifier)
        model = reference.get("model_reference") if isinstance(reference, dict) else None
        if type(model) is int and model in (0, 1):
            pairs.append((model, value))
    return pairs


def prepare(rows: list[dict[str, object]], directory: Path) -> Path:
    selected = []
    for status in ("passed", "failed"):
        candidates = [
            row
            for row in rows
            if row.get("status") == status and isinstance(row.get("text"), str) and row["text"]
        ]
        if len(candidates) < 15:
            raise ValueError("需要15条通过和15条失败的实际回答，不生成假回答补数")
        selected.extend(candidates[:15])
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / "human-labels.csv"
    references = {}
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "case_id",
                "task",
                "conditions",
                "answer",
                "human_pass",
                "human_rater",
                "notes",
            ],
        )
        writer.writeheader()
        # 固定种子洗牌，可复现但不以奇偶泄露参考标签。
        ordered = selected.copy()
        random.Random(20261013).shuffle(ordered)
        for index, row in enumerate(ordered, 1):
            sample = f"sample-{index:02d}"
            writer.writerow(
                {
                    "sample_id": sample,
                    "case_id": row.get("case_id"),
                    "task": row.get("user_input", ""),
                    "conditions": json.dumps(row.get("conditions", {}), ensure_ascii=False),
                    "answer": row["text"],
                }
            )
            references[sample] = {
                "rule_reference": int(row["status"] == "passed"),
                "model_reference": None,
                "event_summary": row.get("event_summary"),
            }
    (directory / "hidden-reference.json").write_text(
        json.dumps({"seed": 20261013, "references": references}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def score_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("references", type=Path)
    args = parser.parse_args(argv)
    references = json.loads(args.references.read_text(encoding="utf-8"))
    references = references.get("references", references)
    with args.csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    readable = bool(rows and "编号" in rows[0])
    print(
        json.dumps(
            agreement(
                human_pairs(rows, references),
                minimum_pairs=20 if readable else 30,
                allow_partial=not readable,
            ),
            ensure_ascii=False,
        )
    )
    return 0


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
    if sys.argv[1:2] == ["score"]:  # 真人CSV与隐藏参考的一致率（原calibrate_v2）
        return score_main(sys.argv[2:])
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--threshold", type=int, choices=range(1, 6), default=3)
    args = parser.parse_args()
    refuse_live_under_pytest(args.live)
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
