"""实时数据边界的坐标与安全错误；不依赖 HTTP 或数据库。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type ProviderDataMode = Literal["live", "synthetic"]
type DataMode = Literal["fixture", "snapshot"] | ProviderDataMode

type ExternalKind = Literal[
    "rate_limited",
    "timeout",
    "network",
    "upstream_5xx",
    "bad_request",
    "not_found_empty",
    "quota_exhausted",
    "invalid_json",
]


class ExternalAttempt(BaseModel):
    """闭合、无正文的请求结果；可进入工具、事件和 trace。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: ExternalKind | None = None
    status: int | None = Field(default=None, ge=100, le=599)
    attempts: int = Field(default=0, ge=0, le=2)
    waited_seconds: float = Field(default=0, ge=0, le=75)
    recovered_from: ExternalKind | None = None
    first_failure: ExternalKind | None = None
    retry_skipped: Literal["quota", "deadline"] | None = None
    provisional: bool = False
    cap_scope: Literal["run", "daily"] | None = None
    used: int | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=0)


def external_explanation(info: ExternalAttempt) -> str:
    """可信类别转用户说明，绝不读取上游正文。"""
    reasons: dict[ExternalKind, str] = {
        "rate_limited": "供应商请求过于频繁",
        "timeout": "供应商响应超时",
        "network": "供应商网络连接失败",
        "upstream_5xx": "供应商服务暂时异常",
        "bad_request": "供应商拒绝请求参数或权限",
        "not_found_empty": "供应商返回空结果",
        "quota_exhausted": "供应商调用配额已用完",
        "invalid_json": "供应商返回的数据格式无效",
    }
    message = reasons.get(info.kind, "供应商请求未完成") if info.kind else "供应商请求未完成"
    if info.status is not None:
        message += f"（HTTP {info.status}）"
    if info.used is not None and info.limit is not None:
        message += (
            f"；{'本轮' if info.cap_scope == 'run' else '今日'}已用{info.used}/{info.limit}次"
        )
    if info.attempts > 1:
        message += f"；已自动重试{info.attempts - 1}次"
    if info.retry_skipped:
        message += (
            "；因"
            + ("配额不足" if info.retry_skipped == "quota" else "剩余时间不足")
            + "未执行重试"
        )
    if info.waited_seconds:
        message += f"；已等待{info.waited_seconds:.1f}秒"
    return message + "。请核对条件或稍后再试。"


def external_code(
    info: ExternalAttempt,
) -> Literal["validation", "blocked", "unavailable", "timeout", "rate_limited"]:
    match info.kind:
        case "bad_request":
            return "validation"
        case "quota_exhausted":
            return "blocked"
        case "timeout":
            return "timeout"
        case "rate_limited":
            return "rate_limited"
        case _:
            return "unavailable"


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class GeoPoint(Coordinates):
    name: str
    viewport: dict[str, Coordinates] | None = None
    broad: bool = False


class ExternalDataError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        validation: bool = False,
        info: ExternalAttempt | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.validation = validation
        self.info = info or ExternalAttempt(kind="bad_request" if validation else "invalid_json")
        self.retry_after = retry_after


def broad_region(city: str) -> bool:
    """用户省级表达需细化住宿地点；不以城市面积推断范围。"""
    value = city.strip().casefold()
    return value in {
        "北海道",
        "hokkaido",
        "沖縄",
        "冲绳",
        "沖縄県",
        "okinawa",
        "东京都",
        "東京都",
    } or value.endswith(("県", "县", "府"))
