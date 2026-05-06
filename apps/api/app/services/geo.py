from math import asin, cos, radians, sin, sqrt
from typing import Iterable

Point = dict[str, float]


def haversine_km(a: Point, b: Point) -> float:
    radius_km = 6371.0
    d_lat = radians(b["lat"] - a["lat"])
    d_lon = radians(b["lon"] - a["lon"])
    lat1 = radians(a["lat"])
    lat2 = radians(b["lat"])
    h = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    return 2 * radius_km * asin(sqrt(h))


def centroid(points: Iterable[Point]) -> Point:
    pts = list(points)
    return {
        "lat": sum(point["lat"] for point in pts) / len(pts),
        "lon": sum(point["lon"] for point in pts) / len(pts),
    }


def min_distance_to_polyline_km(point: Point, polyline: list[Point]) -> float:
    if not polyline:
        return 9999
    return min(haversine_km(point, vertex) for vertex in polyline)


def route_near_point(route: list[Point], point: Point, threshold_km: float) -> bool:
    return min_distance_to_polyline_km(point, route) <= threshold_km


def point_in_bbox(point: Point, bbox: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox
    return west <= point["lon"] <= east and south <= point["lat"] <= north


def bbox_from_points(points: Iterable[Point], padding_degrees: float = 0.08) -> tuple[float, float, float, float]:
    pts = list(points)
    return (
        min(point["lon"] for point in pts) - padding_degrees,
        min(point["lat"] for point in pts) - padding_degrees,
        max(point["lon"] for point in pts) + padding_degrees,
        max(point["lat"] for point in pts) + padding_degrees,
    )
