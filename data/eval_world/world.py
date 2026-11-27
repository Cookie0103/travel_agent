"""冻结的酒店评测世界与独立的模拟佣金表。"""

import hashlib
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parent
HOTELS_FILE = "synthetic-hotels-v1.json"
COMMISSION_FILE = "synthetic-commission-v1.json"
MANIFEST_FILE = "synthetic-v1.manifest.json"
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
    prices_jpy: dict[Demand, tuple[int, int]]

    @model_validator(mode="after")
    def price_profiles(self) -> Self:
        if set(self.prices_jpy) != {"weekday", "weekend", "event"} or any(
            price <= 0 for pair in self.prices_jpy.values() for price in pair
        ):
            raise ValueError("每家评测酒店须有三种需求日期及一人/两人含税房价")
        return self


class World(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: Literal["synthetic", "rakuten"]
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


def load_world(directory: Path = ROOT) -> tuple[World, dict[str, Commission]]:
    manifest = json.loads((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
    raw = {name: (directory / name).read_bytes() for name in (HOTELS_FILE, COMMISSION_FILE)}
    if manifest["sha256"] != {
        name: hashlib.sha256(content).hexdigest() for name, content in raw.items()
    }:
        raise ValueError("评测酒店世界或模拟佣金表的哈希已变")
    world = World.model_validate_json(raw[HOTELS_FILE])
    commission = {
        key: Commission.model_validate(value)
        for key, value in json.loads(raw[COMMISSION_FILE]).items()
    }
    if commission.keys() != {hotel.hotel_id for hotel in world.hotels}:
        raise ValueError("评测酒店与模拟佣金表的标识不一致")
    return world, commission
