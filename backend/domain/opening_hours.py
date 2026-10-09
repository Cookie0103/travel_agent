"""京都营业时间的保守子集；校验整段停留，未知语法绝不当作营业。"""

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

KYOTO = timezone(timedelta(hours=9), "Asia/Tokyo")
DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
Window = tuple[int, int]


def _days(value: str | None) -> set[int]:
    if value is None:
        return set(range(7))
    days: set[int] = set()
    for part in value.split(","):
        bounds = part.split("-")
        first, last = DAYS.index(bounds[0]), DAYS.index(bounds[-1])
        days.update((first + offset) % 7 for offset in range((last - first) % 7 + 1))
    return days


def _minutes(value: str) -> int:
    hours, minutes = map(int, value.split(":"))
    if hours > 24 or minutes > 59 or (hours == 24 and minutes):
        raise ValueError("invalid time")
    return hours * 60 + minutes


def _schedule(raw: str) -> dict[int, list[Window]]:
    week: dict[int, list[Window]] = {day: [] for day in range(7)}
    day_pattern = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
    selection = rf"{day_pattern}(?:-{day_pattern})?"
    pattern = rf"(?:(?P<days>{selection}(?:,{selection})*)\s+)?(?P<hours>.+)"
    for rule in raw.split(";"):
        match = re.fullmatch(pattern, rule.strip())
        if match is None:
            raise ValueError("unsupported rule")
        hours = match["hours"]
        windows: list[Window] = []
        if hours not in {"off", "closed"}:
            for span in hours.split(","):
                if not re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}", span):
                    raise ValueError("unsupported hours")
                start, end = map(_minutes, span.split("-"))
                if start >= 1440 or start == end:
                    raise ValueError("ambiguous interval")
                windows.append((start, end + (1440 if end < start else 0)))
        for day in _days(match["days"]):
            # 同一星期的后续规则覆盖前面的规则，例如 Mo-Su 09:00-17:00; Mo off。
            week[day] = windows
    if ";" in raw and any(end > 1440 for windows in week.values() for _, end in windows):
        raise ValueError("跨午夜与覆盖规则组合不在支持子集内")
    return week


def opening_state(
    raw: str | None, start: datetime, end: datetime
) -> Literal["open", "closed", "unknown"]:
    """仅支持24/7、星期范围/列表、固定时段及off；节假日/季节/注释均unknown。"""
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise ValueError("停留时间必须有时区且结束晚于开始")
    start, end = start.astimezone(KYOTO), end.astimezone(KYOTO)
    if not raw or end - start > timedelta(days=1):
        return "unknown"
    if raw.strip() == "24/7":
        return "open"
    try:
        week = _schedule(raw)
    except ValueError:
        return "unknown"
    intervals: list[tuple[datetime, datetime]] = []
    midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in (-1, 0, 1):
        day = midnight + timedelta(days=offset)
        intervals.extend(
            (day + timedelta(minutes=a), day + timedelta(minutes=b)) for a, b in week[day.weekday()]
        )
    covered = start
    for left, right in sorted(intervals):
        if left <= covered < right:
            covered = right
        if covered >= end:
            return "open"
    return "closed"
