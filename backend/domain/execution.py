"""应用执行的数据契约；业务身份和事件不依赖 SDK 消息或会话文件。"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, cast, get_args
from uuid import UUID, uuid4

type ErrorCode = Literal[
    "validation",
    "blocked",
    "unavailable",
    "timeout",
    "rate_limited",
    "provider_error",
    "conflict",
    "cancelled",
]
type EventKind = Literal[
    "started",
    "text",
    "tool_started",
    "tool_finished",
    "presentation",
    "context_compacted",
    "completed",
    "failed",
    "cancelled",
    "partial",
    "awaiting_user",
]


def error_code(value: object) -> ErrorCode:
    """外部错误只接受已定义的应用码，未知值统一归provider_error。"""
    return (
        cast(ErrorCode, value)
        if isinstance(value, str) and value in get_args(ErrorCode.__value__)
        else "provider_error"
    )


@dataclass(frozen=True)
class RunContext:
    """由服务端生成的业务 ID；不能把 SDK session_id 当成用户身份。"""

    user_id: UUID
    session_id: UUID = field(default_factory=uuid4)
    run_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class RuntimeIdentity:
    provider: str
    model: str
    sdk_version: str
    cli_version: str


@dataclass(frozen=True)
class SessionReference:
    context: RunContext
    identity: RuntimeIdentity
    sdk_session_id: str
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class RuntimeEvent:
    """前端/CLI 所需的最小事件；text 是用户输出，不进入公共 Trace。"""

    context: RunContext
    kind: EventKind
    text: str = ""
    tool_name: str | None = None
    code: ErrorCode | None = None
    tool_call_id: UUID | None = None
    argument_keys: tuple[str, ...] = ()
    result_empty: bool | None = None
    presentation: dict[str, object] | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    request_revision: int | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeOutcome:
    text: str = ""
    sdk_session_id: str | None = None
    code: ErrorCode | None = None
    reason: str = "completed"


@dataclass(frozen=True)
class RunResult:
    context: RunContext
    outcome: RuntimeOutcome
    reference: SessionReference | None = None


def terminal_event(context: RunContext, outcome: RuntimeOutcome) -> RuntimeEvent:
    kind: EventKind = (
        "completed"
        if outcome.code is None
        else "cancelled"
        if outcome.code == "cancelled"
        else "failed"
    )
    return RuntimeEvent(context, kind, code=outcome.code)


def event_metadata(event: RuntimeEvent) -> RuntimeEvent:
    """实时第三方内容只用于当前响应；持久事件保留步骤与业务引用。"""
    from dataclasses import replace

    presentation: dict[str, object] | None = None
    if event.presentation is not None:
        data = event.presentation.get("data")
        if isinstance(data, dict):
            # 乐天报价是本人会话私有证据；Google行程卡只保留按需补卡的业务引用。
            safe = (
                data
                if data.get("component") == "hotel_comparison"
                else {
                    key: value
                    for key, value in data.items()
                    if key in {"component", "draft_id", "plan_id", "offer_ids", "expected_revision"}
                }
            )
            presentation = {"data": safe}
    return replace(event, text="", presentation=presentation)
