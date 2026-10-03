"""跨平台 API 启动入口；Windows 为 PostgreSQL 显式选择支持的事件循环。"""

import asyncio
import io
import sys

import uvicorn


def loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    uvicorn.run(
        "backend.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        loop="backend.server:loop_factory",
    )
