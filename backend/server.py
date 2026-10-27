"""跨平台 API 启动入口；Windows 为 PostgreSQL 显式选择支持的事件循环。"""

import argparse
import asyncio
import io
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv

from backend.api.app import create_app
from backend.limits import ProbeError
from backend.profile import current, profile_name
from backend.providers.claude_agent.ledger import exclusive
from backend.services import runs
from backend.tools.travel import LIVE_TOOL_TIMEOUT
from backend.trace_log import enable_stdout, trace


def loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()


def proxy_options(environment: Mapping[str, str]) -> dict[str, Any]:
    """代理头默认关闭（uvicorn默认会信任本机来源的X-Forwarded-For，可被伪造）；
    仅当显式设置 FORWARDED_ALLOW_IPS（受信代理地址，逗号分隔）才开启，且只信任这些来源。"""
    trusted = environment.get("FORWARDED_ALLOW_IPS", "").strip()
    if not trusted:
        return {"proxy_headers": False}
    return {"proxy_headers": True, "forwarded_allow_ips": trusted}


def log_boot() -> None:
    """启动时打印生效限额，便于从部署日志确认 profile。"""
    limits = current()
    trace(
        "boot",
        profile=profile_name(),
        limits={
            **{
                key: getattr(limits, key)
                for key in (
                    "max_calls",
                    "max_turns",
                    "max_attempts",
                    "upstream_timeout",
                    "worker_timeout",
                    "process_timeout",
                    "evidence_ttl_minutes",
                    "max_validations",
                )
            },
            "run_timeout": runs.RUN_TIMEOUT or limits.run_timeout,
            "live_tool_timeout": LIVE_TOOL_TIMEOUT,
            "run_caps": dict(limits.run_caps),
            "daily_cap": limits.daily_cny_cap,
        },
    )


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", encoding="utf-8", override=False)
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Travel Agent 本地API，默认离线")
    parser.add_argument("--live", action="store_true", help="允许显式live消息使用已授权人民币线路")
    parser.add_argument("--relaxed", action="store_true", help="放宽次数与时限（费用上限不变）")
    parser.add_argument("--trace-cloud", action="store_true", help="显式上传脱敏运行记录到Langfuse")
    parser.add_argument("--host", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1")
    arguments = parser.parse_args()
    if arguments.relaxed:
        os.environ["TRAVEL_PROFILE"] = "relaxed"
    enable_stdout()  # Railway只收集stdout
    log_boot()
    if arguments.live:
        try:
            with exclusive(Path(__file__).resolve().parents[1] / ".cache/model-budget/active.lock"):
                trace("live_lock_ready")  # 只核对锁可获取；不预占费用、不调用模型
        except (OSError, ProbeError):
            trace("live_lock_unavailable")  # 活跃旧实例仍持锁时保持互斥，不让诊断阻止服务启动
    uvicorn.run(
        create_app(live_enabled=arguments.live, trace_cloud=arguments.trace_cloud),
        host=arguments.host,
        port=8000,
        loop="backend.server:loop_factory",
        **proxy_options(os.environ),
    )
