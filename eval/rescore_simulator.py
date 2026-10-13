"""补强后的同批统一重算；只读原始回答/事件，不再调用模型。"""

import argparse
import json
from decimal import Decimal
from pathlib import Path

from pydantic import TypeAdapter

from backend.domain.execution import RuntimeEvent
from eval.report import reliability
from eval.simulator import hotel_delivered, recalled

ROOT = Path(__file__).resolve().parents[1]


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
            path = (
                ROOT
                / ".cache"
                / "sessions"
                / str(context.user_id)
                / str(context.session_id)
                / f"events-{context.run_id}.jsonl"
            )
            matches = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            matched = [
                event
                for event in matches
                if event.get("kind") == item.get("kind")
                and event.get("tool_call_id") == item.get("tool_call_id")
                and event.get("context") == item.get("context")
            ]
            if len(matched) != 1 or not isinstance(matched[0].get("external"), dict):
                raise ValueError("原始外部调用观察无法唯一恢复，保持未知")
            item["external"] = matched[0]["external"]
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
    return {
        **row,
        "checks": checks,
        "repeat": row.get("trial"),
        "steps": TypeAdapter(tuple[RuntimeEvent, ...]).dump_python(events, mode="json"),
        "status": "passed" if all(checks.values()) else "failed",
        "rescore_basis": "all original trials; hotel delivery/recovery; "
        "denial-aware recall; no model rerun",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    rows = [
        rescore(json.loads(line)) for line in args.results.read_text(encoding="utf-8").splitlines()
    ]
    target = args.results.parent / "rescored-results.jsonl"
    with target.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    summary = {
        "n": len(rows),
        "passed": sum(r["status"] == "passed" for r in rows),
        "cost_cny": str(sum((Decimal(str(r["cost_cny"])) for r in rows), Decimal(0))),
        "reliability": reliability(rows, 3),
        "scope": "same raw trials, model and conditions; revised scorer; uncalibrated semantics",
    }
    (args.results.parent / "rescored-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(target)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
