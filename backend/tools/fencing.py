"""第三方自由文本进入模型前的围栏：仅处理白名单字段，标识符/数值/服务端文案保持原样。"""

import re
import unicodedata

from backend.tools.contracts import RESULT_LIMIT

LABEL = "untrusted_text"
FIELD_LIMIT = RESULT_LIMIT // 4
# 第三方自由文本字段；只在 data 下的集合行中匹配，服务端文案（warnings/suggestion/skill）不在其中。
TEXT_FIELDS = frozenset(
    {"name", "title", "text", "aliases", "tags", "hotel_name", "room_type", "attribution"}
    | {"address", "description", "snippet", "summary", "review", "reviews"}
)
_INVISIBLE = re.compile("[­​-‏ -‮⁠-⁩︀-️﻿]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# 任何形态的围栏标签或角色/工具标记（含空格、属性、未闭合）。
_MARKER = re.compile(
    rf"<[ \t]*/?[ \t]*(?:{LABEL}|system|human|user|assistant|function_calls|invoke|tool_use"
    r"|tool_result)(?![A-Za-z0-9_])(?:[^<>]{0,200}>)?|<\|[^|<>\r\n]{1,64}\|>",
    re.IGNORECASE,
)
_TURN = re.compile(r"(\n[ \t]*\n[ \t]*)(human|assistant|system|user)[ \t]*:", re.IGNORECASE)


def sanitize(text: str, limit: int = FIELD_LIMIT) -> str:
    text = _CONTROL.sub(" ", _INVISIBLE.sub("", unicodedata.normalize("NFKC", text)))
    while (stripped := _MARKER.sub("[removed]", text)) != text:  # 到不动点，防嵌套重组
        text = stripped
    text = _TURN.sub(r"\1\2 -", text)
    return text if len(text) <= limit else text[: limit - 15] + " ...[truncated]"


def fence(text: str) -> str:
    return f"<{LABEL}>{sanitize(text)}</{LABEL}>"


def _value(value: object) -> object:
    if isinstance(value, str):
        return fence(value)
    if isinstance(value, list):
        return [fence(item) if isinstance(item, str) else item for item in value]
    return value


def fence_payload(payload: dict[str, object]) -> dict[str, object]:
    """返回副本：data 集合行内的白名单文本字段被围栏；其余字段原样。"""
    data = payload.get("data")
    if not isinstance(data, dict):
        return payload
    fenced: dict[str, object] = {}
    for key, rows in data.items():
        fenced[key] = (
            [
                {k: _value(v) if k in TEXT_FIELDS else v for k, v in row.items()}
                if isinstance(row, dict)
                else row
                for row in rows
            ]
            if isinstance(rows, list)
            else rows
        )
    return {**payload, "data": fenced}
