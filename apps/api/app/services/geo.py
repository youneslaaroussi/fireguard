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


def _point_segment_distance_km(point: Point, start: Point, end: Point) -> float:
    # Equirectangular projection is accurate enough for short route safety buffers.
    mean_lat = radians((start["lat"] + end["lat"] + point["lat"]) / 3)
    km_per_degree_lat = 111.32
    km_per_degree_lon = 111.32 * cos(mean_lat)
    px = point["lon"] * km_per_degree_lon
    py = point["lat"] * km_per_degree_lat
    ax = start["lon"] * km_per_degree_lon
    ay = start["lat"] * km_per_degree_lat
    bx = end["lon"] * km_per_degree_lon
    by = end["lat"] * km_per_degree_lat
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return haversine_km(point, start)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    nearest = {"lon": (ax + t * dx) / km_per_degree_lon, "lat": (ay + t * dy) / km_per_degree_lat}
    return haversine_km(point, nearest)


def min_distance_to_polyline_km(point: Point, polyline: list[Point]) -> float:
    if not polyline:
        return 9999
    if len(polyline) == 1:
        return haversine_km(point, polyline[0])
    return min(
        _point_segment_distance_km(point, start, end)
        for start, end in zip(polyline, polyline[1:])
    )


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
