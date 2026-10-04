"""工具契约的唯一来源；MCP 只注册此定义，业务执行入口不依赖 SDK。"""

from dataclasses import dataclass
from typing import Literal, Protocol

from backend.domain.execution import ErrorCode, RunContext

RESULT_LIMIT = 8000


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    schema: dict[str, object]
    kind: Literal["read", "state", "draft", "presentation", "side_effect"] = "read"
    timeout_seconds: float = 5
    max_result_chars: int = RESULT_LIMIT


@dataclass(frozen=True)
class ToolResult:
    data: dict[str, object]
    code: ErrorCode | None = None
    empty: bool = False
    data_mode: Literal["fixture", "snapshot", "live"] = "fixture"
    evidence_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    suggestion: str = ""

    def payload(self) -> dict[str, object]:
        """正文状态是工具契约的一部分，兼容忽略 MCP is_error 的模型。"""
        return {
            "status": "error" if self.code else "empty" if self.empty else "ok",
            "data": self.data,
            "evidence_ids": list(self.evidence_ids),
            "data_mode": self.data_mode,
            "warnings": list(self.warnings),
            "error": {"code": self.code, "suggestion": self.suggestion} if self.code else None,
        }


class ToolExecutor(Protocol):
    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult: ...
