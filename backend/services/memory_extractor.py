"""run完成后的异步记忆抽取：只读用户原话与助手最终文本，提议仍走MemoryService校验与确认卡。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.memory import MemoryOperation, MemoryProposal
from backend.domain.tool_facts import argument_facts
from backend.limits import ProbeError
from backend.persistence import memory, runs, sessions
from backend.persistence.database import Database
from backend.services.common import ServiceError, transaction
from backend.services.memory import MemoryService, extraction_runs

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
TOOL_NAME = runs.MEMORY_EXTRACTOR  # 事件/诊断里的来源名；不是模型可调用的工具

type ExtractorCall = Callable[[dict[str, object]], Awaitable[str]]


class ExtractorOutput(BaseModel):
    """模型原始输出；逐条校验，一条不合法不连累其他条。"""

    model_config = ConfigDict(extra="ignore")
    ops: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=5)


@dataclass(frozen=True)
class Extraction:
    events: tuple[RuntimeEvent, ...] = ()
    invalid: int = 0
    proposed: int = 0
    deferred: int = 0
    skipped: str | None = None
    cards: tuple[dict[str, object], ...] = ()


async def deepseek_call(payload: dict[str, object]) -> str:
    """生产默认：ADR-011同一无工具SDK路径(固定温度DeepSeek)，阻塞调用放线程里。"""
    from backend.providers.claude_agent.structured import structured_call

    text, _ = await asyncio.to_thread(structured_call, "memory", payload, ROOT)
    return text


class MemoryExtractor:
    def __init__(self, database: Database, call: ExtractorCall = deepseek_call) -> None:
        self.database, self.call = database, call

    async def transcript(self, context: RunContext) -> dict[str, object] | None:
        """最近几轮(旧→新)的user_text与助手最终回复；绝不含工具结果。"""
        async with transaction(self.database) as db:
            source = await runs.owned(db, context.user_id, context.run_id)
            user = await sessions.get_user(db, context.user_id)
            if (
                source is None
                or user is None
                or source.session_id != context.session_id
                or source.status != "completed"
            ):
                return None
            turns = await extraction_runs(db, source, user.memory_forgotten_at)
            if not turns or turns[-1].id != source.id:
                return None  # 来源轮是卡片确认或早于遗忘边界：不抽取
            facts = memory.bounded_snapshot(
                await memory.active(db, context.user_id, context.session_id)
            )
        return {
            "turns": [{"user": row.user_text, "assistant": row.answer[:2000]} for row in turns],
            "active_memory": facts,
        }

    async def extract(self, context: RunContext) -> Extraction:
        payload = await self.transcript(context)
        if payload is None:
            return Extraction(skipped="no_source")
        try:
            output = ExtractorOutput.model_validate_json(await self.call(payload))
        except (ProbeError, ValueError, ValidationError):
            LOGGER.warning("memory extraction unavailable: %s", context.run_id)
            return Extraction(skipped="model_unavailable")
        service = MemoryService(self.database)
        cards: list[dict[str, object]] = []
        accepted: list[dict[str, object]] = []
        invalid = deferred = 0
        for raw in output.ops:
            try:
                operation = MemoryOperation.model_validate(raw)
                shown, later = await service.propose_with_deferred(
                    context, MemoryProposal(ops=(operation,)), extracted=True
                )
            except (ValidationError, ServiceError):
                invalid += 1
                continue
            cards.extend(shown)
            deferred += later
            accepted.append(operation.model_dump(mode="json", include={"key", "scope", "op"}))
        call_id = uuid4()
        events = [
            RuntimeEvent(
                context,
                "tool_finished",
                tool_name=TOOL_NAME,
                tool_call_id=call_id,
                result_empty=not cards and not deferred,
                arguments=argument_facts(TOOL_NAME, {"ops": accepted}),
            ),
            # 每条被拒提议记一次失败，与原工具逐次失败计数口径一致(评测invalid_attempts)。
            *(
                RuntimeEvent(context, "tool_finished", tool_name=TOOL_NAME, code="validation")
                for _ in range(invalid)
            ),
            *(
                RuntimeEvent(
                    context,
                    "presentation",
                    tool_name=TOOL_NAME,
                    tool_call_id=call_id,
                    presentation={"status": "ok", "data": {"component": "choice", **card}},
                )
                for card in cards
            ),
        ]
        return Extraction(tuple(events), invalid, len(accepted), deferred, cards=tuple(cards))
