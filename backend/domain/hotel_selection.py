"""在既有六报价上限内优先覆盖不同酒店，再保留有限套餐；保持上游顺序。"""

from collections.abc import Sequence

MAX_HOTEL_OFFERS = 6


def hotel_rate_indices(keys: Sequence[tuple[str, str]], limit: int) -> tuple[int, ...]:
    if not 1 <= limit <= MAX_HOTEL_OFFERS:
        raise ValueError("酒店数量必须为1至6")
    hotels: set[str] = set()
    rates: set[tuple[str, str]] = set()
    first: list[int] = []
    for index, (hotel, rate) in enumerate(keys):
        if hotel not in hotels and len(hotels) < limit:
            hotels.add(hotel)
            rates.add((hotel, rate))
            first.append(index)
    counts = dict.fromkeys(hotels, 1)
    picked = first.copy()
    for index, key in enumerate(keys):
        if len(picked) >= MAX_HOTEL_OFFERS:
            break
        hotel, _ = key
        if hotel in hotels and key not in rates and counts[hotel] < 2:
            rates.add(key)
            counts[hotel] += 1
            picked.append(index)
    return tuple(sorted(picked))
