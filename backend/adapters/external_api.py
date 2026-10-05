"""外部请求共用最小计数与错误边界；不保存 URL、密钥或原始响应。"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError
from sqlalchemy import text

from backend.domain.external_data import ExternalDataError
from backend.persistence.database import Database
from backend.providers.claude_agent.profile import DEFAULT, current

ApiName = Literal["geocode", "places", "routes", "rakuten", "weather"]
CAP_NAMES: dict[ApiName, str] = {
    "geocode": "GOOGLE_GEOCODE_DAILY_CAP",
    "places": "GOOGLE_PLACES_DAILY_CAP",
    "routes": "GOOGLE_ROUTES_DAILY_CAP",
    "rakuten": "RAKUTEN_DAILY_CAP",
    "weather": "WEATHER_DAILY_CAP",
}


class ApiUsage:
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
        for api, name in CAP_NAMES.items():
            try:
                cap = int(environment.get(name, "").strip() or limits.daily_defaults[api])
                if cap < 0:
                    raise ValueError
            except ValueError:
                raise ExternalDataError(f"{name} 必须为非负整数") from None
            self.daily[api] = cap

    async def consume(self, api: ApiName) -> None:
        if self.run_limits and self.used.get(api, 0) >= self.run_caps[api]:
            raise ExternalDataError(f"本轮 {api} 调用已达上限")
        cap = self.daily[api]
        if cap == 0:
            raise ExternalDataError(f"{api} 调用已禁用")
        # 不变量：独立事务先提交计数，再联网；业务失败/回滚不会退还已发请求。
        async with self.database.sessions.begin() as db:
            count = await db.scalar(
                text(
                    "INSERT INTO external_api_usage(day, api, calls) VALUES (:day, :api, 1) "
                    "ON CONFLICT (day, api) DO UPDATE SET calls = external_api_usage.calls + 1 "
                    "WHERE external_api_usage.calls < :cap RETURNING calls"
                ),
                {"day": datetime.now(UTC).date(), "api": api, "cap": cap},
            )
        if count is None:
            raise ExternalDataError(f"今日 {api} 调用已达上限")
        self.used[api] = self.used.get(api, 0) + 1


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
    await usage.consume(api)
    try:
        response = await http.request(
            method, url, params=params, headers=headers, json=body, timeout=8
        )
    except httpx.TimeoutException:
        raise ExternalDataError(f"{api} 请求超时，请稍后再试") from None
    except httpx.RequestError:
        raise ExternalDataError(f"{api} 网络连接失败") from None
    if empty_404 and response.status_code == 404:
        return {"hotels": []}
    if response.status_code == 429:
        raise ExternalDataError(f"{api} 请求受限（429），请稍后再试")
    if not response.is_success:
        raise ExternalDataError(
            f"{api} 请求失败（HTTP {response.status_code}），请检查API权限与配额"
        )
    try:
        return TypeAdapter(dict[str, JsonValue]).validate_python(response.json())
    except (ValueError, ValidationError):
        raise ExternalDataError(f"{api} 返回了无效 JSON") from None
