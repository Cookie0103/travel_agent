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


def calendar(plan: PlanView) -> str:
    def stamp(value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

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
                "DTSTAMP:" + stamp(plan.saved_at or datetime.now(UTC)),
                "DTSTART:" + stamp(item.start),
                "DTEND:" + stamp(item.end),
                "SUMMARY:" + escape(item.name),
                "DESCRIPTION:" + escape(item.source_ref or "来源未知"),
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
