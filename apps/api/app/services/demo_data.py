from __future__ import annotations

from app.services.time import now_iso

INCIDENT_ID = "demo-incident-bc-001"


def synthetic_zones() -> list[dict]:
    return [
        {
            "zone_id": "ZONE_A",
            "name": "Canyon Ridge",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-121.612, 50.236],
                    [-121.586, 50.236],
                    [-121.586, 50.258],
                    [-121.612, 50.258],
                    [-121.612, 50.236],
                ]],
            },
            "centroid": {"lat": 50.247, "lon": -121.599},
            "population": 420,
            "households": 168,
            "vulnerable_count": 38,
            "vehicle_access_score": 0.72,
            "priority_notes": "Dense residential hillside with one primary eastbound exit.",
        },
        {
            "zone_id": "ZONE_B",
            "name": "River Flats",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-121.585, 50.235],
                    [-121.552, 50.235],
                    [-121.552, 50.258],
                    [-121.585, 50.258],
                    [-121.585, 50.235],
                ]],
            },
            "centroid": {"lat": 50.247, "lon": -121.568},
            "population": 610,
            "households": 244,
            "vulnerable_count": 71,
            "vehicle_access_score": 0.64,
            "priority_notes": "Main evacuation path overlaps Canyon Ridge for first 8 km.",
        },
        {
            "zone_id": "ZONE_C",
            "name": "Pine Clinic District",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-121.578, 50.210],
                    [-121.540, 50.210],
                    [-121.540, 50.233],
                    [-121.578, 50.233],
                    [-121.578, 50.210],
                ]],
            },
            "centroid": {"lat": 50.222, "lon": -121.559},
            "population": 260,
            "households": 96,
            "vulnerable_count": 92,
            "vehicle_access_score": 0.28,
            "priority_notes": "Clinic, assisted-living wing, and low vehicle access.",
        },
    ]


def synthetic_shelters() -> list[dict]:
    updated_at = now_iso()
    return [
        {
            "shelter_id": "SHELTER_A",
            "name": "Cache Creek Arena",
            "location": {"lat": 50.811, "lon": -121.325},
            "capacity_total": 500,
            "capacity_available": 120,
            "pet_friendly": True,
            "medical_support": False,
            "accessible": True,
            "status": "near_capacity",
            "updated_at": updated_at,
        },
        {
            "shelter_id": "SHELTER_B",
            "name": "Lillooet Secondary Reception Centre",
            "location": {"lat": 50.687, "lon": -121.932},
            "capacity_total": 900,
            "capacity_available": 760,
            "pet_friendly": True,
            "medical_support": True,
            "accessible": True,
            "status": "open",
            "updated_at": updated_at,
        },
        {
            "shelter_id": "SHELTER_C",
            "name": "Merritt Civic Centre",
            "location": {"lat": 50.112, "lon": -120.789},
            "capacity_total": 700,
            "capacity_available": 360,
            "pet_friendly": False,
            "medical_support": True,
            "accessible": True,
            "status": "open",
            "updated_at": updated_at,
        },
    ]


def replay_fire_hotspots() -> list[dict]:
    ingested_at = now_iso()
    return [
        {
            "source": "NASA_FIRMS_REPLAY",
            "external_id": "FIRMS_REPLAY_20240723_001",
            "location": {"lat": 50.226, "lon": -121.505},
            "brightness": 334.2,
            "confidence": "high",
            "frp": 62.4,
            "scan": 0.43,
            "track": 0.39,
            "acquired_at": "2024-07-23T21:14:00Z",
            "updated_at": ingested_at,
            "ingested_at": ingested_at,
            "raw": {"replay": True, "source_shape": "NASA FIRMS area CSV"},
        },
        {
            "source": "NASA_FIRMS_REPLAY",
            "external_id": "FIRMS_REPLAY_20240723_002",
            "location": {"lat": 50.238, "lon": -121.523},
            "brightness": 329.7,
            "confidence": "nominal",
            "frp": 48.9,
            "scan": 0.42,
            "track": 0.38,
            "acquired_at": "2024-07-23T21:14:00Z",
            "updated_at": ingested_at,
            "ingested_at": ingested_at,
            "raw": {"replay": True, "source_shape": "NASA FIRMS area CSV"},
        },
    ]


def replay_fire_perimeters() -> list[dict]:
    ingested_at = now_iso()
    return [
        {
            "source": "BC_WILDFIRE_REPLAY",
            "fire_name": "Kwoiek Creek Replay Perimeter",
            "fire_number": "BC-REPLAY-KWK-001",
            "status": "Out of Control",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-121.545, 50.205],
                    [-121.488, 50.209],
                    [-121.476, 50.252],
                    [-121.533, 50.264],
                    [-121.545, 50.205],
                ]],
            },
            "area_hectares": 1875.0,
            "updated_at": ingested_at,
            "ingested_at": ingested_at,
            "raw": {"replay": True, "source_shape": "BC ArcGIS FeatureServer geoJSON"},
        }
    ]


def replay_road_events() -> list[dict]:
    ingested_at = now_iso()
    return [
        {
            "source": "DRIVEBC_OPEN511_REPLAY",
            "external_id": "DBC_REPLAY_CLOSURE_001",
            "title": "Highway 1 eastbound closed near Kwoiek Creek",
            "description": "Full closure due to wildfire operations. Detour unavailable for public traffic.",
            "event_type": "closure",
            "severity": "high",
            "road_name": "Highway 1",
            "location": {"lat": 50.241, "lon": -121.548},
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [-121.571, 50.247],
                    [-121.548, 50.241],
                    [-121.520, 50.236],
                ],
            },
            "starts_at": "2024-07-23T20:30:00Z",
            "ends_at": None,
            "updated_at": ingested_at,
            "ingested_at": ingested_at,
            "raw": {"replay": True, "source_shape": "DriveBC Open511 events"},
        }
    ]


def replay_weather() -> list[dict]:
    ingested_at = now_iso()
    return [
        {
            "weather_id": "WEATHER_REPLAY_001",
            "source": "OPEN_METEO_REPLAY",
            "location": {"lat": 50.247, "lon": -121.568},
            "wind_speed_kph": 34.0,
            "wind_direction_degrees": 248,
            "wind_gusts_kph": 49.0,
            "forecast_horizon_hours": 3,
            "updated_at": ingested_at,
            "ingested_at": ingested_at,
            "raw": {"replay": True, "source_shape": "Open-Meteo forecast"},
        }
    ]


def dispatch_assets() -> list[dict]:
    return [
        {
            "asset_id": "DISPATCH_BUS_01",
            "asset_type": "accessible_bus",
            "status": "available",
            "location": {"lat": 50.232, "lon": -121.571},
            "capacity": 36,
        },
        {
            "asset_id": "DISPATCH_ENGINE_04",
            "asset_type": "fire_engine",
            "status": "available",
            "location": {"lat": 50.246, "lon": -121.585},
            "capacity": 4,
        },
    ]


def policies() -> list[dict]:
    return [
        {
            "policy_id": "POLICY_APPROVAL_PUBLIC_ACTIONS",
            "title": "Human approval for public-facing actions",
            "body": "Resident alerts, evacuation orders, shelter-in-place instructions, road closure instructions, and dispatch movement require incident commander approval before execution.",
        },
        {
            "policy_id": "POLICY_SHELTER_IN_PLACE",
            "title": "Shelter in place when evacuation routes are unsafe",
            "body": "If all self-evacuation routes cross active fire risk or known full closures, recommend temporary shelter-in-place and dispatch-assisted evacuation rather than blind evacuation.",
        },
    ]


def resident_contacts(zone_a_phone: str | None = None) -> list[dict]:
    zone_a_number = zone_a_phone or "+15555550123"
    return [
        {"resident_id": "RES_A_001", "zone_id": "ZONE_A", "phone": zone_a_number, "allowlisted": True},
        {"resident_id": "RES_B_001", "zone_id": "ZONE_B", "phone": "+15555550124", "allowlisted": True},
        {"resident_id": "RES_C_001", "zone_id": "ZONE_C", "phone": "+15555550125", "allowlisted": False},
    ]
