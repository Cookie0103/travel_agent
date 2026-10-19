"""RFC 5545 日历导出；UTC时间、文本转义与UTF-8字节折行。"""

from datetime import UTC, datetime

from backend.services.views import PlanView


def escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold(value: str) -> str:
    lines = []
    current = ""
    for char in value:
        if len((current + char).encode("utf-8")) > 75:
            lines.append(current)
            current = " "
        current += char
    return "\r\n".join([*lines, current])


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def calendar(plan: PlanView) -> str:
    """DTSTAMP取保存时间、SEQUENCE取计划版本：同一版本重复下载逐字节相同，新版本被日历当作更新。"""
    assert plan.version is not None and plan.saved_at is not None
    stale = "；提示：部分来源或报价已过期，出行前请重新确认" if plan.needs_refresh else ""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Travel Agent//Trip//ZH",
        "CALSCALE:GREGORIAN",
    ]
    for item in plan.cards:
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{item.item_id}@travel-agent",
                "DTSTAMP:" + stamp(plan.saved_at),
                f"SEQUENCE:{plan.version}",
                "DTSTART:" + stamp(item.start),
                "DTEND:" + stamp(item.end),
                "SUMMARY:" + escape(item.name),
                "DESCRIPTION:" + escape((item.source_ref or "来源未知") + stale),
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
