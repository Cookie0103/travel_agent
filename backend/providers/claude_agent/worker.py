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
from backend.providers.claude_agent.checkpoints import Checkpoints
from backend.providers.claude_agent.database_tools import DatabaseTools, database_tools
from backend.providers.claude_agent.events import save_event
from backend.providers.claude_agent.runtime import ClaudeRuntime, RuntimeConfig
from backend.tools.contracts import ToolDefinition, ToolExecutor
from backend.tools.search import DEFINITIONS, SearchExecutor
from backend.tools.travel import DEFINITIONS as TRAVEL_DEFINITIONS


async def run(payload: dict[str, object], cli: Path) -> dict[str, object]:
    prompts = payload.get("prompts")
    if (
        not isinstance(prompts, list)
        or not 1 <= len(prompts) <= 2
        or any(not isinstance(p, str) for p in prompts)
    ):
        return {"status": "error", "code": "validation"}
    context = RunContext(
        UUID(str(payload["user_id"])),
        UUID(str(payload["session_id"])),
        UUID(str(payload.get("run_id", uuid4()))),
    )
    identity = RuntimeIdentity(
        "deepseek",
        os.environ["ANTHROPIC_MODEL"],
        importlib.metadata.version("claude-agent-sdk"),
        str(payload["cli_version"]),
    )
    dsn = payload.get("database_dsn")
    if isinstance(dsn, str):
        supplier_url = payload.get("supplier_url")
        async with database_tools(
            dsn, supplier_url if isinstance(supplier_url, str) else None
        ) as executor:
            snapshot, revision = await executor.context_snapshot(context)
            system = travel_prompt() + snapshot
            return await run_prompts(
                prompts,
                context,
                identity,
                cli,
                TRAVEL_DEFINITIONS,
                executor,
                system,
                checkpoints=Checkpoints(Path.cwd()),
                revision=revision,
            )
    return await run_prompts(
        prompts, context, identity, cli, DEFINITIONS, SearchExecutor(), travel_prompt()
    )


async def run_prompts(
    prompts: list[object],
    context: RunContext,
    identity: RuntimeIdentity,
    cli: Path,
    definitions: tuple[ToolDefinition, ...],
    executor: ToolExecutor,
    system: str,
    *,
    checkpoints: Checkpoints | None = None,
    revision: int = 0,
) -> dict[str, object]:
    config = RuntimeConfig(identity, cli, Path.cwd(), system)
    agent = Agent(ClaudeRuntime(config, definitions, executor))
    events: list[RuntimeEvent] = []

    def emit(event: RuntimeEvent) -> None:
        save_event(Path.cwd() / f"events-{event.context.run_id}.jsonl", event)
        events.append(event)

    reference_id = None
    resumed = checkpoints.load(context, identity, revision) if checkpoints else None
    if resumed is not None:
        agent.restore(resumed)
        reference_id = resumed.id
    if checkpoints:
        checkpoints.invalidate()
    results: list[dict[str, object]] = []
    for index, prompt in enumerate(prompts):
        assert isinstance(prompt, str)
        if index:
            context = replace(context, run_id=uuid4())
        result = await agent.run(context, prompt, emit, reference_id=reference_id)
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
    persisted = False
    if checkpoints and result.reference:
        if not isinstance(executor, DatabaseTools) or await executor.revision(context) == revision:
            persisted = checkpoints.save(result.reference, revision)
    return {
        "status": "success",
        "results": results,
        "events": [asdict(e) for e in events],
        "identity": asdict(identity),
        "resume_mode": "sdk" if resumed else "business_snapshot",
        "checkpoint_persisted": persisted,
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
