"""固定温度无工具SDK调用；新角色仍使用ADR-011的同一运行与计费路径。"""

import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from backend.agent.persona import JudgeKind
from backend.domain.execution import RunContext, RunResult, RuntimeEvent
from backend.providers.claude_agent.live import run_live
from backend.providers.claude_agent.settings import load_runtime_settings


def structured_call(
    kind: JudgeKind,
    payload: object,
    root: Path,
    *,
    trace_cloud: bool = False,
    trace_id: str | None = None,
    evaluation: dict[str, object] | None = None,
) -> tuple[str, dict[str, object]]:
    context = RunContext(uuid4())
    report = run_live(
        json.dumps(payload, ensure_ascii=False, default=str),
        context,
        root,
        persona_judge=True,
        judge_kind=kind,
        trace_cloud=trace_cloud,
        trace_id=trace_id,
        evaluation=evaluation,
    )
    requests = report.get("requests")
    events = report.get("events")
    settings = load_runtime_settings(os.environ)
    identity = report.get("identity")
    if (
        report.get("status") != "success"
        or report.get("guard_failures") != []
        or not isinstance(requests, list)
        or not requests
        or report.get("http_attempts") != len(requests)
        or not isinstance(identity, dict)
        or identity.get("provider") != "deepseek"
        or identity.get("model") != settings.model
        or any(
            not isinstance(r, dict)
            or type(r.get("temperature")) is not int
            or r["temperature"] != 0
            for r in requests
        )
        or not isinstance(events, list)
        or any(not isinstance(e, dict) or e.get("kind") == "tool_started" for e in events)
    ):
        raise ValueError("无工具结构化调用未通过运行校验")
    observed = TypeAdapter(list[RuntimeEvent]).validate_python(events)
    if any(e.context != context for e in observed):
        raise ValueError("结构化事件身份不一致")
    result = TypeAdapter(list[RunResult]).validate_python(report.get("results"))
    if len(result) != 1 or result[0].context != context or result[0].outcome.code:
        raise ValueError("结构化结果身份或终态无效")
    return result[0].outcome.text, report
