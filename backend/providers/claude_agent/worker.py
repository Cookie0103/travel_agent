"""隔离工作进程的应用入口：同一个 Agent 可续接多轮，正式 CLI 首版只发一轮。"""

import asyncio
import importlib.metadata
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from uuid import UUID, uuid4

from backend.agent.persona import travel_prompt
from backend.agent.runtime import Agent
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity
from backend.providers.claude_agent.runtime import ClaudeRuntime, RuntimeConfig
from backend.tools.search import DEFINITIONS, SearchExecutor


async def run(payload: dict[str, object], cli: Path) -> dict[str, object]:
    prompts = payload.get("prompts")
    if (
        not isinstance(prompts, list)
        or not 1 <= len(prompts) <= 2
        or any(not isinstance(p, str) for p in prompts)
    ):
        return {"status": "error", "code": "validation"}
    context = RunContext(UUID(str(payload["user_id"])), UUID(str(payload["session_id"])))
    identity = RuntimeIdentity(
        "deepseek",
        os.environ["ANTHROPIC_MODEL"],
        importlib.metadata.version("claude-agent-sdk"),
        str(payload["cli_version"]),
    )
    config = RuntimeConfig(identity, cli, Path.cwd(), travel_prompt())
    agent = Agent(ClaudeRuntime(config, DEFINITIONS, SearchExecutor()))
    events: list[RuntimeEvent] = []
    reference_id = None
    results: list[dict[str, object]] = []
    for prompt in prompts:
        context = replace(context, run_id=uuid4())
        result = await agent.run(context, prompt, events.append, reference_id=reference_id)
        results.append(asdict(result))
        if result.outcome.code:
            return {
                "status": "error",
                "code": result.outcome.code,
                "reason": result.outcome.reason,
                "results": results,
                "events": [asdict(e) for e in events],
                "identity": asdict(identity),
            }
        assert result.reference
        reference_id = result.reference.id
    return {
        "status": "success",
        "results": results,
        "events": [asdict(e) for e in events],
        "identity": asdict(identity),
    }


def main() -> None:
    try:
        value: object = json.loads(sys.stdin.read())
        if not isinstance(value, dict):
            raise ValueError("invalid input")
        result = asyncio.run(run({str(k): v for k, v in value.items()}, Path(sys.argv[1])))
    except Exception:
        result = {"status": "error", "code": "provider_error", "reason": "worker_failure"}
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
