"""有界轨迹分诊：用于生成回归候选，模型标签不作为根因准确率结论。"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from backend.domain.execution import RuntimeEvent
from backend.domain.tool_facts import ChoiceOptionId
from backend.tools.travel import SCHEMAS

type FailureLabel = Literal[
    "wrong_tool",
    "wrong_parameters",
    "ignored_tool_error",
    "constraint_violation",
    "premature_confirmation",
    "hallucinated_id",
    "missing_clarification",
    "repeated_loop",
    "first_error_visible",
    "grader_artifact",
    "simulator_artifact",
    "unknown",
]


class Triage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    first_step: int | None = Field(default=None, strict=True, ge=0)
    label: FailureLabel

    @model_validator(mode="after")
    def identified_step(self) -> "Triage":
        if self.label != "unknown" and self.first_step is None:
            raise ValueError("明确标签需要已观测步骤")
        return self


def choice_options(event: RuntimeEvent) -> list[str]:
    data = event.presentation.get("data") if event.presentation else None
    options = (
        data.get("options")
        if isinstance(data, dict) and data.get("component") == "choice"
        else None
    )
    if not isinstance(options, list):
        return []
    found: list[str] = []
    for option in options[:3]:
        if not isinstance(option, dict):
            continue
        try:
            found.append(TypeAdapter(ChoiceOptionId).validate_python(option.get("option_id")))
        except ValueError:
            continue
    return found


def consistency_check(
    reference: Triage,
    steps: list[dict[str, object]],
    *,
    required_tools: tuple[str, ...] = (),
    forbidden_tools: tuple[str, ...] = (),
) -> Literal["与事件一致", "不一致", "无法判断"]:
    index = reference.first_step
    if index is None or index >= len(steps):
        return "无法判断"
    step = steps[index]
    if reference.label == "wrong_tool":
        if step.get("tool") in required_tools:
            return "不一致"
        if step.get("tool") in forbidden_tools:
            return "与事件一致"
    # 其余标签需要因果或语义证据；发生过错误不证明模型忽略了错误。
    return "无法判断"


CHECK_EXPLANATIONS = {
    "no_unnecessary_tools": "只使用本任务允许的工具，不进行无关查询",
    "memory_exact": "提议偏好的类别、方向、范围和操作与原要求相符",
    "controller_valid": "模拟用户动作与页面已有选项相符",
    "claim_consistency": "回答所述卡片和重试等操作有本轮事件支持",
    "no_reoffer_after_decline": "相同条件和金额的放宽已拒绝后不再展示",
    "saved_items_cover_segments": "保存行程覆盖全部日期和三段住宿",
    "expected_state": "服务端最终状态与场景要求相符",
}


def failed_check_explanations(row: dict[str, object]) -> dict[str, str]:
    checks = row.get("checks")
    return {
        key: explanation
        for key, explanation in CHECK_EXPLANATIONS.items()
        if isinstance(checks, dict) and checks.get(key) is False
    }


def compact_steps(events: tuple[RuntimeEvent, ...]) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for event in events:
        if event.kind not in {"tool_started", "tool_finished", "presentation", "failed"}:
            continue
        steps.append(
            {
                "index": len(steps),
                "kind": event.kind,
                "tool": event.tool_name if event.tool_name in SCHEMAS else None,
                "code": event.code,
                "result_empty": event.result_empty,
                "external": event.external.model_dump(mode="json") if event.external else None,
                "relaxation_cause": event.relaxation_cause,
                "argument_keys": [
                    key
                    for key in event.argument_keys
                    if event.tool_name in SCHEMAS and key in SCHEMAS[event.tool_name].model_fields
                ],
                "arguments": event.arguments.model_dump(mode="json", exclude_none=True)
                if event.arguments
                else None,
                "choice_options": choice_options(event),
            }
        )
        if len(steps) == 40:
            break
    return steps


def validate_triage(response: str, steps: list[dict[str, object]]) -> Triage:
    result = Triage.model_validate_json(response)
    if result.first_step is not None and result.first_step >= len(steps):
        raise ValueError("不能归因到不存在的步骤")
    return result


def check_references(results: Path, references: Path, out: Path) -> Path:
    from eval.publish_v2 import match_triage, read_rows
    from eval.rescore_simulator import verify_originals
    from eval.suites import load_suite

    root = Path(__file__).resolve().parents[1]
    verify_originals(root / ".cache/batch-2026-10-14/f0-original-hashes.json")
    paths = (results, references, results.parent / "manifest.json")
    hashes = {
        str(p.resolve().relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }
    cases, _ = load_suite(root, "v2-memory", "dev")
    mapped = {case.case_id: case for case in cases}
    rows = []
    for row, model in match_triage(read_rows(results), read_rows(references)):
        steps = row.get("process_steps")
        if not isinstance(steps, list):
            steps = []
        reference = model.get("reference")
        parsed = Triage.model_validate(reference) if isinstance(reference, dict) else None
        case = mapped.get(str(row.get("case_id")))
        checked = (
            consistency_check(
                parsed,
                steps,
                required_tools=tuple(case.required_tools) if case else (),
                forbidden_tools=tuple(case.forbidden_tools) if case else (),
            )
            if parsed
            else "无法判断"
        )
        rows.append(
            {
                "case_id": row.get("case_id"),
                "trial": row.get("repeat", row.get("trial")),
                "reference": reference,
                "consistency": checked,
                "failed_check_explanations": failed_check_explanations(row),
            }
        )
    # 来源在检查前后必须未改变；原始F0池也再次校验。
    if any(
        hashlib.sha256((root / name).read_bytes()).hexdigest() != digest
        for name, digest in hashes.items()
    ):
        raise ValueError("检查期间来源变化")
    verify_originals(root / ".cache/batch-2026-10-14/f0-original-hashes.json")
    out.mkdir(parents=True, exist_ok=False)
    target = out / "consistency.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(
            {
                "title": "未核实的分诊线索",
                "rows": rows,
                "source_sha256": hashes,
                "counts": {
                    kind: sum(r["consistency"] == kind for r in rows)
                    for kind in ("与事件一致", "不一致", "无法判断")
                },
                "root_cause_accuracy": None,
                "model_calls": 0,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
    return target


def main() -> int:
    from dotenv import load_dotenv

    from eval.structured import structured_call
    from scripts.dev import configure_environment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--check-references", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.check_references:
        if args.live or args.out is None:
            parser.error("离线检查需要--out且禁止--live")
        print(check_references(args.results, args.check_references, args.out))
        return 0
    rows = [
        json.loads(line)
        for line in args.results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failed = [row for row in rows if row.get("status") == "failed"]
    if not args.live:
        print(json.dumps({"prepared": len(failed), "http_attempts": 0}))
        return 0
    configure_environment()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False)
    target = args.results.parent / "model-triage.jsonl"
    with target.open("x", encoding="utf-8") as output:
        for row in failed:
            steps = row.get("process_steps")
            if not isinstance(steps, list):
                events = TypeAdapter(tuple[RuntimeEvent, ...]).validate_python(row.get("steps", []))
                steps = compact_steps(events)
            try:
                response, report = structured_call(
                    "triage",
                    {
                        "steps": steps,
                        "failed_check_explanations": failed_check_explanations(row),
                        "failed_checks": row.get("failed_checks")
                        or [k for k, v in row.get("checks", {}).items() if v is False],
                    },
                    root,
                )
                reference = validate_triage(response, steps).model_dump(mode="json")
                result = {
                    "case_id": row["case_id"],
                    "trial": row.get("trial")
                    if type(row.get("trial")) is int
                    else row.get("repeat"),
                    "reference": reference,
                    "cost_cny": report.get("run_accounted_cny"),
                    "http_attempts": report.get("http_attempts"),
                    "trace_id": report.get("trace_id"),
                    "human_verified": False,
                    "title": "未核实的分诊线索",
                }
            except ValueError:
                result = {
                    "case_id": row["case_id"],
                    "trial": row.get("trial")
                    if type(row.get("trial")) is int
                    else row.get("repeat"),
                    "reference": None,
                    "human_verified": False,
                }
            output.write(json.dumps(result, ensure_ascii=False) + "\n")
            output.flush()
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
