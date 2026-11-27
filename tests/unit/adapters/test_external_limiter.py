"""乐天发送间隔使用虚拟时钟，不等待真实秒数。"""

import asyncio

from backend.adapters.external_api import RakutenLimiter


def test_concurrent_requests_keep_minimum_interval() -> None:
    now = 0.0
    sent: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    async def exercise() -> None:
        limiter = RakutenLimiter(1.1, lambda: now, sleep)

        async def send() -> None:
            await limiter.wait()
            sent.append(now)

        await asyncio.gather(send(), send(), send())

    asyncio.run(exercise())
    assert sent == [0.0, 1.1, 2.2]
