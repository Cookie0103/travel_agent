"""进程内限流原语（演示登录、对外只读MCP）；不跨进程/重启共享，多实例部署时各实例各自计数。"""

import ipaddress
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping

from backend.services.common import ServiceError

type Clock = Callable[[], float]


def positive_int(environment: Mapping[str, str], name: str, default: int, cap: int) -> int:
    """读取正整数环境变量；非法值启动即报错，超过上限按上限（限流参数不能被配成“无限”）。"""
    raw = environment.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ValueError(f"{name} 必须为正整数")
    return min(value, cap)


class RateLimited(ServiceError):
    """429；retry_after 秒数供 Retry-After 响应头。"""

    def __init__(self, wait: float, reason: str) -> None:
        self.retry_after = max(1, math.ceil(wait))
        super().__init__(429, "rate_limited", "请求过于频繁，请稍后再试", reason)


def client_key(address: str) -> str:
    """限流用的客户端键：IPv4映射地址折成IPv4，IPv6按/64聚合；非法/空地址原样返回。"""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is not None:
            return str(parsed.ipv4_mapped)
        return str(ipaddress.IPv6Network((int(parsed), 64), strict=False))
    return str(parsed)


class SlidingWindow:
    """每个键在 seconds 秒内最多 limit 次；被拒绝的请求不计入，也不延长窗口。

    hits 按“最近一次被接受的时间”有序（最旧在前）：过期键从队首惰性摊销O(1)清除；
    超过 max_keys 时淘汰最旧的键，内存有界（被淘汰的活跃键额度重置，这是有界内存的代价）。
    """

    def __init__(
        self, limit: int, seconds: float, clock: Clock = time.monotonic, max_keys: int = 10_000
    ) -> None:
        self.limit, self.seconds, self.clock, self.max_keys = limit, seconds, clock, max_keys
        self.hits: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, key: str) -> float:
        """只检查不记录、不建键：允许返回0，否则返回需等待的秒数。"""
        now = self.clock()
        queue = self.hits.get(key)
        if queue is None:
            return 0.0
        while queue and queue[0] <= now - self.seconds:
            queue.popleft()
        return queue[0] + self.seconds - now if len(queue) >= self.limit else 0.0

    def hit(self, key: str) -> float:
        """允许返回0并记一次；否则返回需等待的秒数。"""
        wait = self.check(key)
        if wait:
            return wait
        now = self.clock()
        queue = self.hits.get(key)
        if queue is None:
            queue = self.hits[key] = deque()
        queue.append(now)
        self.hits.move_to_end(key)
        while self.hits:
            oldest, history = next(iter(self.hits.items()))
            if len(self.hits) > self.max_keys or not history or history[-1] <= now - self.seconds:
                del self.hits[oldest]
            else:
                break
        return 0.0


class TokenBucket:
    """每个键容量 burst，每秒补 per_second 个令牌；take 消耗一个。"""

    def __init__(
        self, burst: int, per_second: float, clock: Clock = time.monotonic, max_keys: int = 10_000
    ) -> None:
        self.burst, self.per_second, self.clock, self.max_keys = burst, per_second, clock, max_keys
        self.state: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def take(self, key: str) -> float:
        """允许返回0；否则返回下一个令牌还需等待的秒数。"""
        now = self.clock()
        tokens, stamp = self.state.get(key, (float(self.burst), now))
        tokens = min(float(self.burst), tokens + (now - stamp) * self.per_second)
        if tokens < 1:
            self.state[key] = (tokens, now)
            return math.ceil((1 - tokens) / self.per_second * 1000) / 1000
        self.state[key] = (tokens - 1, now)
        self.state.move_to_end(key)  # 按最近使用有序；队首已补满的键等同没有记录
        while self.state:
            oldest, (held, stamp) = next(iter(self.state.items()))
            full = held + (now - stamp) * self.per_second >= self.burst
            if len(self.state) > self.max_keys or full:
                del self.state[oldest]
            else:
                break
        return 0.0
