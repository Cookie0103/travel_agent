"""有界酒店诊断与预算档位；金额只来自核实完整的报价，不修改用户条件。"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.travel_request import TravelRequest

if TYPE_CHECKING:
    from backend.domain.hotels import HotelOffer


class HotelSearchDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    upstream_count: int | None = Field(default=None, ge=0)
    count_basis: str = "ASSUMED：上游 recordCount 按酒店计数；过滤数按返回房型计数"
    dropped_room: int = Field(default=0, ge=0)
    dropped_unknown_price: int = Field(default=0, ge=0)
    dropped_min_price: int = Field(default=0, ge=0)
    in_budget: int = Field(default=0, ge=0)
    over_budget: int = Field(default=0, ge=0)
    original_upper: Decimal | None = None
    applied_upper: Decimal | None = None
    tier: Decimal | None = None
    steps: list[str] = Field(default_factory=list)
    cause: Literal["coverage", "budget", "room_filter", "upstream_empty", "unknown_prices"] = (
        "upstream_empty"
    )
    skipped: Literal["quota", "deadline"] | None = None
    message: str = ""


def nightly_upper(request: TravelRequest) -> Decimal | None:
    lodging = request.lodging_budget
    if lodging is None or request.lodging_budget_unlimited or lodging.currency != request.currency:
        return None
    upper = lodging.amount.upper
    if upper is None or lodging.basis == "per_room_night":
        return upper
    if request.start_date is None or request.end_date is None or request.rooms is None:
        return None
    units = (request.end_date - request.start_date).days * request.rooms
    return upper / units if units > 0 else None


def nightly_price(offer: HotelOffer) -> Decimal | None:
    request = offer.request
    if offer.total is None or not request.start_date or not request.end_date or not request.rooms:
        return None
    units = (request.end_date - request.start_date).days * request.rooms
    return offer.total / units if units > 0 else None


def evaluate(
    offers: tuple[HotelOffer, ...],
    request: TravelRequest,
    diagnosis: HotelSearchDiagnostics,
    *,
    limit: int,
) -> tuple[HotelOffer, ...]:
    upper = nightly_upper(request)
    diagnosis.original_upper = upper
    priced = [(offer, nightly_price(offer)) for offer in offers]
    qualified = [
        (offer, price)
        for offer, price in priced
        if price is not None and offer.currency == request.currency
    ]
    within = [offer for offer, price in qualified if upper is None or price <= upper]
    diagnosis.in_budget = len(within) if upper is not None else 0
    diagnosis.over_budget = len(qualified) - len(within) if upper is not None else 0
    diagnosis.tier, diagnosis.applied_upper = None, None
    recovered = (
        "price_sorted_requery" in diagnosis.steps or "price_sorted_fixture" in diagnosis.steps
    )
    if upper is None or within:
        diagnosis.cause = (
            "coverage" if recovered and within else "budget" if upper else "unknown_prices"
        )
        selected = (
            offers if upper is None else tuple(within) + tuple(o for o in offers if o not in within)
        )
    elif qualified:
        diagnosis.cause = "budget"
        selected = offers
        if recovered and diagnosis.skipped is None:
            for tier in (Decimal("1.5"), Decimal(2), Decimal(3)):
                diagnosis.steps.append("tier_" + str(tier))
                candidates = [o for o, price in qualified if price <= upper * tier]
                if candidates:
                    diagnosis.tier, diagnosis.applied_upper = tier, upper * tier
                    selected = tuple(
                        sorted(candidates, key=lambda o: nightly_price(o) or Decimal(0))
                    )[:3]
                    break
            else:
                selected = ()
    else:
        diagnosis.cause = (
            "unknown_prices"
            if offers or diagnosis.dropped_unknown_price
            else "room_filter"
            if diagnosis.dropped_room
            else "upstream_empty"
        )
        selected = offers
    scope = (
        f"{request.hotel_search_location or request.city}中心3km，"
        f"{request.start_date}至{request.end_date}，{request.adults}成人、"
        f"{len(request.child_ages or ())}儿童、{request.rooms}间房"
    )
    found = diagnosis.upstream_count if diagnosis.upstream_count is not None else "未知数量"
    counts = (
        f"上游返回{found}；"
        f"房型不符{diagnosis.dropped_room}、价格未知{diagnosis.dropped_unknown_price}、"
        f"异常低价{diagnosis.dropped_min_price}；预算内{diagnosis.in_budget}、超预算{diagnosis.over_budget}。"
    )
    explanation = (
        f"原每间每晚上限¥{upper}下没有合格候选；已查看¥{diagnosis.applied_upper}档的真实报价，请确认是否接受（全程所有住宿段共用）。"
        if diagnosis.tier is not None
        else "价格升序重查找到了预算内报价，原排序第一页覆盖不足，预算保持原样。"
        if diagnosis.cause == "coverage"
        else (
            f"已检查至原上限3倍（¥{upper * 3}），仍没有符合条件的完整报价；可以换日期、区域或房型。"
        )
        if upper is not None and "tier_3" in diagnosis.steps
        else "请参考房型与完整价格的核实状态；可以调整日期、区域或房型。"
    )
    diagnosis.message = (
        scope
        + "："
        + counts
        + explanation
        + (f"已尝试：{'、'.join(diagnosis.steps)}。" if diagnosis.steps else "")
        + (f"自救因{diagnosis.skipped}跳过。" if diagnosis.skipped else "")
    )
    return selected[:limit]
