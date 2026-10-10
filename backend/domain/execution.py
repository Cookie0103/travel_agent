"""应用执行的数据契约；业务身份和事件不依赖 SDK 消息或会话文件。"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal, cast, get_args
from uuid import UUID, uuid4

from pydantic import Field

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
type ToolReason = Literal[
    "tool_call_cap",
    "repair_limit",
    "repeat_blocked",
    "result_too_long",
    "unregistered_tool",
    "context_reuse",
    "evidence_missing",
    "offer_unknown_id",
    "not_found",
    "live_hold_disabled",
    "plan_exists",
    "patch_invalid",
    "revision_stale",
    "lodging_budget_conflict",
    "hotel_search_location_required",
    "hotel_missing_fields",
    "hotel_room_preferences_missing",
    "hotel_external_validation",
    "hotel_external_unavailable",
    "hotel_api_unconfigured",
    "schema",
    "other",
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


_ID_LABEL = re.compile(
    r"[ \t]*\b(?:offer_id|evidence_id|draft_id|plan_id|evidence)\b[ \t]*[:=：]?[ \t]*"
    r"(?=[0-9a-fA-F-]*\d)[0-9a-fA-F][0-9a-fA-F-]{5,35}(?![0-9A-Za-z_])"
    r"(?:…|\.{3})?(?:[ \t]*[，,、；;][ \t]*)?"
)
_UUID = re.compile(
    r"(?<![0-9A-Za-z])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"(?![0-9A-Za-z])"
)
_EMPTY_BRACKETS = re.compile(r"[（(][ \t，,、；;]*[）)]")
_EDGE_SEPARATORS = re.compile(r"(?<=[（(])[ \t]*[，,、；;][ \t]*|[ \t]*[，,、；;][ \t]*(?=[）)])")


def scrub_internal_ids(text: str) -> str:
    """最终回复的兜底：仅删除带标签的内部编号与36位UUID，其余文本原样保留；幂等。"""
    if not text:
        return text
    cleaned = _UUID.sub("", _ID_LABEL.sub("", text))
    if cleaned == text:
        return text
    return _EMPTY_BRACKETS.sub("", _EDGE_SEPARATORS.sub("", cleaned))


def error_code(value: object) -> ErrorCode:
    """外部错误只接受已定义的应用码，未知值统一归provider_error。"""
    return (
        cast(ErrorCode, value)
        if isinstance(value, str) and value in get_args(ErrorCode.__value__)
        else "provider_error"
    )


def tool_reason(code: ErrorCode | None, detail: tuple[str, ...]) -> ToolReason | None:
    """ToolResult.detail -> 封闭原因码；成功为None，未知标签统一为other，绝不透传自由文本。"""
    if code is None:
        return None
    allowed = get_args(ToolReason.__value__)
    for value in detail:
        if value in allowed and value != "other":
            return cast(ToolReason, value)
    return "not_found" if "service:404" in detail else "other"


UPSTREAM_REASON = "upstream_http_"  # RuntimeOutcome.reason前缀，后接三位HTTP状态码


def upstream_error_text(reason: str) -> str | None:
    """上游HTTP错误 -> 固定中文说明；只依据状态码，绝不包含上游响应正文、头或密钥。"""
    digits = reason.removeprefix(UPSTREAM_REASON)
    if not reason.startswith(UPSTREAM_REASON) or not (digits.isascii() and digits.isdigit()):
        return None
    status = int(digits)
    if not 100 <= status <= 599:
        return None
    explanation = {
        400: "请求被拒绝",
        401: "密钥无效或无权限，请检查 API Key",
        402: "账户余额不足，请充值后重试",
        403: "密钥无效或无权限，请检查 API Key",
        429: "请求过于频繁或速率受限，请稍后重试",
    }.get(status)
    if explanation is None and status >= 500:
        explanation = "服务暂时不可用，请稍后重试"
    return f"DeepSeek 返回 {status}：{explanation}" if explanation else f"上游返回 HTTP {status}"


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


type BusinessKind = Literal["answer_only", "draft_staged", "stage_failed", "confirmed"]
type StageReason = Literal["plan_exists", "patch_invalid", "repair_limit", "other"]


@dataclass(frozen=True)
class BusinessResult:
    """Small server facts; never derive a business commit from runtime text."""

    kind: BusinessKind
    draft_id: UUID | None = None
    plan_id: UUID | None = None
    validation_status: Literal["complete", "partial", "conflict"] | None = None
    code: ErrorCode | None = None
    reason: StageReason | None = None
    version: Annotated[int, Field(strict=True, ge=1)] | None = None

    def __post_init__(self) -> None:
        required = {
            "answer_only": set(),
            "draft_staged": {"draft_id", "plan_id", "validation_status"},
            "stage_failed": {"code", "reason"},
            "confirmed": {"plan_id", "version"},
        }
        actual = {
            name
            for name in ("draft_id", "plan_id", "validation_status", "code", "reason", "version")
            if getattr(self, name) is not None
        }
        if actual != required.get(self.kind) or (
            self.version is not None and (type(self.version) is not int or self.version < 1)
        ):
            raise ValueError("业务结果字段不匹配")


@dataclass(frozen=True)
class RuntimeEvent:
    """前端/CLI 所需的最小事件；text 是用户输出，不进入公共 Trace。"""

    context: RunContext
    kind: EventKind
    text: str = ""
    tool_name: str | None = None
    code: ErrorCode | None = None
    reason: ToolReason | None = None  # 仅tool_finished失败时设置；封闭码，不含自由文本
    tool_call_id: UUID | None = None
    argument_keys: tuple[str, ...] = ()
    result_empty: bool | None = None
    presentation: dict[str, object] | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    request_revision: int | None = None
    evidence_ids: tuple[str, ...] = ()
    business_result: BusinessResult | None = None


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
