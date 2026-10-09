"""乐天空室查询：逐晚核对同一酒店/计划/房型，不推算缺失价格。"""

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, JsonValue

from backend.adapters.external_api import ApiUsage, parse_response, request_json
from backend.domain.external_data import ExternalDataError, GeoPoint
from backend.domain.hotel_details import StoredHotelDetails
from backend.domain.hotel_selection import hotel_rate_indices
from backend.domain.hotels import HotelOffer, Money
from backend.domain.room_choices import recognized_room_choices
from backend.domain.room_preferences import room_assessment, room_order
from backend.domain.travel_request import TravelRequest
from backend.profile import current


class Basic(BaseModel):
    hotelNo: int
    hotelName: str
    hotelInformationUrl: str | None = None
    planListUrl: str | None = None
    hotelImageUrl: str | None = None
    reviewAverage: float | None = None
    address1: str | None = None
    address2: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    reviewCount: int | None = Field(default=None, ge=0)


class Detail(BaseModel):
    middleClassCode: str | None = None
    smallClassCode: str | None = None


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


# 判断题：低于该每人每晚价格的套餐视为促销/测试价（实测出现过¥1、¥500），不当真实价格；
# 取值依据与可调整性见 ADR-016。
MIN_PERSON_NIGHT_PRICE = Decimal(1000)
SHOWN_PLAN_LABEL = "乐天返回的该酒店符合条件的套餐中最低价"
DESTINATION_HOST = "travel.rakuten.co.jp"


class Candidate(BaseModel):
    hotel: Basic
    room: Room
    charge: Charge | None
    detail: Detail | None = None

    @property
    def key(self) -> str:
        return f"rakuten:{self.hotel.hotelNo}:{self.room.planId}:{self.room.roomClass}"


def components(value: JsonValue) -> dict[str, JsonValue]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {key: item for part in value if isinstance(part, dict) for key, item in part.items()}
    raise ExternalDataError("乐天响应结构无效")


def split_rooms(rooms: list[JsonValue]) -> list[JsonValue]:
    groups: list[JsonValue] = []
    for item in rooms:
        if isinstance(item, dict) and "roomBasicInfo" in item:
            groups.append([item])
        elif groups and isinstance(groups[-1], list):
            groups[-1].append(item)
    return groups


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
        # v2 roomInfo 是一个房型的字段数组，或多个这样的数组；平铺时每个roomBasicInfo开启新房型。
        groups = (
            split_rooms(rooms)
            if any(isinstance(item, dict) and "roomBasicInfo" in item for item in rooms)
            else rooms
        )
        detail = fields.get("hotelDetailInfo")
        try:  # 仅用于可选的“查看更多”入口，格式异常不应使整个搜索失败
            area = parse_response(Detail, detail) if isinstance(detail, dict) else None
        except ExternalDataError:
            area = None
        for group in groups:
            parts = components(group)
            room = parse_response(Room, parts.get("roomBasicInfo"))
            daily = parts.get("dailyCharge")
            if isinstance(daily, list):
                daily = daily[0] if daily else None
            result.append(
                Candidate(
                    hotel=basic,
                    room=room,
                    charge=parse_response(Charge, daily) if daily else None,
                    detail=area,
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

    async def query(
        self,
        request: TravelRequest,
        day: date,
        point: GeoPoint,
        hotel_ids: tuple[int, ...] = (),
        *,
        by_plan: bool = False,
    ) -> tuple[tuple[Candidate, ...], int | None]:
        """by_plan=False按施設(searchPattern=0)每家一条；by_plan=True只用于单个酒店，列出其套餐。

        不变量：pattern 1按套餐计数，按地点查询时一页只是全城最便宜的30个套餐（含¥1促销与宿舍），
        所以按地点发现酒店必须用pattern 0（P-81）。squeezeCondition=kinen实测在房型/套餐级过滤
        （同一套餐的吸烟房型被换成禁烟房型并去掉无禁烟房的酒店，见ADR-016），逐晚复查也要带上，
        否则roomClass不同会让同一套餐匹配不上。
        """
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
            "hits": 30,
            "responseType": "large",
            "searchPattern": 1 if by_plan else 0,
            "sort": "standard",
        }
        if "房型：禁烟" in recognized_room_choices(request.hard_constraints):
            params["squeezeCondition"] = "kinen"
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
        payload = await request_json(
            self.http,
            self.usage,
            "rakuten",
            "GET",
            "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426",
            params=params,
            headers=headers,
            empty_404=True,
        )
        paging = payload.get("pagingInfo")
        count = paging.get("recordCount") if isinstance(paging, dict) else None
        return candidates(payload), count if isinstance(count, int) and count >= 0 else None

    async def nightly(
        self,
        request: TravelRequest,
        day: date,
        point: GeoPoint,
        hotel_ids: tuple[int, ...] = (),
        *,
        by_plan: bool = False,
    ) -> tuple[Candidate, ...]:
        return (await self.query(request, day, point, hotel_ids, by_plan=by_plan))[0]

    async def search(
        self,
        request: TravelRequest,
        point: GeoPoint,
        *,
        hotel_id: str | None = None,
        rate_id: str | None = None,
        limit: int = 5,
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
        by_plan = selected_id is not None
        first, found = await self.query(
            request,
            request.start_date,
            point,
            (int(selected_id),) if selected_id else (),
            by_plan=by_plan,
        )
        if by_plan:
            selected = tuple(
                item
                for item in first
                if (not hotel_id or str(item.hotel.hotelNo) == hotel_id)
                and (not rate_id or item.key == rate_id)
                and not self.price_unreliable(item, request)
            )
            selected = tuple(
                selected[index]
                for index in room_order([item.room.roomName for item in selected], request)
            )
            selected = tuple(
                selected[index]
                for index in hotel_rate_indices(
                    [(str(item.hotel.hotelNo), item.key) for item in selected], limit
                )
            )
        else:
            selected = self.lowest_per_hotel(first, request)[:limit]
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
                    item.key: item
                    for item in await self.nightly(request, day, point, hotel_ids, by_plan=by_plan)
                }
                for item in selected:
                    # 后几晚同样不接受促销价，否则会把总价低估。
                    value = (
                        self.price(nightly[item.key], request, day)
                        if item.key in nightly
                        and not self.price_unreliable(nightly[item.key], request)
                        else None
                    )
                    previous = totals[item.key]
                    totals[item.key] = (
                        previous + value if previous is not None and value is not None else None
                    )
        now = datetime.now(UTC)
        more_url = None if by_plan else self.destination_url(first)
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
                expires_at=now + timedelta(minutes=current().evidence_ttl_minutes),
                image_url=item.hotel.hotelImageUrl,
                review_average=item.hotel.reviewAverage,
                booking_url=item.room.reserveUrl
                or item.hotel.planListUrl
                or item.hotel.hotelInformationUrl,
                display_details=StoredHotelDetails(
                    hotel_info_url=item.hotel.hotelInformationUrl,
                    plan_list_url=item.hotel.planListUrl,
                    reservation_url=item.room.reserveUrl,
                    address=(item.hotel.address1 or "") + (item.hotel.address2 or "") or None,
                    latitude=item.hotel.latitude,
                    longitude=item.hotel.longitude,
                    review_count=item.hotel.reviewCount,
                    price_basis=None if by_plan else SHOWN_PLAN_LABEL,
                    search_total_found=None if by_plan else found,
                    more_url=more_url,
                    more_url_scope="destination" if more_url else None,
                ),
                data_mode="live",
            )
            for item in selected
        )

    @staticmethod
    def price_unreliable(item: Candidate, request: TravelRequest) -> bool:
        """每人每晚低于下限的第一晚价格视为促销价；未知价格不在此判断，也不补0。"""
        charge = item.charge
        if charge is None:
            return False
        assert request.adults and request.rooms
        per_person = (
            charge.rakutenCharge
            if charge.chargeFlag == 0
            else charge.rakutenCharge / max(1, request.adults // request.rooms)
        )
        return per_person < MIN_PERSON_NIGHT_PRICE

    @classmethod
    def lowest_per_hotel(
        cls, items: tuple[Candidate, ...], request: TravelRequest
    ) -> tuple[Candidate, ...]:
        """每家酒店取资格合格且价格可信的最低价套餐，酒店按上游顺序；无合格套餐的酒店不展示。"""
        best: dict[int, tuple[tuple[bool, Decimal], Candidate]] = {}
        for item in items:
            price = cls.price(item, request, item.charge.stayDate) if item.charge else None
            assessment = room_assessment(item.room.roomName, request)
            if (
                price is None
                or assessment.room_preference_mismatch
                or cls.price_unreliable(item, request)
            ):
                continue
            rank = (assessment.qualification_unknown, price)
            current = best.get(item.hotel.hotelNo)
            if current is None or rank < current[0]:
                best[item.hotel.hotelNo] = (rank, item)
        # dict保持首次出现顺序即上游酒店顺序；资格未核实的酒店由room_order稳定排后。
        chosen = tuple(
            best[no][1] for no in dict.fromkeys(i.hotel.hotelNo for i in items) if no in best
        )
        return tuple(chosen[i] for i in room_order([c.room.roomName for c in chosen], request))

    @staticmethod
    def destination_url(items: tuple[Candidate, ...]) -> str | None:
        """乐天区域页入口：只由接口返回的区域代码拼出，不带日期/人数/追踪参数（ADR-016）。"""
        detail = next((item.detail for item in items if item.detail), None)
        if (
            detail is None
            or not detail.middleClassCode
            or not detail.smallClassCode
            or not re.fullmatch(r"[a-z0-9]+", detail.middleClassCode)
            or not re.fullmatch(r"[a-z0-9]+", detail.smallClassCode)
        ):
            return None
        return (
            f"https://{DESTINATION_HOST}/yado/{detail.middleClassCode}/{detail.smallClassCode}.html"
        )

    @staticmethod
    def price(item: Candidate, request: TravelRequest, day: date) -> Decimal | None:
        charge = item.charge
        if not charge or charge.stayDate != day or item.room.planId is None:
            return None
        return charge.rakutenCharge * (
            (request.adults or 0) if charge.chargeFlag == 0 else (request.rooms or 0)
        )
