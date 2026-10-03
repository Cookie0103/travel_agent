"""应用执行的数据契约；业务身份和事件不依赖 SDK 消息或会话文件。"""

from dataclasses import dataclass, field
from typing import Literal
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
    "completed",
    "failed",
    "cancelled",
]


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
