"""冻结的酒店评测世界与独立的模拟佣金表。"""

import hashlib
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parent
WorldSource = Literal["synthetic", "rakuten"]
Demand = Literal["weekday", "weekend", "event"]


class Station(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    city: str
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    source: str


class Hotel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    hotel_id: str
    city: str
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    rating: float = Field(ge=0, le=5)
    reviews: int = Field(ge=0)
    breakfast: bool
    prices_jpy: dict[Demand, tuple[int | None, int | None]]
    breakfast_by_demand: dict[Demand, tuple[bool | None, bool | None]] | None = Field(
        default=None, exclude_if=lambda items: items is None
    )

    @model_validator(mode="after")
    def price_profiles(self) -> Self:
        if set(self.prices_jpy) != {"weekday", "weekend", "event"} or any(
            price is not None and price <= 0 for pair in self.prices_jpy.values() for price in pair
        ):
            raise ValueError("每家评测酒店须列三种需求日期的整数日元房价或空报价")
        if self.breakfast_by_demand is not None:
            if self.prices_jpy.keys() != self.breakfast_by_demand.keys() or any(
                (price is None) != (breakfast is None)
                for demand, pair in self.prices_jpy.items()
                for price, breakfast in zip(pair, self.breakfast_by_demand[demand], strict=True)
            ):
                raise ValueError("餐食应与对应报价同时出现")
        return self

    def weekday_quote(self) -> tuple[int, bool] | None:
        price = self.prices_jpy["weekday"][0]
        if price is None:
            return None
        breakfast = self.breakfast_by_demand["weekday"][0] if self.breakfast_by_demand else None
        return price, self.breakfast if breakfast is None else breakfast


class World(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: WorldSource
    stations: tuple[Station, ...]
    hotels: tuple[Hotel, ...]

    @model_validator(mode="after")
    def check_cities(self) -> Self:
        cities = {station.city for station in self.stations}
        if len(cities) != 6 or len({hotel.hotel_id for hotel in self.hotels}) != len(self.hotels):
            raise ValueError("评测世界须含六城，酒店标识不可重复")
        if {hotel.city for hotel in self.hotels} != cities or any(
            not 12 <= sum(hotel.city == city for hotel in self.hotels) <= 20 for city in cities
        ):
            raise ValueError("每座城市须有 12 到 20 家酒店")
        for city in cities:
            hotels = [hotel for hotel in self.hotels if hotel.city == city]
            for demand in ("weekday", "weekend", "event"):
                for party in (0, 1):
                    count = sum(hotel.prices_jpy[demand][party] is not None for hotel in hotels)
                    if count < (len(hotels) if self.source == "synthetic" else 12):
                        raise ValueError("每城各日期及人数的已知报价未达最低覆盖")
        return self


class Commission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    partner: bool
    basis_points: int

    @model_validator(mode="after")
    def check_range(self) -> Self:
        offset = 300 if self.partner else 0
        if not 800 <= self.basis_points - offset <= 1200:
            raise ValueError("模拟佣金不在设计区间")
        return self


def world_files(source: WorldSource) -> tuple[str, str, str]:
    return f"{source}-hotels-v1.json", f"{source}-commission-v1.json", f"{source}-v1.manifest.json"


def load_world(
    directory: Path = ROOT, *, source: WorldSource = "synthetic"
) -> tuple[World, dict[str, Commission]]:
    hotels_file, commission_file, manifest_file = world_files(source)
    manifest = json.loads((directory / manifest_file).read_text(encoding="utf-8"))
    raw = {name: (directory / name).read_bytes() for name in (hotels_file, commission_file)}
    if manifest["sha256"] != {
        name: hashlib.sha256(content).hexdigest() for name, content in raw.items()
    }:
        raise ValueError("评测酒店世界或模拟佣金表的哈希已变")
    world = World.model_validate_json(raw[hotels_file])
    if world.source != source or manifest["source"] != source:
        raise ValueError("酒店评测世界的来源不一致")
    commission = {
        key: Commission.model_validate(value)
        for key, value in json.loads(raw[commission_file]).items()
    }
    if commission.keys() != {hotel.hotel_id for hotel in world.hotels}:
        raise ValueError("评测酒店与模拟佣金表的标识不一致")
    return world, commission
