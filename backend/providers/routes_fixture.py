"""读取自制双向路段表；缺覆盖返回unknown，金额只作全员估算而非真实票价。"""

import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from backend.domain.itinerary import RouteEstimate
from backend.domain.travel_request import TravelRequest

PATH = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "routes.json"


class RouteRate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    endpoints: tuple[str, str]
    transport: Literal["walk", "transit", "taxi"]
    minutes: int = Field(strict=True, ge=1, le=1440)
    fare_per_person: Decimal = Field(ge=0, max_digits=8, decimal_places=2)


def load_routes() -> tuple[tuple[RouteRate, ...], str]:
    content = PATH.read_bytes()
    rates = TypeAdapter(tuple[RouteRate, ...]).validate_json(content)
    keys = {(frozenset(rate.endpoints), rate.transport) for rate in rates}
    if len(keys) != len(rates) or any(len(set(rate.endpoints)) != 2 for rate in rates):
        raise ValueError("路段表不能重复或引用同一端点")
    return rates, hashlib.sha256(content).hexdigest()


def estimate(
    rates: tuple[RouteRate, ...], request: TravelRequest, start: str, end: str, departure: datetime
) -> RouteEstimate:
    if request.transport is None:
        raise ValueError("交通方式需要用户确认")
    rate = next(
        (r for r in rates if set(r.endpoints) == {start, end} and r.transport == request.transport),
        None,
    )
    people = (
        request.adults + len(request.child_ages)
        if request.adults is not None and request.child_ages is not None
        else None
    )
    fare = None
    if rate:
        if rate.fare_per_person == 0:
            fare = Decimal(0)
        elif people is not None:
            fare = rate.fare_per_person * people
    return RouteEstimate(
        from_place_id=start,
        to_place_id=end,
        transport=request.transport,
        departure=departure,
        minutes=rate.minutes if rate else None,
        fare=fare,
        confidence="estimate" if rate else "unknown",
    )
