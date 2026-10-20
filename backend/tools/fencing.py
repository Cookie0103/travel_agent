"""第三方自由文本进入模型前的围栏：data 里的字符串默认围栏，只豁免已知的结构化字段。"""

import re
import unicodedata

from backend.tools.contracts import RESULT_LIMIT

LABEL = "untrusted_text"
FIELD_LIMIT = RESULT_LIMIT // 4
# 默认围栏；以下是豁免。模型要原样回传给工具的值（ID、枚举、字段名）不能被围栏改写。
# 结构化键的值还必须是纯ASCII标识（无空白/尖括号），否则照样围栏：被污染的“枚举”不会因键名而逃脱。
STRUCTURED_KEYS = frozenset(
    {"id", "status", "evidence_status", "data_mode", "coordinate_kind", "provider", "license"}
    | {"op", "kind", "component", "currency", "transport", "confidence", "fare_scope", "code"}
    | {"subject", "cause", "choice_card", "goals", "awaiting_field", "lodging", "smoking", "bed"}
    | {"trip_ask_card"}
    | {"field_sources", "pending_tasks", "ready_tasks", "missing_fields"}
)
STRUCTURED_SUFFIXES = (
    "_id", "_ids", "_ref", "_version", "_at", "_fields", "_field", "_amount", "_date",
)  # fmt: skip
# 服务端撰写的文案（非第三方来源），围栏会让模型把规则当成不可信文本。
SERVER_TEXT_KEYS = frozenset(
    {"message", "guidance", "scope", "instructions", "reasons", "presented", "count_basis"}
)
# 整个返回都是仓库内静态文本的工具。
SERVER_OWNED_TOOLS = frozenset({"load_skill"})
# 枚举类键：值必须像枚举（≤32字符、至多3个单词），长句/指令即使是纯ASCII也围栏。
ENUM_KEYS = frozenset(
    {"status", "evidence_status", "data_mode", "coordinate_kind", "provider", "license"}
    | {"op", "kind", "component", "currency", "transport", "confidence", "fare_scope", "cause"}
    | {"choice_card", "lodging", "smoking", "bed", "trip_ask_card"}
)
URL_KEYS = frozenset({"url", "source_ref"})
_TOKEN = re.compile(r"[A-Za-z0-9_.:/+\-]{1,64}")
_ENUM = re.compile(r"(?=.{1,32}\Z)[A-Za-z0-9]+(?:[_.:\-][A-Za-z0-9]+){0,2}")
_URL = re.compile(r"https?://[^\s<>\"'`\\]{1,300}")
# 内容版本：十六进制摘要 + 可选的短后缀（如 "<sha256>:curation-v1"，共76字符，超过通用标识符上限）。
_VERSION = re.compile(r"[0-9a-fA-F]{16,64}(?::[A-Za-z0-9._\-]{1,32})?")
_SAFE_KEY = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
# 与键无关的结构化值：UUID、ISO日期/时间、数字。
_PLAIN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
    r"|-?\d+(?:\.\d+)?"
)
# 零宽/方向控制/软连字符/变体选择符/标签字符/填充字符等不可见码点（ZWJ U+200D 本就在内，保持）。
_INVISIBLE = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u2028-\u202e"
    "\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff9-\ufffb"
    "\U000e0000-\U000e007f\U000e0100-\U000e01ef]"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# 任何形态的围栏标签或角色/工具标记（含空格、属性、未闭合）。
_MARKER = re.compile(
    rf"<[ \t]*/?[ \t]*(?:{LABEL}|system|human|user|assistant|function_calls|invoke|tool_use"
    r"|tool_result)(?![A-Za-z0-9_])(?:[^<>]{0,200}>)?|<\|[^|<>\r\n]{1,64}\|>",
    re.IGNORECASE,
)
_TURN = re.compile(r"(\n[ \t]*\n[ \t]*)(human|assistant|system|user)[ \t]*:", re.IGNORECASE)
_OWN_FENCE = re.compile(rf"(<{LABEL}>(?:(?!{LABEL}).)*</{LABEL}>)", re.DOTALL)


def sanitize(text: str, limit: int = FIELD_LIMIT) -> str:
    text = _CONTROL.sub(" ", _INVISIBLE.sub("", unicodedata.normalize("NFKC", text)))
    while (stripped := _MARKER.sub("[removed]", text)) != text:  # 到不动点，防嵌套重组
        text = stripped
    text = _TURN.sub(r"\1\2 -", text)
    return text if len(text) <= limit else text[: limit - 15] + " ...[truncated]"


def fence(text: str) -> str:
    return f"<{LABEL}>{sanitize(text)}</{LABEL}>"


_FENCE_TAG = re.compile(rf"</?{LABEL}>")


def unfence(text: str) -> str:
    """用户可见边界：去掉本模块生成的围栏标签、保留内容。只用于展示给用户的文本，
    不得用于模型可见的工具结果（那里围栏是安全边界）。"""
    return _FENCE_TAG.sub("", text)


def _server_text(text: str) -> str:
    """服务端文案：保持可读（不做NFKC），但去掉不可见/控制字符与可破坏围栏的标记；
    构造处已围栏的动态片段（由 fence() 生成的完整围栏）原样保留。"""
    out = []
    for part in _OWN_FENCE.split(text):
        if _OWN_FENCE.fullmatch(part):
            out.append(part)
            continue
        part = _CONTROL.sub(" ", _INVISIBLE.sub("", part))
        if _MARKER.search(unicodedata.normalize("NFKC", part)):
            part = sanitize(part, len(part) + 1)
        out.append(part)
    joined = "".join(out)
    return joined if len(joined) <= FIELD_LIMIT else joined[: FIELD_LIMIT - 15] + " ...[truncated]"


def _exempt(key: str, value: str, structured: bool) -> bool:
    if _PLAIN.fullmatch(value):
        return True
    if key in URL_KEYS or key.endswith(("_url", "_ref")):
        if value.isascii() and _URL.fullmatch(value):
            return True
    if key.endswith("_version") and _VERSION.fullmatch(value):
        return True
    if key in ENUM_KEYS:
        return bool(_ENUM.fullmatch(value))
    return (structured or key in STRUCTURED_KEYS or key.endswith(STRUCTURED_SUFFIXES)) and bool(
        _TOKEN.fullmatch(value)
    )


def _walk(key: str, value: object, structured: bool) -> object:
    if isinstance(value, str):
        if key in SERVER_TEXT_KEYS:
            return _server_text(value)
        return value if _exempt(key, value, structured) else fence(value)
    if isinstance(value, list | tuple):
        return [_walk(key, item, structured) for item in value]
    if isinstance(value, dict):
        inner = structured or key == "field_sources"
        out: dict[str, object] = {}
        for index, (k, v) in enumerate(value.items()):
            name = str(k)
            if _SAFE_KEY.fullmatch(name):
                out[name] = _walk(name, v, inner)
            else:  # 键里可能是第三方文本：键改写为安全名，原键文本围栏后随值一起保留
                out[f"untrusted_key_{index}"] = {"key": fence(name), "value": _walk(name, v, inner)}
        return out
    return value


def fence_payload(payload: dict[str, object], tool: str | None = None) -> dict[str, object]:
    """返回副本：data 里所有字符串默认围栏（递归，含嵌套对象/列表），仅豁免结构化字段；
    warnings/error/evidence_ids 等服务端字段原样。"""
    data = payload.get("data")
    if not isinstance(data, dict) or tool in SERVER_OWNED_TOOLS:
        return payload
    return {**payload, "data": {k: _walk(str(k), v, False) for k, v in data.items()}}
