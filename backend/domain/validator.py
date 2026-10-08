"""纯代码校验行程；区分已满足、未知与硬冲突，给SDK具体修复反馈而不代写模型循环。"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from backend.domain.catalog import Place
from backend.domain.evidence import EvidenceRecord, evidence_conditions
from backend.domain.hotels import HotelOffer
from backend.domain.itinerary import (
    CheckStatus,
    ItineraryProposal,
    RouteEstimate,
    ValidationCheck,
    ValidationReport,
)
from backend.domain.opening_hours import KYOTO, opening_state
from backend.domain.travel_request import TravelRequest, lodging_budget_relation


def check(subject: str, status: CheckStatus, code: str, message: str) -> ValidationCheck:
    return ValidationCheck(subject=subject, status=status, code=code, message=message)


def hhmm(value: datetime) -> str:
    return value.astimezone(KYOTO).strftime("%H:%M")


def traced(
    entry: ValidationCheck, proposal: ItineraryProposal, index: int, times: str = ""
) -> ValidationCheck:
    """附加只含序号与时刻的TRACE标签：d{第几天}i{当天第几项}（均从1起）。"""
    dates = [item.start.astimezone(KYOTO).date() for item in proposal.items]
    day = len(dict.fromkeys(dates[: index + 1]))
    position = dates[: index + 1].count(dates[index])
    return entry.tagged(f"{entry.code}:{entry.status}@d{day}i{position}{times}")


def validate_itinerary(
    request: TravelRequest,
    proposal: ItineraryProposal,
    records: tuple[EvidenceRecord, ...],
    now: datetime,
) -> ValidationReport:
    evidence = {record.evidence_id: record for record in records}
    if proposal.expected_revision != request.revision:
        raise ValueError("行程条件版本已变化")
    if set(proposal.evidence_ids()) != set(evidence) or any(
        not record.applicable(request, now) for record in records
    ):
        raise ValueError("行程证据缺失或已失效")
    checks: list[ValidationCheck] = []
    for index, item in enumerate(proposal.items):
        record = evidence[item.place_evidence_id]
        if record.kind != "place":
            raise ValueError("地点引用必须是place证据")
        place = Place.model_validate(record.value) if record.status == "verified" else None
        if place and place.place_id != record.entity_id:
            raise ValueError("地点证据实体不一致")
        checks.extend(visit_checks(request, proposal, index, place))
        checks.extend(route_checks(request, proposal, index, evidence))
    known, estimated, costs = budget_checks(request, proposal, evidence, now)
    checks.extend(costs)
    if request.hard_constraints:
        checks.append(
            check(
                "request",
                "unknown",
                "free_text_constraints",
                "自由文本硬条件尚不能全部机械核查，需保留并明确未验证",
            )
        )
    states = {entry.status for entry in checks}
    status: Literal["complete", "partial", "conflict"] = (
        "conflict" if "conflict" in states else "partial" if "unknown" in states else "complete"
    )
    return ValidationReport(
        status=status, checks=tuple(checks), known_cost=known, estimated_cost=estimated
    )


def visit_checks(
    request: TravelRequest, proposal: ItineraryProposal, index: int, place: Place | None
) -> list[ValidationCheck]:
    item = proposal.items[index]
    subject = f"item:{index}"
    start, end = item.start.astimezone(KYOTO), item.end.astimezone(KYOTO)
    checks: list[ValidationCheck] = []
    if end <= start:
        return [check(subject, "conflict", "visit_duration", "停留结束必须晚于开始")]
    if request.start_date is None or request.end_date is None:
        checks.append(check(subject, "unknown", "trip_dates", "旅行日期未完整确认"))
    elif start.date() < request.start_date or end.date() > request.end_date:
        checks.append(
            check(subject, "conflict", "trip_dates", "停留超出当前旅行日期，按日本时区检查")
        )
    else:
        checks.append(check(subject, "verified", "trip_dates", "停留日期符合旅行范围"))
    if place is None:
        checks.append(check(subject, "unknown", "place_source", "地点证据缺来源，不能认定事实"))
    elif request.city != place.city:
        checks.append(
            check(
                subject,
                "conflict" if request.city else "unknown",
                "city",
                "地点城市与当前条件不一致或城市未确认",
            )
        )
    if index and proposal.items[index - 1].end > item.start:
        checks.append(
            check(
                subject, "conflict", "overlap", "停留与前一项重叠或列表未按时间排序，不能重复安排"
            )
        )
    state = opening_state(place.opening_hours, item.start, item.end) if place else "unknown"
    opening_status: CheckStatus = (
        "verified" if state == "open" else "conflict" if state == "closed" else "unknown"
    )
    checks.append(
        check(
            subject,
            opening_status,
            "opening_hours",
            {
                "open": "快照营业时间覆盖整段停留",
                "closed": "快照营业时间不覆盖停留，请修改日期/时段或地点",
                "unknown": "营业时间缺失或语法未支持，不能认定营业",
            }[state],
        )
    )
    if (
        request.departure_time
        and (index == 0 or proposal.items[index - 1].end.astimezone(KYOTO).date() < start.date())
        and start.timetz().replace(tzinfo=None) < request.departure_time
    ):
        checks.append(
            check(subject, "conflict", "departure_time", "当天首项早于用户明确的出发时刻")
        )
    return checks


def route_checks(
    request: TravelRequest,
    proposal: ItineraryProposal,
    index: int,
    evidence: dict[UUID, EvidenceRecord],
) -> list[ValidationCheck]:
    item = proposal.items[index]
    subject = f"route:{index - 1}->{index}"
    previous = proposal.items[index - 1] if index else None
    if (
        previous is None
        or previous.end.astimezone(KYOTO).date() < item.start.astimezone(KYOTO).date()
    ):
        return (
            [
                traced(
                    check(
                        subject,
                        "conflict",
                        "route_unexpected",
                        "当天首项不带路段：请去掉该项的route_evidence_id"
                        "（路段只接在同一天前一项之后）",
                    ),
                    proposal,
                    index,
                )
            ]
            if item.route_evidence_id
            else []
        )
    if item.route_evidence_id is None:
        return [check(subject, "unknown", "route_missing", "缺少前后地点路段，不猜测可以及时到达")]
    record = evidence[item.route_evidence_id]
    if record.kind != "route":
        raise ValueError("路段引用必须是route证据")
    if record.status == "unknown":
        return [check(subject, "unknown", "route_source", "路段缺来源，不使用其耗时和费用")]
    route = RouteEstimate.model_validate(record.value)
    endpoints = (
        evidence[previous.place_evidence_id].entity_id,
        evidence[item.place_evidence_id].entity_id,
    )
    if (
        route.from_place_id,
        route.to_place_id,
    ) != endpoints or route.transport != request.transport:
        return [
            traced(
                check(
                    subject,
                    "conflict",
                    "route_scope",
                    "路段起终点或交通方式与行程不一致：请按行程顺序，用前一项与本项的place证据ID"
                    "和当前交通方式重新estimate_routes该段",
                ),
                proposal,
                index,
            )
        ]
    times = f" dep={hhmm(route.departure)} pe={hhmm(previous.end)} ns={hhmm(item.start)}"
    if route.departure < previous.end:
        message = (
            f"路段出发({hhmm(route.departure)})早于前一项结束({hhmm(previous.end)})："
            f"请用{hhmm(previous.end)}作为出发时间重新estimate_routes该段"
        )
        return [
            traced(check(subject, "conflict", "route_departure", message), proposal, index, times)
        ]
    if route.departure > item.start:
        message = (
            f"路段出发({hhmm(route.departure)})晚于下一项开始({hhmm(item.start)})："
            f"请重新安排时间，或用不晚于{hhmm(item.start)}的出发时间重新估算"
        )
        return [
            traced(check(subject, "conflict", "route_departure", message), proposal, index, times)
        ]
    if route.minutes is None:
        message = (
            "路线查询失败或达到调用上限，无法确认耗时"
            if record.data_mode == "live"
            else "自制路段表未覆盖此路线"
        )
        return [check(subject, "unknown", "route_duration", message)]
    if route.departure + timedelta(minutes=route.minutes) > item.start:
        return [check(subject, "conflict", "route_gap", "两项之间的时间不足以完成估算路段")]
    if record.data_mode == "live":
        return [check(subject, "verified", "route_live", "Google路线估算耗时内，排程时间足够")]
    return [
        check(
            subject,
            "unknown",
            "route_estimate",
            "路线时长仅估算，排程已留足表中时间，仍非实时路线保证",
        )
    ]


def budget_checks(
    request: TravelRequest,
    proposal: ItineraryProposal,
    evidence: dict[UUID, EvidenceRecord],
    now: datetime,
) -> tuple[Decimal, Decimal, list[ValidationCheck]]:
    known, estimated = Decimal(0), Decimal(0)
    checks = [
        check(
            "budget",
            "unknown",
            "other_costs",
            "景点门票、餐饮等未获得完整费用证据，不能认定全程预算满足",
        )
    ]
    relation = lodging_budget_relation(request)
    checks.append(
        check(
            "lodging_budget",
            "conflict"
            if relation.status == "conflict"
            else "verified"
            if relation.status == "within"
            else "unknown",
            "lodging_budget_" + relation.status,
            relation.message,
        )
    )
    if proposal.hotel_evidence_id:
        known, hotel_checks = hotel_cost(request, evidence[proposal.hotel_evidence_id], now)
        checks.extend(hotel_checks)
    else:
        checks.append(check("hotel", "unknown", "hotel_missing", "未选择住宿报价，不猜测住宿费用"))
    for item in proposal.items:
        if item.route_evidence_id:
            record = evidence[item.route_evidence_id]
            if record.kind != "route":
                raise ValueError("路段引用必须是route证据")
            route = (
                RouteEstimate.model_validate(record.value) if record.status == "verified" else None
            )
            if route and route.fare is not None:
                estimated += route.fare
            elif route and route.minutes is not None and route.transport == "walk":
                pass  # 步行已有耗时估算，费用为0
            else:
                checks.append(
                    check("budget", "unknown", "route_fare", "路段缺全员费用估算，不能当作免费")
                )
    if request.budget is None:
        checks.append(check("budget", "unknown", "budget_missing", "预算尚未明确"))
    elif known > request.budget:
        checks.append(
            check(
                "budget",
                "conflict",
                "known_cost_over_budget",
                "仅已知住宿金额下界已超过整个旅行预算",
            )
        )
    elif known + estimated > request.budget:
        checks.append(
            check(
                "budget",
                "unknown",
                "estimated_cost_over_budget",
                "已知加估算成本超过预算，需要调整或核实估算",
            )
        )
    return known, estimated, checks


HOTEL_CONDITIONS_REASON = (
    "住宿报价与当前住宿条件不一致（日期/人数/房间/币种/城市变了），请重新search_hotel_offers"
)
HOTEL_EXPIRED_REASON = "住宿报价已过期，请重新search_hotel_offers"


def hotel_cost(
    request: TravelRequest, record: EvidenceRecord, now: datetime
) -> tuple[Decimal, list[ValidationCheck]]:
    if record.kind != "hotel_offer":
        raise ValueError("酒店引用必须是hotel_offer证据")
    if record.status == "unknown":
        return Decimal(0), [
            check("hotel", "unknown", "hotel_source", "住宿报价缺来源，不计为已知成本")
        ]
    offer = HotelOffer.model_validate(record.value)
    if str(offer.offer_id) != record.entity_id:
        raise ValueError("住宿报价与证据不一致")
    # 不绑定请求revision：预算/交通/兴趣等无关更新不应使报价失效；影响报价的条件逐字段比较。
    if evidence_conditions(offer.request, "hotel_offer") != evidence_conditions(
        request, "hotel_offer"
    ):
        raise ValueError(HOTEL_CONDITIONS_REASON)
    if not offer.quoted_at <= now < offer.expires_at:
        raise ValueError(HOTEL_EXPIRED_REASON)
    if offer.currency != request.currency:
        return Decimal(0), [check("hotel", "conflict", "currency", "住宿报价币种与当前条件不同")]
    if offer.total is None:
        known = (
            offer.base_amount + (offer.tax_amount or Decimal(0)) + (offer.fee_amount or Decimal(0))
        )
        return known, [
            check("hotel", "unknown", "hotel_total", "住宿缺税费，总价未知；已知金额只表示下界")
        ]
    return offer.total, [
        check("hotel", "verified", "hotel_total", "住宿报价包含税费，入住条件一致")
    ]
