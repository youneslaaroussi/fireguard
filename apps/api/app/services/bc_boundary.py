from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx


BC_BOUNDARY_WFS_URL = (
    "https://openmaps.gov.bc.ca/geo/pub/"
    "WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_PROVINCE_SP/ows"
)
BC_BOUNDARY_WFS_PARAMS = {
    "service": "WFS",
    "version": "2.0.0",
    "request": "GetFeature",
    "typeNames": "pub:WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_PROVINCE_SP",
    "outputFormat": "json",
    "srsName": "EPSG:4326",
}
BC_BOUNDARY_SOURCE_URL = (
    f"{BC_BOUNDARY_WFS_URL}?service=WFS&version=2.0.0&request=GetFeature"
    "&typeNames=pub:WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_PROVINCE_SP"
    "&outputFormat=json&srsName=EPSG:4326"
)


def _rings_from_geometry(geometry: dict[str, Any]) -> list[list[list[float]]]:
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        return [ring for ring in coordinates if ring]
    if geometry.get("type") == "MultiPolygon":
        rings: list[list[list[float]]] = []
        for polygon in coordinates:
            rings.extend(ring for ring in polygon if ring)
        return rings
    return []


@lru_cache(maxsize=1)
def _bc_boundary_rings() -> list[list[list[float]]]:
    response = httpx.get(BC_BOUNDARY_WFS_URL, params=BC_BOUNDARY_WFS_PARAMS, timeout=20)
    response.raise_for_status()
    payload = response.json()
    rings: list[list[list[float]]] = []
    for feature in payload.get("features", []):
        rings.extend(_rings_from_geometry(feature.get("geometry") or {}))
    if not rings:
        raise RuntimeError("BC boundary WFS returned no polygon rings.")
    return rings


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    j = len(ring) - 1
    for i, point in enumerate(ring):
        lon_i, lat_i = float(point[0]), float(point[1])
        lon_j, lat_j = float(ring[j][0]), float(ring[j][1])
        crosses = (lat_i > lat) != (lat_j > lat)
        if crosses:
            denominator = lat_j - lat_i
            if denominator:
                intersect_lon = (lon_j - lon_i) * (lat - lat_i) / denominator + lon_i
                if lon < intersect_lon:
                    inside = not inside
        j = i
    return inside


def _southern_bc_bbox_fallback(lat: float, lon: float) -> bool:
    if not (-139.2 <= lon <= -114.0 and 48.2 <= lat <= 60.1):
        return False
    if lat >= 49.0:
        return True
    return lon <= -123.0


def classify_bc_location(location: dict[str, Any]) -> dict[str, Any]:
    lat = float(location["lat"])
    lon = float(location["lon"])
    try:
        rings = _bc_boundary_rings()
        return {
            "inside": any(_point_in_ring(lon, lat, ring) for ring in rings),
            "method": "official_bc_boundary_wfs",
            "source_url": BC_BOUNDARY_SOURCE_URL,
        }
    except Exception as exc:
        return {
            "inside": _southern_bc_bbox_fallback(lat, lon),
            "method": "southern_bc_bbox_fallback",
            "source_url": BC_BOUNDARY_SOURCE_URL,
            "warning": f"Official BC boundary fetch failed; used conservative bbox fallback: {str(exc)[:300]}",
        }
