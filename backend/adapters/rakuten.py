"""乐天空室查询：逐晚核对同一酒店/计划/房型，不推算缺失价格。"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, JsonValue

from backend.adapters.external_api import ApiUsage, parse_response, request_json
from backend.domain.external_data import ExternalDataError, GeoPoint
from backend.domain.hotels import HotelOffer, Money
from backend.domain.travel_request import TravelRequest


class Basic(BaseModel):
    hotelNo: int
    hotelName: str
    hotelInformationUrl: str
    planListUrl: str | None = None
    hotelImageUrl: str | None = None
    reviewAverage: float | None = None


class Room(BaseModel):
    roomClass: str
    roomName: str
    planId: int | str | None = None
    reserveUrl: str | None = None
    withBreakfastFlag: int | None = None


class Charge(BaseModel):
    stayDate: date
    rakutenCharge: Money
    chargeFlag: int = Field(ge=0, le=1)


class Candidate(BaseModel):
    hotel: Basic
    room: Room
    charge: Charge | None

    @property
    def key(self) -> str:
        return f"rakuten:{self.hotel.hotelNo}:{self.room.planId}:{self.room.roomClass}"


def components(value: JsonValue) -> dict[str, JsonValue]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {key: item for part in value if isinstance(part, dict) for key, item in part.items()}
    raise ExternalDataError("乐天响应结构无效")


def candidates(payload: dict[str, JsonValue]) -> tuple[Candidate, ...]:
    hotels = payload.get("hotels")
    if not isinstance(hotels, list):
        raise ExternalDataError("乐天响应缺少酒店列表")
    result = []
    for entry in hotels:
        fields = components(entry)
        if "hotel" in fields:
            fields = components(fields["hotel"])
        basic = parse_response(Basic, fields.get("hotelBasicInfo"))
        rooms = fields.get("roomInfo", [])
        if not isinstance(rooms, list):
            raise ExternalDataError("乐天响应房型列表无效")
        # v2 roomInfo 是一个房型的字段数组，或多个这样的数组。
        groups = (
            [rooms]
            if any(isinstance(item, dict) and "roomBasicInfo" in item for item in rooms)
            else rooms
        )
        for group in groups:
            parts = components(group)
            room = parse_response(Room, parts.get("roomBasicInfo"))
            daily = parts.get("dailyCharge")
            if isinstance(daily, list):
                daily = daily[0] if daily else None
            result.append(
                Candidate(
                    hotel=basic, room=room, charge=parse_response(Charge, daily) if daily else None
                )
            )
    return tuple(result)


class Rakuten:
    def __init__(
        self,
        app_id: str,
        access_key: str,
        affiliate_id: str,
        referer: str,
        http: httpx.AsyncClient,
        usage: ApiUsage,
    ) -> None:
        self.app_id, self.access_key, self.affiliate_id = app_id, access_key, affiliate_id
        self.referer, self.http, self.usage = referer, http, usage

    async def nightly(
        self, request: TravelRequest, day: date, point: GeoPoint, hotel_ids: tuple[int, ...] = ()
    ) -> tuple[Candidate, ...]:
        assert request.adults and request.rooms
        params: dict[str, str | int | float] = {
            "applicationId": self.app_id,
            "format": "json",
            "formatVersion": 2,
            "checkinDate": day.isoformat(),
            "checkoutDate": (day + timedelta(days=1)).isoformat(),
            "adultNum": max(1, request.adults // request.rooms),
            "roomNum": request.rooms,
            "datumType": 1,
            "hits": 10,
            "responseType": "large",
            "searchPattern": 1,
        }
        if hotel_ids:
            params["hotelNo"] = ",".join(map(str, hotel_ids[:15]))
        else:
            params.update(latitude=point.latitude, longitude=point.longitude, searchRadius=3)
        if self.affiliate_id:
            params["affiliateId"] = self.affiliate_id
        headers = {"accessKey": self.access_key}
        if self.referer:
            headers["Referer"] = self.referer
            site = urlsplit(self.referer)
            headers["Origin"] = f"{site.scheme}://{site.netloc}"
        return candidates(
            await request_json(
                self.http,
                self.usage,
                "rakuten",
                "GET",
                "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426",
                params=params,
                headers=headers,
                empty_404=True,
            )
        )

    async def search(
        self,
        request: TravelRequest,
        point: GeoPoint,
        *,
        hotel_id: str | None = None,
        rate_id: str | None = None,
        limit: int = 4,
    ) -> tuple[HotelOffer, ...]:
        assert request.start_date and request.end_date and request.adults and request.rooms
        nights = (request.end_date - request.start_date).days
        if self.usage.default_profile:  # 其他档位按配置的run_caps原值
            self.usage.run_caps["rakuten"] = min(8, nights + 1)
        if point.broad:
            raise ExternalDataError(
                "目的地区域过大；酒店只能查询中心3公里，请先指定具体城市或住宿地点", validation=True
            )
        selected_id = hotel_id or (
            rate_id.split(":")[1] if rate_id and rate_id.startswith("rakuten:") else None
        )
        if selected_id and not selected_id.isdecimal():
            raise ExternalDataError("酒店ID无效", validation=True)
        first = await self.nightly(
            request, request.start_date, point, (int(selected_id),) if selected_id else ()
        )
        selected = tuple(
            item
            for item in first
            if (not hotel_id or str(item.hotel.hotelNo) == hotel_id)
            and (not rate_id or item.key == rate_id)
        )[:limit]
        reason = (
            "儿童计价未知"
            if request.child_ages
            else "超过7晚，不核算总价"
            if nights > 7
            else "成人无法平均分配到每间房"
            if request.adults % request.rooms
            else None
        )
        totals: dict[str, Decimal | None] = {
            item.key: self.price(item, request, request.start_date) if not reason else None
            for item in selected
        }
        if selected and not reason:
            hotel_ids = tuple(dict.fromkeys(item.hotel.hotelNo for item in selected))
            for offset in range(1, nights):
                day = request.start_date + timedelta(days=offset)
                nightly = {
                    item.key: item for item in await self.nightly(request, day, point, hotel_ids)
                }
                for item in selected:
                    value = (
                        self.price(nightly[item.key], request, day) if item.key in nightly else None
                    )
                    previous = totals[item.key]
                    totals[item.key] = (
                        previous + value if previous is not None and value is not None else None
                    )
        now = datetime.now(UTC)
        return tuple(
            HotelOffer(
                rate_id=item.key,
                hotel_id=str(item.hotel.hotelNo),
                hotel_name=item.hotel.hotelName,
                room_type=item.room.roomName,
                currency="JPY",
                request=request,
                base_amount=totals[item.key] or Decimal(0),
                tax_amount=None,
                fee_amount=None,
                included_total=totals[item.key],
                total_reason=reason
                or (
                    "部分晚数缺少同计划同房型报价，完整总价未知"
                    if totals[item.key] is None
                    else None
                ),
                breakfast=None
                if item.room.withBreakfastFlag is None
                else item.room.withBreakfastFlag == 1,
                refundable=None,
                quoted_at=now,
                expires_at=now + timedelta(minutes=15),
                image_url=item.hotel.hotelImageUrl,
                review_average=item.hotel.reviewAverage,
                booking_url=item.room.reserveUrl
                or item.hotel.planListUrl
                or item.hotel.hotelInformationUrl,
                data_mode="live",
            )
            for item in selected
        )

    @staticmethod
    def price(item: Candidate, request: TravelRequest, day: date) -> Decimal | None:
        charge = item.charge
        if not charge or charge.stayDate != day or item.room.planId is None:
            return None
        return charge.rakutenCharge * (
            (request.adults or 0) if charge.chargeFlag == 0 else (request.rooms or 0)
        )
