"""工具契约的唯一来源；MCP 只注册此定义，业务执行入口不依赖 SDK。"""

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import ValidationError

from backend.domain.execution import ErrorCode, RunContext

RESULT_LIMIT = 8000
# present_travel_result的整个展示就是工具结果：5-6张带停留条件/链接/地址/坐标/证据的酒店卡
# 约2.9k字/张(5张约14k，6张约17k；脱敏样本实测5张11.7k/6张13.9k)。按8000会让首次展示必被拒；
# 24000留约40%余量，其余工具仍用RESULT_LIMIT。
PRESENTATION_RESULT_LIMIT = 24000


DEFAULT_REPAIR_ROUNDS = 3  # 静态文本的基准修复轮数(=DEFAULT/RELAXED的max_validations-1)


def repair_rounds(max_validations: int) -> int:
    """模型可见的修复轮数=首次校验之外的轮数；评测单因素(1)另有专门文案，仍按基准。"""
    if max_validations > DEFAULT_REPAIR_ROUNDS + 1:
        return max_validations - 1
    return DEFAULT_REPAIR_ROUNDS


def with_repair_rounds(text: str, max_validations: int) -> str:
    """把静态文本里的“最多修复3轮”换成当前档位的实际轮数；基准档位字节不变。"""
    return text.replace(
        f"最多修复{DEFAULT_REPAIR_ROUNDS}轮", f"最多修复{repair_rounds(max_validations)}轮"
    )


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    schema: dict[str, object]
    kind: Literal["read", "state", "draft", "presentation", "side_effect"] = "read"
    timeout_seconds: float = 5
    max_result_chars: int = RESULT_LIMIT


def validation_paths(error: ValidationError, limit: int = 6) -> tuple[str, ...]:
    """pydantic错误 -> 'loc.path:error_type'；不含输入值和消息；extra字段名不原样记录。"""
    paths: list[str] = []
    for item in error.errors(include_input=False, include_context=False, include_url=False):
        loc = [str(part) for part in item["loc"]]
        if item["type"] == "extra_forbidden" and loc:
            loc[-1] = "<extra>"
        paths.append((".".join(loc) + ":" + item["type"])[:60])
        if len(paths) == limit:
            break
    return tuple(paths)


@dataclass(frozen=True)
class ToolResult:
    data: dict[str, object]
    code: ErrorCode | None = None
    empty: bool = False
    data_mode: Literal["fixture", "snapshot", "live"] = "fixture"
    evidence_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    suggestion: str = ""
    detail: tuple[str, ...] = ()  # 仅供TRACE的脱敏诊断标签，不进入payload/模型

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
