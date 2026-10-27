"""测试共用：Windows 默认 Proactor 循环与 psycopg 异步不兼容，连库的测试一律用 Selector 循环。"""

import asyncio
from typing import Any

SELECTOR_OPTIONS: dict[str, Any] = {"loop_factory": asyncio.SelectorEventLoop}


def selector_runner() -> asyncio.Runner:
    return asyncio.Runner(loop_factory=asyncio.SelectorEventLoop)
