from data.eval_world.world import load_world
from scripts.live.capture_phase2_hotels import DEMANDS, PARTIES, ObservedRate, select_hotels


def test_private_world_preserves_missing_quotes_and_meal_changes() -> None:
    station = load_world()[0].stations[0]
    rate = ObservedRate(
        hotel_id=101,
        name="合成旅馆",
        latitude=station.latitude,
        longitude=station.longitude,
        rating=4,
        reviews=20,
        breakfast=True,
        price=9000,
    )
    groups = {
        (demand, party): {(101, True): rate.model_copy(update={"price": 8000 + party * 1000})}
        for demand in DEMANDS
        for party in PARTIES
    }
    groups["event", 2] = {}
    (missing,) = select_hotels(station, groups)
    assert missing.prices_jpy["event"] == (9000, None)
    groups["event", 2][101, False] = rate.model_copy(update={"breakfast": False, "price": 12_000})
    (hotel,) = select_hotels(station, groups)
    assert hotel.prices_jpy["event"] == (9000, 12_000)
    assert hotel.breakfast_by_demand and hotel.breakfast_by_demand["event"] == (True, False)
