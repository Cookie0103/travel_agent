"""隔离工作进程的应用入口：同一个 Agent 可续接多轮，正式 CLI 首版只发一轮。"""

import asyncio
import importlib.metadata
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import TypeAdapter

from backend.agent.persona import JudgeKind, evaluation_judge_prompt, travel_prompt
from backend.agent.runtime import Agent
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeIdentity, event_metadata
from backend.providers.claude_agent.checkpoints import Checkpoints
from backend.providers.claude_agent.database_tools import DatabaseTools, database_tools
from backend.providers.claude_agent.evaluation import (
    EvaluationVariant,
    evaluation_definitions,
    validate_variant,
)
from backend.providers.claude_agent.events import save_event
from backend.providers.claude_agent.limits import Provider
from backend.providers.claude_agent.profile import current
from backend.providers.claude_agent.runtime import ClaudeRuntime, RuntimeConfig
from backend.services.common import ServiceError
from backend.tools.contracts import ToolDefinition, ToolExecutor, repair_rounds
from backend.tools.search import DEFINITIONS, SearchExecutor
from backend.tools.travel import live_definitions, repair_definitions
from backend.tools.workflow import WorkflowName
from backend.trace_log import trace


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
        TypeAdapter(Provider).validate_python(payload.get("provider", "deepseek")),
        os.environ["ANTHROPIC_MODEL"],
        importlib.metadata.version("claude-agent-sdk"),
        str(payload["cli_version"]),
    )
    dsn = payload.get("database_dsn")
    workflow: WorkflowName | None = TypeAdapter(WorkflowName | None).validate_python(
        payload.get("workflow")
    )
    persona_judge = payload.get("persona_judge", False)
    try:
        judge_kind: JudgeKind = TypeAdapter(JudgeKind).validate_python(
            payload.get("judge_kind", "persona")
        )
        variant: EvaluationVariant = TypeAdapter(EvaluationVariant).validate_python(
            payload.get("evaluation_variant", "full")
        )
        validate_variant(
            variant, database=isinstance(dsn, str), workflow=workflow, judge=bool(persona_judge)
        )
    except ValueError:
        return {"status": "error", "code": "validation"}
    if variant != "full" and len(prompts) != 1:
        return {"status": "error", "code": "validation"}
    if (
        (judge_kind != "persona" and not persona_judge)
        or type(persona_judge) is not bool
        or (
            persona_judge
            and (
                identity.provider != "deepseek"
                or dsn
                or workflow
                or payload.get("supplier_url")
                or len(prompts) != 1
            )
        )
    ):
        return {"status": "error", "code": "validation"}
    if persona_judge:
        return await run_prompts(
            prompts,
            context,
            identity,
            cli,
            (),
            SearchExecutor(),
            evaluation_judge_prompt(judge_kind),
        )
    definitions = evaluation_definitions(variant, database=isinstance(dsn, str))
    real_data = payload.get("real_data") is True
    if real_data:
        definitions = live_definitions(definitions)
    if variant == "no_tools":
        return await run_prompts(
            prompts,
            context,
            identity,
            cli,
            definitions,
            SearchExecutor(),
            travel_prompt() + "\n本次纯模型对照没有工具或外部事实，不能声称已查询/校验/保存/预订。",
            max_turns=12,
        )
    if isinstance(dsn, str):
        supplier_url = payload.get("supplier_url")
        async with database_tools(
            dsn, supplier_url if isinstance(supplier_url, str) else None, real_data=real_data
        ) as executor:
            if variant == "no_repairs":
                executor.executor.max_validations = 1
            snapshot, revision, preference_revision = await executor.context_snapshot(
                context, include_preferences=variant not in {"no_preferences", "baseline_b2"}
            )
            rounds = executor.executor.max_validations
            definitions = repair_definitions(definitions, rounds)
            system = travel_prompt(repair_rounds(rounds)) + snapshot
            return await run_prompts(
                prompts,
                context,
                identity,
                cli,
                definitions,
                executor,
                system,
                checkpoints=Checkpoints(Path.cwd())
                if variant == "full" and not real_data
                else None,
                revision=revision,
                preference_revision=preference_revision,
                workflow=workflow,
                disable_auto_compaction=variant in {"no_compaction", "baseline_b2"},
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
    preference_revision: int = 0,
    workflow: WorkflowName | None = None,
    max_turns: int = 6,
    disable_auto_compaction: bool = False,
) -> dict[str, object]:
    config = RuntimeConfig(
        identity,
        cli,
        Path.cwd(),
        system,
        workflow=workflow,
        max_turns=max_turns,
        disable_auto_compaction=disable_auto_compaction,
    )
    if isinstance(executor, DatabaseTools):
        # 完整规划实测需8次工具往返+回答；保留3轮修复空间，HTTP/工具/费用边界不变。
        config = replace(config, max_turns=current().max_turns)
        if executor.travel.live:
            config = replace(
                config, persist_session=False, timeout_seconds=current().worker_timeout
            )
    agent = Agent(ClaudeRuntime(config, definitions, executor))
    events: list[RuntimeEvent] = []

    def emit(event: RuntimeEvent) -> None:
        transient = isinstance(executor, DatabaseTools) and executor.travel.live is not None
        save_event(
            Path.cwd() / f"events-{event.context.run_id}.jsonl",
            event_metadata(event) if transient else event,
        )
        events.append(event)

    reference_id = None
    resumed = (
        checkpoints.load(context, identity, revision, preference_revision=preference_revision)
        if checkpoints
        else None
    )
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
            if isinstance(executor, DatabaseTools):
                snapshot, current_revision, current_preferences = await executor.context_snapshot(
                    context
                )
                if (revision, preference_revision) != (current_revision, current_preferences):
                    reference_id = None
                revision, preference_revision = current_revision, current_preferences
                # 每个用户轮次重新注入事实并建立独立工具限额；SDK负责旧消息和压缩。
                executor = DatabaseTools(
                    executor.loop, executor.travel.database, executor.supplier_url
                )
                agent.runtime = ClaudeRuntime(
                    replace(
                        config,
                        system_prompt=travel_prompt(
                            repair_rounds(executor.executor.max_validations)
                        )
                        + snapshot,
                    ),
                    definitions,
                    executor,
                )
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
        if not isinstance(executor, DatabaseTools) or await executor.revisions(context) == (
            revision,
            preference_revision,
        ):
            persisted = checkpoints.save(
                result.reference, revision, preference_revision=preference_revision
            )
    return {
        "status": "success",
        "results": results,
        "events": [asdict(e) for e in events],
        "identity": asdict(identity),
        "resume_mode": "sdk" if resumed else "business_snapshot",
        "checkpoint_persisted": persisted,
    }


def main() -> None:
    trace("worker_start")
    try:
        value: object = json.loads(sys.stdin.read())
        if not isinstance(value, dict):
            raise ValueError("invalid input")
        result = asyncio.run(run({str(k): v for k, v in value.items()}, Path(sys.argv[1])))
    except ServiceError as error:
        result = {"status": "error", "code": error.code, "reason": "business_snapshot_unavailable"}
    except Exception:
        result = {"status": "error", "code": "provider_error", "reason": "worker_failure"}
    trace("worker_end", status=result.get("status"), code=result.get("code"))
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
