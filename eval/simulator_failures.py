"""私有控制器失败记录：封闭分类，不存异常正文；模型输出脱敏后限2KiB。"""

import json
import os
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from backend.domain.execution import scrub_internal_ids

type ControllerReason = Literal[
    "invalid_simulator_output",
    "simulator_unavailable",
    "choice_missing",
    "stale_choice",
    "answered_choice",
    "unknown_option",
    "unauthorized_draft",
    "service_rejected",
]
SECRET_KEYS = (
    "DEEPSEEK_API_KEY",
    "GOOGLE_MAPS_API_KEY",
    "RAKUTEN_APPLICATION_ID",
    "RAKUTEN_ACCESS_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "DATABASE_PASSWORD",
    "DATABASE_URL",
    "DATABASE_PUBLIC_URL",
    "TRAVEL_TRACE_HMAC_KEY",
)
ASSIGNMENT = re.compile(
    r'(?i)("?(?:api[_-]?key|access[_-]?key|token|secret(?:[_-]?key)?|hmac[_-]?key|password|authorization)"?\s*[:=]\s*)'
    r'("(?:\\.|[^"\\])*"|[^\s,}]+)'
)
TOKEN = re.compile(r"\b(?:sk-[a-z0-9_-]+|Bearer\s+[^\s,\"}]+)", re.I)
URL = re.compile(r"\b(?:https?|postgres(?:ql)?(?:\+psycopg)?)://[^\s\"'<>]+", re.I)
EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)


def private_output(text: str) -> str:
    for name in SECRET_KEYS:
        secret = os.environ.get(name)
        if secret:
            for form in (secret, json.dumps(secret, ensure_ascii=False)[1:-1]):
                text = text.replace(form, "[redacted]")
    text = TOKEN.sub("[redacted]", text)
    text = ASSIGNMENT.sub(r'\1"[redacted]"', text)
    text = EMAIL.sub("[email]", URL.sub("[url]", scrub_internal_ids(text)))
    return text.encode("utf-8")[:2048].decode("utf-8", errors="ignore")


def failure_details(
    reason: ControllerReason, response: str | None, action: Mapping[str, object] | None
) -> dict[str, object]:
    if action is None and response is not None:
        try:
            action = TypeAdapter(dict[str, object]).validate_json(response)
        except ValidationError:
            action = None  # 非法JSON仍保留脱敏raw，不复制异常正文。
    rejected = json.dumps(dict(action), ensure_ascii=False, default=str) if action else response
    return {
        "reason": reason,
        "raw_simulator_output": private_output(response) if response is not None else None,
        "rejected_action": private_output(rejected) if rejected is not None else None,
        "scope": "private, redacted, UTF-8 max 2048 bytes each; no exception message",
    }
