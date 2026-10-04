"""跨平台 API 启动入口；Windows 为 PostgreSQL 显式选择支持的事件循环。"""

import argparse
import asyncio
import io
import sys

import uvicorn

from backend.api.app import create_app


def loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Travel Agent 本地API，默认离线")
    parser.add_argument("--live", action="store_true", help="允许显式live消息使用已授权人民币线路")
    parser.add_argument("--trace-cloud", action="store_true", help="显式上传脱敏运行记录到Langfuse")
    parser.add_argument("--host", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1")
    arguments = parser.parse_args()
    uvicorn.run(
        create_app(live_enabled=arguments.live, trace_cloud=arguments.trace_cloud),
        host=arguments.host,
        port=8000,
        loop="backend.server:loop_factory",
    )
