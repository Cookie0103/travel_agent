"""把冻结酒店事实投影到 H2 合成供应商夹具。"""

from datetime import date, timedelta

from backend.adapters.evaluation_world import (
    EvaluationCity,
    EvaluationHotel,
    EvaluationWeather,
    EvaluationWorld,
)
from data.eval_world.world import Commission, Station, World, load_world

type HotelDataset = tuple[World, dict[str, Commission]]

RAIN_STARTS = (
    date(2026, 11, 10),
    date(2026, 11, 27),
    date(2026, 12, 8),
    date(2026, 12, 19),
    date(2027, 1, 9),
)


def _synthetic_hotel(hotel: EvaluationHotel, station: Station, index: int) -> EvaluationHotel:
    # 刻意让低价、早餐、近车站和家庭房有交集，佣金和酒店身份仍来自冻结表。
    base = 6500 + (index - 1) * 590
    near = index <= 4
    family = index in {1, 2, 4, 6}
    weekday, weekend, event = base, base + 750, base + 2200
    return hotel.model_copy(
        update={
            "latitude": round(station.latitude + index * 0.00065, 6) if near else hotel.latitude,
            "longitude": round(station.longitude - index * 0.0005, 6) if near else hotel.longitude,
            "rating": max(hotel.rating, 4.5 if near else 4.3 if index <= 6 else 0.0),
            "breakfast": index <= 6 or hotel.breakfast,
            "prices_jpy": {
                "weekday": (weekday, weekday),
                "weekend": (weekend, weekend),
                "event": (event, event),
            },
            "breakfast_by_demand": None,
            "room_type": "禁煙家庭房（4名）" if family else hotel.room_type,
            "max_guests": 4 if family else 2,
        }
    )


def _cities(world: World, commission: dict[str, Commission]) -> tuple[EvaluationCity, ...]:
    cities = []
    for city_index, station in enumerate(world.stations, 1):
        hotels = []
        for index, hotel in enumerate((h for h in world.hotels if h.city == station.city), 1):
            value = EvaluationHotel(
                number=city_index * 100 + index,
                name=hotel.name,
                latitude=hotel.latitude,
                longitude=hotel.longitude,
                rating=hotel.rating,
                reviews=hotel.reviews,
                breakfast=hotel.breakfast,
                partner=commission[hotel.hotel_id].partner,
                prices_jpy=hotel.prices_jpy,
                breakfast_by_demand=hotel.breakfast_by_demand,
            )
            hotels.append(
                _synthetic_hotel(value, station, index) if world.source == "synthetic" else value
            )
        cities.append(
            EvaluationCity(
                city=station.city,
                latitude=station.latitude,
                longitude=station.longitude,
                hotels=tuple(hotels),
            )
        )
    return tuple(cities)


def phase2_world(
    dataset: HotelDataset | None = None,
    *,
    weather_by_date: dict[date, EvaluationWeather] | None = None,
) -> EvaluationWorld:
    world, commission = dataset if dataset is not None else load_world()
    weather: dict[date, EvaluationWeather] = {}
    if world.source == "synthetic":
        weather = {
            day + timedelta(days=offset): "rain" for day in RAIN_STARTS for offset in range(3)
        }
    weather.update(weather_by_date or {})
    return EvaluationWorld(
        source=world.source,
        today=date(2026, 10, 24),
        weather_by_date=weather,
        synthetic_calendar=world.source == "synthetic",
        cities=_cities(world, commission),
    )
