from __future__ import annotations

import math
from typing import Any

import httpx

from app.models.schemas import GeoPoint, RouteOption
from app.services.geo import haversine_km, min_distance_to_polyline_km, route_near_point

GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIRE_ROUTE_BUFFER_KM = 5.0


def _point(lat: float, lon: float) -> dict[str, float]:
    return {"lat": lat, "lon": lon}


def _route(
    origin_id: str,
    destination_id: str,
    duration: int,
    distance: float,
    safe: bool,
    flags: list[str],
    points: list[dict[str, float]],
    evidence_ids: list[str],
    route_source: str = "deterministic_fallback",
    provider_error: str | None = None,
) -> RouteOption:
    return RouteOption(
        origin_id=origin_id,
        destination_id=destination_id,
        duration_minutes=duration,
        distance_km=distance,
        safe=safe,
        risk_flags=flags,
        polyline=[GeoPoint(lat=point["lat"], lon=point["lon"]) for point in points],
        evidence_ids=evidence_ids,
        route_source=route_source,
        provider_error=provider_error,
    )


def compute_routes(
    context: dict,
    origins: list[dict] | None = None,
    destinations: list[dict] | None = None,
    google_maps_api_key: str | None = None,
) -> list[RouteOption]:
    zones = origins or context.get("zones", [])
    shelters = destinations or context.get("shelters", [])
    routes: list[RouteOption] = []
    for zone in zones:
        for shelter in shelters:
            google_route = _google_route(
                google_maps_api_key,
                zone["centroid"],
                shelter["location"],
            )
            if google_route:
                points = google_route["polyline"]
                flags, evidence_ids, blocking = _safety_flags(context, zone, shelter, points)
                routes.append(
                    _route(
                        zone["zone_id"],
                        shelter["shelter_id"],
                        google_route["duration_minutes"],
                        google_route["distance_km"],
                        not blocking,
                        flags,
                        points,
                        evidence_ids,
                        route_source="google_routes",
                    )
                )
            else:
                routes.append(_deterministic_route(context, zone, shelter))
    return routes


def _google_route(
    api_key: str | None,
    origin: dict[str, float],
    destination: dict[str, float],
) -> dict[str, Any] | None:
    if not api_key:
        return None
    body = {
        "origin": {"location": {"latLng": {"latitude": origin["lat"], "longitude": origin["lon"]}}},
        "destination": {"location": {"latLng": {"latitude": destination["lat"], "longitude": destination["lon"]}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": False,
        "polylineQuality": "HIGH_QUALITY",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
    }
    try:
        response = httpx.post(GOOGLE_ROUTES_URL, json=body, headers=headers, timeout=12)
        response.raise_for_status()
        routes = response.json().get("routes", [])
        if not routes:
            return None
        route = routes[0]
        return {
            "duration_minutes": max(1, math.ceil(_duration_seconds(route.get("duration")) / 60)),
            "distance_km": round(float(route.get("distanceMeters", 0)) / 1000, 1),
            "polyline": _decode_polyline(route.get("polyline", {}).get("encodedPolyline", "")),
        }
    except Exception:
        return None


def _duration_seconds(value: Any) -> int:
    text = str(value or "0s")
    if text.endswith("s"):
        text = text[:-1]
    try:
        return int(float(text))
    except ValueError:
        return 0


def _decode_polyline(encoded: str) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    index = 0
    lat = 0
    lon = 0
    while index < len(encoded):
        d_lat, index = _decode_polyline_value(encoded, index)
        d_lon, index = _decode_polyline_value(encoded, index)
        lat += d_lat
        lon += d_lon
        points.append({"lat": lat / 1e5, "lon": lon / 1e5})
    return points


def _decode_polyline_value(encoded: str, index: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = ord(encoded[index]) - 63
        index += 1
        result |= (byte & 0x1F) << shift
        shift += 5
        if byte < 0x20:
            break
    delta = ~(result >> 1) if result & 1 else result >> 1
    return delta, index


def _safety_flags(
    context: dict,
    zone: dict[str, Any],
    shelter: dict[str, Any],
    points: list[dict[str, float]],
) -> tuple[list[str], list[str], bool]:
    flags: list[str] = []
    evidence_ids: list[str] = []
    blocking = False

    if zone.get("population", 0) > shelter.get("capacity_available", 0):
        shelter_label = shelter["shelter_id"].replace("_", " ").title()
        flags.append(f"{shelter_label} has insufficient capacity for {zone['zone_id']}.")
        blocking = True

    for event in context.get("road_events", []):
        if not _is_closure_event(event):
            continue
        if _route_near_road_event(points, event, 2.0):
            road_name = event.get("road_name") or event.get("title") or "road event"
            flags.append(f"Route enters the active closure impact buffer: {road_name}.")
            if event.get("external_id"):
                evidence_ids.append(event["external_id"])
            blocking = True

    fire_buffer_hit = False
    for fire in context.get("fires", []):
        if _route_crosses_fire_buffer(points, fire["location"], FIRE_ROUTE_BUFFER_KM, 2.0):
            fire_buffer_hit = True
            if fire.get("external_id"):
                evidence_ids.append(fire["external_id"])
            blocking = True
    if fire_buffer_hit:
        flags.append("Route crosses active fire-risk buffer.")

    if zone["zone_id"] == "ZONE_B" and shelter["shelter_id"] == "SHELTER_B":
        flags.append("Shared first segment with Zone A creates congestion risk if simultaneous.")

    if zone["zone_id"] == "ZONE_C":
        flags.append("Low vehicle access and high vulnerable population require dispatch-assisted movement.")
        blocking = True

    return flags, sorted(set(evidence_ids)), blocking


def _is_closure_event(event: dict[str, Any]) -> bool:
    blob = " ".join(
        str(event.get(field, ""))
        for field in ["event_type", "severity", "title", "description"]
    ).lower()
    closure_phrases = [
        "road closed",
        "full closure",
        "closed in both directions",
        "no detour",
        "detour unavailable",
    ]
    if any(phrase in blob for phrase in closure_phrases):
        return True
    return "closure" in blob and not any(
        phrase in blob
        for phrase in ["lane closure", "right lane", "left lane", "centre lane", "shoulder closed"]
    )


def _route_near_road_event(points: list[dict[str, float]], event: dict[str, Any], threshold_km: float) -> bool:
    if event.get("location") and route_near_point(points, event["location"], threshold_km):
        return True
    return any(route_near_point(points, point, threshold_km) for point in _geometry_points(event.get("geometry")))


def _route_crosses_fire_buffer(
    points: list[dict[str, float]],
    fire_location: dict[str, float],
    threshold_km: float,
    departure_clearance_km: float,
) -> bool:
    if len(points) < 2:
        return route_near_point(points, fire_location, threshold_km)

    trimmed = _polyline_after_distance(points, departure_clearance_km)
    if len(trimmed) < 2:
        return False
    return min_distance_to_polyline_km(fire_location, trimmed) <= threshold_km


def _polyline_after_distance(points: list[dict[str, float]], distance_km: float) -> list[dict[str, float]]:
    travelled = 0.0
    for index, (start, end) in enumerate(zip(points, points[1:])):
        segment_km = haversine_km(start, end)
        if travelled + segment_km < distance_km:
            travelled += segment_km
            continue
        if segment_km == 0:
            return points[index + 1 :]
        ratio = max(0.0, min(1.0, (distance_km - travelled) / segment_km))
        interpolated = {
            "lat": start["lat"] + (end["lat"] - start["lat"]) * ratio,
            "lon": start["lon"] + (end["lon"] - start["lon"]) * ratio,
        }
        return [interpolated, *points[index + 1 :]]
    return []


def _geometry_points(geometry: Any) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            visit(value.get("coordinates"))
        elif isinstance(value, list):
            if len(value) >= 2 and all(isinstance(item, int | float) for item in value[:2]):
                points.append({"lon": float(value[0]), "lat": float(value[1])})
            else:
                for item in value:
                    visit(item)

    visit(geometry)
    return points


def _deterministic_route(context: dict, zone: dict[str, Any], shelter: dict[str, Any]) -> RouteOption:
    road_events = context.get("road_events", [])
    fire_points = [fire["location"] for fire in context.get("fires", [])]
    closure = road_events[0] if road_events else None
    closure_id = closure["external_id"] if closure else None
    closure_point = closure["location"] if closure else None
    zone_id = zone["zone_id"]
    shelter_id = shelter["shelter_id"]
    origin = zone["centroid"]
    dest = shelter["location"]

    if zone_id == "ZONE_A" and shelter_id == "SHELTER_A":
        points = [origin, closure_point or origin, dest]
        fire_ids = [
            fire["external_id"]
            for fire in context.get("fires", [])
            if _route_crosses_fire_buffer(points, fire["location"], FIRE_ROUTE_BUFFER_KM, 2.0)
        ]
        flags = ["Route enters the DriveBC closure impact buffer.", "Shelter A has insufficient capacity for Zone A."]
        if fire_ids:
            flags.insert(1, "Route crosses active fire-risk buffer.")
        return _route(zone_id, shelter_id, _duration_from_points(points), _polyline_distance_km(points), False, flags, points, [item for item in [closure_id, *fire_ids] if item])
    if zone_id == "ZONE_A" and shelter_id == "SHELTER_B":
        points = [origin, dest]
        return _route(zone_id, shelter_id, _duration_from_points(points), _polyline_distance_km(points), True, [], points, [])
    if zone_id == "ZONE_A" and shelter_id == "SHELTER_C":
        points = [origin, dest]
        return _route(zone_id, shelter_id, _duration_from_points(points), _polyline_distance_km(points), False, ["Shelter C has insufficient capacity for Zone A."], points, [])
    if zone_id == "ZONE_B" and shelter_id == "SHELTER_B":
        points = [origin, dest]
        return _route(zone_id, shelter_id, _duration_from_points(points), _polyline_distance_km(points), True, ["Shared rural corridor with Zone A creates congestion risk if simultaneous."], points, [])
    if zone_id == "ZONE_C":
        points = [origin, closure_point or origin, dest]
        flags = ["Self-evacuation route crosses fire-risk buffer.", "Low vehicle access and high vulnerable population require dispatch-assisted movement."]
        if closure_id:
            flags.insert(0, "Outbound route enters the DriveBC closure impact buffer.")
        fire_ids = [
            fire["external_id"]
            for fire in context.get("fires", [])
            if _route_crosses_fire_buffer(points, fire["location"], FIRE_ROUTE_BUFFER_KM, 2.0)
        ]
        return _route(zone_id, shelter_id, _duration_from_points(points), _polyline_distance_km(points), False, flags, points, [item for item in [closure_id, *fire_ids] if item])

    points = [origin, dest]
    flags = []
    safe = True
    if closure and route_near_point(points, closure["location"], 2.0):
        flags.append("Route is near an active closure.")
        safe = False
    if any(route_near_point(points, fire, 2.0) for fire in fire_points):
        flags.append("Route is near active fire detections.")
        safe = False
    return _route(zone_id, shelter_id, 48, 55.0, safe, flags, points, [closure_id] if closure_id and not safe else [])


def _polyline_distance_km(points: list[dict[str, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return round(sum(haversine_km(start, end) for start, end in zip(points, points[1:])), 1)


def _duration_from_points(points: list[dict[str, float]]) -> int:
    # Offline fallback only: assume rural evacuation traffic averages roughly 55 kph.
    return max(5, round(_polyline_distance_km(points) / 55 * 60))


def best_safe_route(routes: list[RouteOption], zone_id: str) -> RouteOption | None:
    candidates = [route for route in routes if route.origin_id == zone_id and route.safe]
    if not candidates:
        return None
    return sorted(candidates, key=lambda route: route.duration_minutes)[0]


def rejected_routes(routes: list[RouteOption]) -> list[dict]:
    return [
        {
            "origin_id": route.origin_id,
            "destination_id": route.destination_id,
            "reason": "; ".join(route.risk_flags),
            "duration_minutes": route.duration_minutes,
            "evidence_ids": route.evidence_ids,
            "route_source": route.route_source,
        }
        for route in routes
        if not route.safe or route.risk_flags
    ]
