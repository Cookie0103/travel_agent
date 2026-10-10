"""可信更新回执的用户文案；只描述实际改动，不显示内部ID。"""

from backend.domain.travel_request import TravelRequest

LABELS = {
    "city": "目的地",
    "hotel_search_location": "住宿查询地点",
    "start_date": "开始日期",
    "end_date": "结束日期",
    "adults": "成人",
    "child_ages": "儿童年龄",
    "rooms": "房间数",
    "budget": "全程预算",
    "lodging_budget": "住宿预算",
    "lodging_budget_unlimited": "每晚住宿预算",
    "segments": "城市段",
    "transport": "交通",
    "departure_time": "每日出发",
    "soft_constraints": "节奏/偏好",
    "hard_constraints": "硬条件",
    "interests": "兴趣",
    "currency": "全程币种",
    "timezone": "时区",
}


def value_label(request: TravelRequest, name: str) -> str:
    value = getattr(request, name)
    if value is None:
        return "未知"
    if name == "lodging_budget_unlimited":
        return (
            "不限" if request.lodging_budget_unlimited else value_label(request, "lodging_budget")
        )
    if name == "segments" and request.segments:
        return "；".join(f"{s.city} {s.arrive}—{s.depart}" for s in request.segments)
    if name == "lodging_budget" and request.lodging_budget:
        lodging = request.lodging_budget
        basis = "每房每晚" if lodging.basis == "per_room_night" else "住宿总额"
        return (
            f"{lodging.amount.lower or '下限未知'}–{lodging.amount.upper or '上限未知'} "
            f"{lodging.currency}（{basis}）"
        )
    if isinstance(value, tuple):
        if name == "child_ages":
            return "、".join(f"{age}岁" for age in value) if value else "无儿童"
        return "、".join(str(item) for item in value) or "未填"
    if name == "transport":
        return {"walk": "步行", "transit": "公共交通", "taxi": "出租车"}.get(str(value), "未知")
    return str(value)


def update_message(
    request: TravelRequest, changed: tuple[str, ...], skipped: tuple[str, ...]
) -> str:
    text = (
        "已按对话更新："
        + "；".join(f"{LABELS[name]}={value_label(request, name)}" for name in changed)
        + "。"
        if changed
        else "条件值没有变化。"
    )
    if skipped:
        text += (
            "保留手填的"
            + "、".join(LABELS[name] for name in skipped)
            + "；要修改请明确说改成什么。"
        )
    return text
