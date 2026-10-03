"""本地虚构房价目录适配器；不查询真实库存，旅行服务复用此处的版本与报价规则。"""

import hashlib
from pathlib import Path

from pydantic import TypeAdapter

from backend.domain.hotels import HotelRate

PATH = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "hotels.json"


def load_rates() -> tuple[tuple[HotelRate, ...], str]:
    raw = PATH.read_text(encoding="utf-8")
    rates = TypeAdapter(tuple[HotelRate, ...]).validate_json(raw)
    if len({rate.rate_id for rate in rates}) != len(rates):
        raise ValueError("模拟报价目录包含重复rate_id")
    return rates, hashlib.sha256(raw.encode("utf-8")).hexdigest()
