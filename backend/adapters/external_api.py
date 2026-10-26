"""外部请求共用最小计数与错误边界；不保存 URL、密钥或原始响应。"""

import asyncio
import math
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary

import httpx
from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError
from sqlalchemy import text

from backend.domain.external_data import ExternalAttempt, ExternalDataError
from backend.persistence.database import Database
from backend.profile import DEFAULT, current
from backend.trace_log import trace

ApiName = Literal["geocode", "places", "routes", "rakuten", "weather"]
CAP_NAMES: dict[ApiName, str] = {
    "geocode": "GOOGLE_GEOCODE_DAILY_CAP",
    "places": "GOOGLE_PLACES_DAILY_CAP",
    "routes": "GOOGLE_ROUTES_DAILY_CAP",
    "rakuten": "RAKUTEN_DAILY_CAP",
    "weather": "WEATHER_DAILY_CAP",
}
REQUEST_DEADLINE: ContextVar[float | None] = ContextVar("external_request_deadline", default=None)
# 本次工具调用自己的外部尝试；并发调用共享usage.observations，按切片归属会串到别的调用。
CALL_OBSERVATIONS: ContextVar[list[ExternalAttempt] | None] = ContextVar(
    "external_call_observations", default=None
)


class RakutenLimiter:
    """只串行化发送间隔；时钟与等待可注入，无新调度层。"""

    def __init__(
        self,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.lock = asyncio.Lock()
        self.last_sent: float | None = None

    async def wait(self) -> float:
        async with self.lock:
            delay = (
                0.0
                if self.last_sent is None
                else max(0.0, self.last_sent + self.interval - self.clock())
            )
            if delay:
                await self.sleep(delay)
            self.last_sent = self.clock()
            return delay


_LIMITERS: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[float, RakutenLimiter]] = (
    WeakKeyDictionary()
)


def _limiter(interval: float) -> RakutenLimiter:
    # worker通常只有一个loop；测试和运维多loop不能共享已绑定的asyncio锁。
    return _LIMITERS.setdefault(asyncio.get_running_loop(), {}).setdefault(
        interval, RakutenLimiter(interval)
    )


class ApiUsage:
    rakuten_interval: float = 1.1
    _observations: list[ExternalAttempt] | None = None

    @property
    def observations(self) -> list[ExternalAttempt]:
        if self._observations is None:
            self._observations = []
        return self._observations

    def __init__(
        self, database: Database, environment: Mapping[str, str], *, run_limits: bool = True
    ) -> None:
        self.database = database
        self.daily: dict[ApiName, int] = {}
        self.used: dict[ApiName, int] = {}
        limits = current(environment)
        self.run_caps = {api: limits.run_caps[api] for api in CAP_NAMES}
        self.run_limits = run_limits
        self.default_profile = limits is DEFAULT
        self._observations = []
        try:
            self.rakuten_interval = float(
                environment.get("RAKUTEN_MIN_INTERVAL_SECONDS", "").strip() or "1.1"
            )
            if not math.isfinite(self.rakuten_interval) or not 0 <= self.rakuten_interval <= 3:
                raise ValueError
        except ValueError:
            raise ExternalDataError(
                "RAKUTEN_MIN_INTERVAL_SECONDS 必须在0到3之间", validation=True
            ) from None
        for api, name in CAP_NAMES.items():
            try:
                cap = int(environment.get(name, "").strip() or limits.daily_defaults[api])
                if cap < 0:
                    raise ValueError
            except ValueError:
                raise ExternalDataError(f"{name} 必须为非负整数") from None
            self.daily[api] = cap

    async def consume(self, api: ApiName) -> None:
        limit = self.run_caps[api]
        if self.run_limits and limit is not None and self.used.get(api, 0) >= limit:
            trace(
                "cap_hit", api=api, cap="run", used=self.used.get(api, 0), limit=self.run_caps[api]
            )
            raise ExternalDataError(
                f"本轮 {api} 调用已达上限（{self.used.get(api, 0)}/{limit}）",
                info=ExternalAttempt(
                    kind="quota_exhausted", cap_scope="run", used=self.used.get(api, 0), limit=limit
                ),
            )
        cap = self.daily[api]
        if cap == 0:
            trace("cap_hit", api=api, cap="daily", used=0, limit=0)
            raise ExternalDataError(
                f"{api} 调用已禁用（0/0）",
                info=ExternalAttempt(kind="quota_exhausted", cap_scope="daily", used=0, limit=0),
            )
        # 先占本轮额度再await：并发只读工具不能在计数事务期间一起越过本轮上限；未发出则退还。
        self.used[api] = self.used.get(api, 0) + 1
        # 不变量：独立事务先提交计数，再联网；业务失败/回滚不会退还已发请求。
        try:
            async with self.database.sessions.begin() as db:
                count = await db.scalar(
                    text(
                        "INSERT INTO external_api_usage(day, api, calls) VALUES (:day, :api, 1) "
                        "ON CONFLICT (day, api) DO UPDATE SET calls = external_api_usage.calls + 1 "
                        "WHERE external_api_usage.calls < :cap RETURNING calls"
                    ),
                    {"day": datetime.now(UTC).date(), "api": api, "cap": cap},
                )
        except BaseException:
            self.used[api] -= 1
            raise
        if count is None:
            self.used[api] -= 1
            trace("cap_hit", api=api, cap="daily", used=cap, limit=cap)
            raise ExternalDataError(
                f"今日 {api} 调用已达上限（{cap}/{cap}）",
                info=ExternalAttempt(
                    kind="quota_exhausted", cap_scope="daily", used=cap, limit=cap
                ),
            )


def parse_response[T: BaseModel](model: type[T], payload: object) -> T:
    try:
        return model.model_validate(payload)
    except ValidationError:
        raise ExternalDataError("供应商响应字段缺失或格式无效") from None


async def request_json(
    http: httpx.AsyncClient,
    usage: ApiUsage,
    api: ApiName,
    method: str,
    url: str,
    *,
    params: dict[str, str | int | float] | None = None,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    empty_404: bool = False,
) -> dict[str, JsonValue]:
    parts = urlsplit(url)
    started = time.monotonic()
    seen: dict[str, object] = {"status": None, "bytes": None, "error_class": None}
    attempts, waited = 0, 0.0
    first: ExternalDataError | None = None
    attempt_kinds: list[str] = []
    info = ExternalAttempt()
    delay = 0.0
    try:
        for attempt in range(2):
            try:
                await usage.consume(api)
            except ExternalDataError as quota:
                info = quota.info.model_copy(
                    update={
                        "attempts": attempts,
                        "waited_seconds": waited,
                        "recovered_from": first.info.kind if first else None,
                        "first_failure": first.info.kind if first else None,
                        "retry_skipped": "quota" if first else None,
                    }
                )
                raise ExternalDataError(
                    (str(first) + "；因配额不足未执行重试；" if first else "") + str(quota),
                    info=info,
                ) from None
            if delay:
                await asyncio.sleep(delay)
                waited += delay
            if api == "rakuten":
                waited += await _limiter(usage.rakuten_interval).wait()
            attempts += 1
            seen = {"status": None, "bytes": None, "error_class": None}
            try:
                result = await _request(
                    http, api, method, url, params, headers, body, empty_404, seen
                )
                info = ExternalAttempt(
                    attempts=attempts,
                    waited_seconds=waited,
                    recovered_from=first.info.kind if first else None,
                    first_failure=first.info.kind if first else None,
                    kind="not_found_empty" if seen["status"] == 404 else None,
                )
                return result
            except ExternalDataError as error:
                info = error.info.model_copy(
                    update={
                        "attempts": attempts,
                        "waited_seconds": waited,
                        "first_failure": first.info.kind if first else error.info.kind,
                    }
                )
                if attempt or error.info.kind not in {
                    "rate_limited",
                    "timeout",
                    "network",
                    "upstream_5xx",
                    "invalid_json",
                }:
                    raise ExternalDataError(
                        str(error), validation=error.validation, info=info
                    ) from None
                delay = (
                    (
                        min(error.retry_after, 3)
                        if error.retry_after is not None
                        else 1 + random.uniform(0, 0.3)
                    )
                    if error.info.kind == "rate_limited"
                    else 0.5 + random.uniform(0, 0.3)
                )
                deadline = REQUEST_DEADLINE.get()
                if (
                    deadline is not None
                    and time.monotonic()
                    + delay
                    + 8
                    + (usage.rakuten_interval if api == "rakuten" else 0)
                    >= deadline
                ):
                    info = info.model_copy(update={"retry_skipped": "deadline"})
                    raise ExternalDataError(
                        str(error) + "；剩余执行时间不足，未重试", info=info
                    ) from None
                first = error
            finally:
                attempt_kinds.append(info.kind or "ok")
        raise AssertionError("bounded request loop exhausted")
    finally:
        usage.observations.append(info)
        if (own := CALL_OBSERVATIONS.get()) is not None:
            own.append(info)
        if len(usage.observations) > 256:
            del usage.observations[:-256]
        trace(
            "api_call",
            api=api,
            method=method,
            host=parts.netloc,
            path=parts.path,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            retries=max(0, attempts - 1),
            attempt_kinds=attempt_kinds,
            kind=info.kind,
            waited_seconds=waited,
            recovered_from=info.recovered_from,
            first_failure=info.first_failure,
            retry_skipped=info.retry_skipped,
            **seen,
        )


async def _request(
    http: httpx.AsyncClient,
    api: ApiName,
    method: str,
    url: str,
    params: dict[str, str | int | float] | None,
    headers: dict[str, str] | None,
    body: dict[str, object] | None,
    empty_404: bool,
    seen: dict[str, object],
) -> dict[str, JsonValue]:
    try:
        response = await http.request(
            method, url, params=params, headers=headers, json=body, timeout=8
        )
    except httpx.TimeoutException as error:
        seen["error_class"] = type(error).__name__
        raise ExternalDataError(
            f"{api} 请求超时，请稍后再试", info=ExternalAttempt(kind="timeout")
        ) from None
    except httpx.RequestError as error:
        seen["error_class"] = type(error).__name__
        raise ExternalDataError(
            f"{api} 网络连接失败", info=ExternalAttempt(kind="network")
        ) from None
    seen.update(status=response.status_code, bytes=len(response.content))
    if empty_404 and response.status_code == 404:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("error") == "not_found":
            return {"hotels": []}
    if response.status_code == 429:
        try:
            delay = float(response.headers.get("Retry-After", ""))
            if not math.isfinite(delay) or delay < 0:
                raise ValueError
        except ValueError:
            try:
                date = parsedate_to_datetime(response.headers.get("Retry-After", ""))
                delay = max(0.0, (date - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                delay = None
        raise ExternalDataError(
            f"{api} 请求受限（429），请稍后再试",
            info=ExternalAttempt(kind="rate_limited", status=429),
            retry_after=delay,
        )
    if not response.is_success:
        raise ExternalDataError(
            f"{api} 请求失败（HTTP {response.status_code}），请检查API权限与配额",
            info=ExternalAttempt(
                kind="upstream_5xx" if response.status_code >= 500 else "bad_request",
                status=response.status_code,
            ),
            validation=response.status_code < 500,
        )
    try:
        return TypeAdapter(dict[str, JsonValue]).validate_python(response.json())
    except (ValueError, ValidationError):
        raise ExternalDataError(
            f"{api} 返回了无效 JSON",
            info=ExternalAttempt(kind="invalid_json", status=response.status_code),
        ) from None
