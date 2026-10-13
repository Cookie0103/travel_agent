"""有界轨迹分诊：用于生成回归候选，模型标签不作为根因准确率结论。"""

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from backend.domain.execution import RuntimeEvent
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


def main() -> int:
    from dotenv import load_dotenv

    from eval.structured import structured_call
    from scripts.dev import configure_environment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
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
