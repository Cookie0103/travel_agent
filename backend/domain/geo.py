"""经纬度之间的球面距离。"""

from math import asin, cos, radians, sin, sqrt


def haversine_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    north = radians(lat_b - lat_a)
    east = radians(lon_b - lon_a)
    angle = sin(north / 2) ** 2 + (cos(radians(lat_a)) * cos(radians(lat_b)) * sin(east / 2) ** 2)
    return 2 * 6_371_000 * asin(sqrt(min(1.0, angle)))
