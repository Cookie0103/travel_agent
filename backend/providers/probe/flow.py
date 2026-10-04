"""执行一次合成工具往返并保存脱敏摘要，不实现旅行业务 Agent。"""

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam, ToolUseBlock

from backend.providers.probe.ledger import Entry, Ledger, exclusive
from backend.providers.probe.settings import ProbeError, Settings, price_for
from backend.providers.probe.transport import Reply, create_client, request

Send = Callable[[list[MessageParam], list[ToolParam]], Reply]
Save = Callable[[dict[str, object]], None]


def tools_for_probe() -> list[ToolParam]:
    """只有合成工具定义，不查询真实景点或网络。"""
    return [
        {
            "name": "lookup_fixture",
            "description": "Read a synthetic indoor place by city.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "enum": ["Kyoto", "Osaka"]},
                },
                "required": ["city"],
                "additionalProperties": False,
            },
            "cache_control": {"type": "ephemeral"},
        }
    ]


def synthetic_results(reply: Reply) -> list[ToolResultBlockParam]:
    """R02：只回传本轮完整合法的工具调用，按 ID 配对，故意反转结果顺序。"""
    calls = [block for block in reply.message.content if isinstance(block, ToolUseBlock)]
    if reply.message.stop_reason != "tool_use" or not calls or len(calls) > 2:
        raise ProbeError("provider_error", "首轮没有一至两个完整工具调用")
    if len({call.id for call in calls}) != len(calls) or any(not call.id for call in calls):
        raise ProbeError("validation", "工具调用 ID 缺失或重复")
    results: list[ToolResultBlockParam] = []
    for call in reversed(calls):
        args = call.input
        if call.name != "lookup_fixture" or not isinstance(args, dict) or set(args) != {"city"}:
            raise ProbeError("validation", "未知工具或参数格式错误")
        city = args["city"]
        if not isinstance(city, str) or city not in {"Kyoto", "Osaka"}:
            raise ProbeError("validation", "工具城市不在合成输入范围内")
        failed = city == "Osaka"
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": call.id,
                "is_error": failed,
                "content": json.dumps(
                    {
                        "status": "unavailable" if failed else "ok",
                        "city": city,
                        "fixture": None if failed else "sample_indoor_place",
                    }
                ),
            }
        )
    return results


def execute_flow(settings: Settings, send: Send, save: Save) -> dict[str, object]:
    """一次流程最多两次请求；第一轮完成后才允许带结果续接。"""
    report: dict[str, object] = {
        "model_requested": settings.model,
        "status": "running",
        "time": datetime.now(UTC).isoformat(),
        "thinking": "enabled",
        "cache_control_sent": True,
        "disable_parallel_tool_use": True,
    }
    save(report)
    try:
        messages: list[MessageParam] = [
            {
                "role": "user",
                "content": (
                    "Use lookup_fixture for Kyoto and Osaka, ideally together. "
                    "These are synthetic fixtures. After receiving BOTH results, "
                    "do not call tools again; briefly summarize the result and mention "
                    "any unavailable city. Keep reasoning and answer very short."
                ),
            }
        ]
        first = send(messages, tools_for_probe())
        report["first"] = first.summary(settings.model)
        save(report)
        results = synthetic_results(first)
        if (
            Decimal(str(first.summary(settings.model)["usage_cost_upper_cny"]))
            > price_for(settings.model).attempt_charge
        ):
            raise ProbeError("blocked", "响应用量超出保守费用估计，停止续接")
        report["tool_count"] = len(results)
        report["is_error_true_sent"] = any(result["is_error"] for result in results)
        report["result_order"] = "reversed_by_id"
        messages += [
            {"role": "assistant", "content": first.message.content},
            {"role": "user", "content": results},
        ]
        last = send(messages, tools_for_probe())
        report["last"] = last.summary(settings.model)
        require_final_answer(last)
        report["status"] = "success"
    except ProbeError as error:
        report.update(status="failed", error_code=error.code, reason=str(error))
        raise
    finally:
        save(report)
    return report


def require_final_answer(reply: Reply) -> None:
    """截断或仍想调工具时明确失败，不偷偷追加第三轮。"""
    if reply.message.stop_reason != "end_turn" or not any(
        block.type == "text" and block.text.strip() for block in reply.message.content
    ):
        raise ProbeError("provider_error", "续接没有完整最终回答，不追加调用")


def write_report(path: Path, report: dict[str, object]) -> None:
    """每个阶段原子替换摘要，避免记录半个 JSON。"""
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def run_probe(settings: Settings, directory: Path) -> dict[str, object]:
    """唯一真实入口；整次持有锁，成功后账本阻止再次运行。"""
    with exclusive(directory / "running.lock"):
        ledger = Ledger(directory / "ledger.jsonl")
        ledger.start_flow(datetime.now(UTC))
        count = sum(entry.kind == "flow" for entry in ledger.entries())
        with create_client(settings) as client:
            report = execute_flow(
                settings,
                lambda messages, tools: request(client, ledger, settings, messages, tools),
                lambda report: write_report(directory / f"flow-{count}.json", report),
            )
        ledger.append(Entry("success", datetime.now(UTC).date().isoformat(), "CNY"))
        return report
