"""生成有来源坐标的合成酒店世界，不读取供应商数据或环境变量。"""

import hashlib
import json
import random
from collections.abc import Sequence
from pathlib import Path

from data.eval_world.world import (
    COMMISSION_FILE,
    HOTELS_FILE,
    MANIFEST_FILE,
    ROOT,
    Commission,
    Hotel,
    Station,
    World,
)

SEED = 20261127
STATIONS = (
    ("京都", "京都站", 34.985556, 135.758611, "Q801046"),
    ("大阪", "大阪站", 34.702500, 135.496111, "Q801694"),
    ("奈良", "奈良站", 34.680661, 135.819022, "Q1150978"),
    ("東京", "东京站", 35.680833, 139.766944, "Q283196"),
    ("札幌", "札幌站", 43.068611, 141.350778, "Q801404"),
    ("福岡", "博多站", 33.589995, 130.420560, "Q137752767"),
)


def make_hotels(stations: Sequence[Station]) -> tuple[Hotel, ...]:
    rng = random.Random(SEED)
    hotels = []
    for city_index, station in enumerate(stations):
        for index in range(16):
            base = (6800 + (city_index % 4) * 700 + index * 580 + rng.randrange(0, 1200)) // 10 * 10
            guests = 1500 + rng.randrange(0, 2000, 50)
            weekend = 1300 + (index % 5) * 390
            demand = 2900 + (index % 7) * 510
            hotels.append(
                Hotel(
                    hotel_id=f"synthetic:{city_index + 1}:{index + 1:02}",
                    city=station.city,
                    name=f"合成{station.city}酒店{index + 1:02}",
                    latitude=round(station.latitude + rng.uniform(-0.018, 0.018), 6),
                    longitude=round(station.longitude + rng.uniform(-0.018, 0.018), 6),
                    rating=round(rng.uniform(3.25, 4.85), 2),
                    reviews=rng.randrange(12, 2100),
                    breakfast=index % 3 != 0,
                    prices_jpy={
                        "weekday": (base, base + guests),
                        "weekend": (base + weekend, base + weekend + guests),
                        "event": (base + demand, base + demand + guests),
                    },
                )
            )
    return tuple(hotels)


def generate(output: Path = ROOT) -> None:
    stations = tuple(
        Station(
            city=city,
            name=name,
            latitude=lat,
            longitude=lon,
            source=f"https://www.wikidata.org/wiki/{entity}",
        )
        for city, name, lat, lon, entity in STATIONS
    )
    hotels = make_hotels(stations)
    world = World(source="synthetic", stations=stations, hotels=hotels)
    commissions = {}
    for index, hotel in enumerate(hotels):
        partner = index % 4 == 0
        seed = hashlib.sha256(f"{SEED}/{hotel.hotel_id}".encode()).digest()
        base = 800 + int.from_bytes(seed[:4], "big") % 401
        commissions[hotel.hotel_id] = Commission(
            partner=partner, basis_points=base + (300 if partner else 0)
        )
    documents = {
        HOTELS_FILE: world.model_dump(mode="json"),
        COMMISSION_FILE: {key: value.model_dump(mode="json") for key, value in commissions.items()},
    }
    versions = {}
    for name, content in documents.items():
        data = (json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        (output / name).write_bytes(data)
        versions[name] = hashlib.sha256(data).hexdigest()
    manifest = {"seed": SEED, "source": "synthetic", "live_calls": 0, "sha256": versions}
    (output / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    generate()
