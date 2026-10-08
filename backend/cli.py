"""用户运行入口；默认离线演示，只有显式 --live 才读取付费线路配置。"""

import argparse
import asyncio
import io
import os
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from backend.adapters.tracing import cloud_exporter, trace_report
from backend.agent.fixture_runtime import FixtureRuntime
from backend.agent.runtime import Agent
from backend.domain.execution import RunContext, RuntimeEvent
from backend.limits import ProbeError
from backend.providers.claude_agent.live import run_live
from backend.tools.search import SearchExecutor


async def offline(prompt: str, *, trace_cloud: bool = False) -> int:
    exporter = cloud_exporter(os.environ) if trace_cloud else None
    agent = Agent(FixtureRuntime(SearchExecutor()))
    context = RunContext(uuid4())
    events: list[RuntimeEvent] = []
    result = await agent.run(context, prompt, events.append)
    directory = Path(__file__).resolve().parents[1] / ".cache" / "traces" / str(context.run_id)
    report: dict[str, object] = {
        "status": "error" if result.outcome.code else "success",
        "events": [asdict(e) for e in events],
        "identity": asdict(agent.runtime.identity),
    }
    trace_report(report, directory, exporter)
    if result.outcome.code:
        print(f"查询未完成：{result.outcome.code}")
        return 1
    print(result.outcome.text)
    print(f"本地 Trace：{report.get('trace_id', '记录失败；业务结果已保留')}")
    return 0


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="京都旅行助手：默认离线演示")
    parser.add_argument("prompt", nargs="?", default="京都有哪些室内景点？")
    parser.add_argument(
        "--live", action="store_true", help="使用已授权的 DeepSeek 线路；产生 API 费用"
    )
    parser.add_argument(
        "--trace-cloud", action="store_true", help="显式导出脱敏 Trace 到配置的 Langfuse"
    )
    arguments = parser.parse_args()
    try:
        if not arguments.live:
            return asyncio.run(offline(arguments.prompt, trace_cloud=arguments.trace_cloud))
        report = run_live(
            arguments.prompt,
            RunContext(uuid4()),
            Path(__file__).resolve().parents[1],
            trace_cloud=arguments.trace_cloud,
        )
    except (ProbeError, ValueError) as error:
        print(f"运行未开始：{error}")
        return 1
    if report.get("status") != "success":
        print(f"运行未完成：{report.get('code', 'provider_error')}，已保存私有运行记录。")
        return 1
    results = report.get("results")
    if isinstance(results, list) and results and isinstance(results[-1], dict):
        outcome = results[-1].get("outcome")
        if isinstance(outcome, dict):
            print(outcome.get("text", ""))
            print(
                f"本次真实请求：{report['http_attempts']}；"
                f"累计保守费用：{report['grant_accounted_cny']} 元"
            )
            return 0
    print("运行未返回完整结果。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
