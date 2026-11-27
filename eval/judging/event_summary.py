"""内容评审只读封闭事件事实；缺失来源保持未知，不采集正文或第三方资料。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.domain.execution import ErrorCode, RuntimeEvent
from backend.domain.external_data import DataMode
from backend.tools.travel import SCHEMAS


class JudgeTool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: str
    code: ErrorCode | None = None
    choice_card: Literal["shown", "none", "declined"] | None = None
    attempts: int | None = Field(default=None, strict=True, ge=0, le=2)
    data_mode: DataMode | None = None

    @field_validator("tool")
    @classmethod
    def known_tool(cls, value: str) -> str:
        if value not in SCHEMAS:
            raise ValueError("评审摘要只接受已注册工具名称")
        return value


class JudgeEvents(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tools: tuple[JudgeTool, ...] = Field(default=(), max_length=40)
    budget_card: bool | None = None
    memory_card: bool | None = None
    truncated: bool = False


def event_summary(events: tuple[RuntimeEvent, ...] | None) -> JudgeEvents:
    if events is None:
        return JudgeEvents()
    tools = [
        JudgeTool(
            tool=event.tool_name,
            code=event.code,
            choice_card=event.choice_card,
            attempts=event.external.attempts if event.external else None,
            data_mode=event.data_mode,
        )
        for event in events
        if event.kind == "tool_finished"
        and event.tool_name in SCHEMAS
        and event.tool_name is not None
    ]
    cards: set[str] = set()
    for event in events:
        if event.kind != "presentation" or not event.presentation:
            continue
        data = event.presentation.get("data")
        if isinstance(data, dict) and data.get("component") == "choice":
            kind = data.get("kind")
            if kind in {"budget_relaxation", "memory_confirm"}:
                cards.add(str(kind))
    return JudgeEvents(
        tools=tuple(tools[:40]),
        truncated=len(tools) > 40,
        budget_card="budget_relaxation" in cards,
        memory_card="memory_confirm" in cards,
    )
