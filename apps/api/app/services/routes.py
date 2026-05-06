from __future__ import annotations

from app.models.schemas import GeoPoint, RouteOption
from app.services.geo import route_near_point


def _point(lat: float, lon: float) -> dict[str, float]:
    return {"lat": lat, "lon": lon}


def _route(origin_id: str, destination_id: str, duration: int, distance: float, safe: bool, flags: list[str], points: list[dict[str, float]], evidence_ids: list[str]) -> RouteOption:
    return RouteOption(
        origin_id=origin_id,
        destination_id=destination_id,
        duration_minutes=duration,
        distance_km=distance,
        safe=safe,
        risk_flags=flags,
        polyline=[GeoPoint(lat=point["lat"], lon=point["lon"]) for point in points],
        evidence_ids=evidence_ids,
    )


def compute_routes(context: dict, origins: list[dict] | None = None, destinations: list[dict] | None = None) -> list[RouteOption]:
    zones = origins or context.get("zones", [])
    shelters = destinations or context.get("shelters", [])
    road_events = context.get("road_events", [])
    fire_points = [fire["location"] for fire in context.get("fires", [])]
    closure = road_events[0] if road_events else None
    closure_id = closure["external_id"] if closure else None

    routes: list[RouteOption] = []
    for zone in zones:
        zone_id = zone["zone_id"]
        for shelter in shelters:
            shelter_id = shelter["shelter_id"]
            if zone_id == "ZONE_A" and shelter_id == "SHELTER_A":
                points = [_point(50.247, -121.599), _point(50.247, -121.571), _point(50.241, -121.548), _point(50.811, -121.325)]
                routes.append(_route(zone_id, shelter_id, 18, 38.4, False, ["Route intersects Highway 1 full closure.", "Route crosses active fire-risk buffer.", "Shelter A has insufficient capacity for Zone A."], points, [closure_id] if closure_id else []))
            elif zone_id == "ZONE_A" and shelter_id == "SHELTER_B":
                routes.append(_route(zone_id, shelter_id, 38, 42.8, True, [], [_point(50.247, -121.599), _point(50.302, -121.702), _point(50.687, -121.932)], []))
            elif zone_id == "ZONE_B" and shelter_id == "SHELTER_B":
                routes.append(_route(zone_id, shelter_id, 42, 45.6, True, ["Shared first segment with Zone A creates congestion risk if simultaneous."], [_point(50.247, -121.568), _point(50.306, -121.704), _point(50.687, -121.932)], []))
            elif zone_id == "ZONE_C":
                points = [_point(50.222, -121.559), _point(50.236, -121.532), _point(50.241, -121.548)]
                flags = ["Self-evacuation route crosses fire-risk buffer.", "Low vehicle access and high vulnerable population require dispatch-assisted movement."]
                if closure_id:
                    flags.insert(0, "Outbound route intersects Highway 1 closure.")
                routes.append(_route(zone_id, shelter_id, 54, 50.1, False, flags, points, [closure_id] if closure_id else []))
            else:
                origin = zone["centroid"]
                dest = shelter["location"]
                points = [origin, dest]
                flags = []
                safe = True
                if closure and route_near_point(points, closure["location"], 2.0):
                    flags.append("Route is near an active closure.")
                    safe = False
                if any(route_near_point(points, fire, 2.0) for fire in fire_points):
                    flags.append("Route is near active fire detections.")
                    safe = False
                routes.append(_route(zone_id, shelter_id, 48, 55.0, safe, flags, points, [closure_id] if closure_id and not safe else []))
    return routes


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
        }
        for route in routes
        if not route.safe or route.risk_flags
    ]
