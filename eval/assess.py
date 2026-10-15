"""对私有调用事实与独立人工参数答案离线评分；不访问模型，不修改原评测结果。"""

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from backend.domain.execution import RuntimeEvent
from eval.diagnostics import ArgumentFact
from eval.metrics import tool_call_accuracy
from eval.suites import load_suite
from scripts.dev import configure_environment

ROOT = Path(__file__).resolve().parents[1]


def assess(
    events_path: Path,
    actual_path: Path,
    expected_path: Path,
    *,
    suite: Literal["legacy", "frozen"],
    split: Literal["dev", "test"],
    case_id: str,
) -> dict[str, object]:
    cases, metadata = load_suite(ROOT, suite, split)
    matches = [case for case in cases if case.case_id == case_id]
    if len(matches) != 1:
        raise ValueError("案例必须来自原版本化用例集")
    events = TypeAdapter(tuple[RuntimeEvent, ...]).validate_python(
        [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line]
    )
    actual = TypeAdapter(tuple[ArgumentFact, ...]).validate_json(actual_path.read_bytes())
    expected = TypeAdapter(tuple[ArgumentFact, ...]).validate_json(expected_path.read_bytes())
    return {
        "case_id": case_id,
        "evaluation_suite": metadata,
        "tool_call_accuracy": tool_call_accuracy(matches[0], events, actual, expected),
        "expectation_source": "annotations; reviewer must verify independence",
        "limitations": "完整参数答案仅适用于已独立确认调用；"
        "其他合法路径须另给答案，缺证据仍unknown",
    }


def main() -> int:
    configure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True, help="私有events JSONL")
    parser.add_argument("--actual", type=Path, required=True, help="实际ArgumentFact JSON数组")
    parser.add_argument(
        "--expected", type=Path, required=True, help="独立人工ArgumentFact JSON数组"
    )
    parser.add_argument("--suite", choices=["legacy", "frozen"], default="legacy")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--case-id", required=True)
    arguments = parser.parse_args()
    try:
        result = assess(
            arguments.events,
            arguments.actual,
            arguments.expected,
            suite=arguments.suite,
            split=arguments.split,
            case_id=arguments.case_id,
        )
    except (ValueError, ValidationError, OSError):
        print("评分未完成：案例或私有事实附件无效；不输出原文。")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
