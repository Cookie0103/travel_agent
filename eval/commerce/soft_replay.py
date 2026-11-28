"""给已保存的商业结果补算通过体检的软性条目。"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from backend.adapters.decision_model import DecisionClient
from eval.commerce.parameters import Registry, load_parameters
from eval.commerce.score import rescore
from eval.commerce.soft import score_saved


async def supplement(
    row: dict[str, Any],
    accepted: frozenset[str],
    client: DecisionClient,
    scale: float,
    parameters: Registry | None,
) -> dict[str, Any]:
    sheet = row.get("commerce")
    inputs = row.get("soft_facts")
    if not isinstance(sheet, dict) or not sheet.get("passed") or not isinstance(inputs, dict):
        return row
    values = {}
    for hotel_id, state in inputs.items():
        if isinstance(state, dict):
            probabilities = await score_saved(
                state, accepted, client, rule_passed=True, scale=scale
            )
            if probabilities:
                values[hotel_id] = probabilities
    return {
        **row,
        "commerce_soft": {
            "model": client.model,
            "revision": client.revision,
            "temperature": scale,
            "parameter_version": parameters.version if parameters else None,
            "expected_score_jpy": rescore(sheet, parameters, soft=values)
            if values and parameters
            else None,
            "by_hotel": values,
            "state": "observed" if values else "unavailable",
        },
    }


async def run(args: argparse.Namespace) -> int:
    evidence = json.loads(args.health.read_text(encoding="utf-8"))
    approved = frozenset(item["item"] for item in evidence["items"] if item["passed"])
    client = DecisionClient(args.endpoint, evidence["model"], evidence["revision"], args.cache)
    scale = evidence.get("probability_temperature") or 1.0
    parameters = load_parameters(args.parameters) if args.parameters else None
    if args.input.resolve() == args.out.resolve():
        raise ValueError("软性补算须写入单独的结果文件")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.input.open(encoding="utf-8") as source, args.out.open("x", encoding="utf-8") as out:
        for line in source:
            if line.strip():
                record = await supplement(json.loads(line), approved, client, scale, parameters)
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--health", required=True, type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--parameters", type=Path)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
