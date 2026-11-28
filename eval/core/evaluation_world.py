"""把冻结酒店世界投影到现有隔离供应商夹具。"""

from datetime import date

from backend.adapters.evaluation_world import (
    EvaluationCity,
    EvaluationHotel,
    EvaluationWeather,
    EvaluationWorld,
)
from data.eval_world.world import Commission, World, load_world

type HotelDataset = tuple[World, dict[str, Commission]]


def phase2_world(
    dataset: HotelDataset | None = None,
    *,
    weather_by_date: dict[date, EvaluationWeather] | None = None,
) -> EvaluationWorld:
    world, commission = dataset if dataset is not None else load_world()
    return EvaluationWorld(
        source=world.source,
        today=date(2026, 10, 24),
        weather_by_date=weather_by_date or {},
        cities=tuple(
            EvaluationCity(
                city=station.city,
                latitude=station.latitude,
                longitude=station.longitude,
                hotels=tuple(
                    EvaluationHotel(
                        number=city_index * 100 + hotel_index,
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
                    for hotel_index, hotel in enumerate(
                        (h for h in world.hotels if h.city == station.city), 1
                    )
                ),
            )
            for city_index, station in enumerate(world.stations, 1)
        ),
    )
