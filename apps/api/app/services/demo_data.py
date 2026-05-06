from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.services.time import now_iso

INCIDENT_ID = "demo-incident-bc-001"
REPO_ROOT = Path(__file__).resolve().parents[4]
FIRMS_SNAPSHOT_CSV = REPO_ROOT / "data" / "replay" / "bc_demo" / "firms_snapshot.csv"
FIRMS_SNAPSHOT_URL = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
    "[MAP_KEY]/VIIRS_NOAA20_SP/-122.2,52.0,-121.3,52.9/5/2024-07-10"
)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _firms_external_id(row: dict[str, str]) -> str:
    date_token = str(row.get("acq_date", "unknown")).replace("-", "")
    time_token = str(row.get("acq_time", "0000")).zfill(4)
    lat_token = str(row.get("latitude", "0")).replace("-", "M").replace(".", "_")
    lon_token = str(row.get("longitude", "0")).replace("-", "M").replace(".", "_")
    satellite = str(row.get("satellite") or "VIIRS")
    return f"FIRMS_{satellite}_{date_token}_{time_token}_{lat_token}_{lon_token}"


def _firms_acquired_at(row: dict[str, str]) -> str:
    acq_time = str(row.get("acq_time", "0000")).zfill(4)
    return f"{row.get('acq_date')}T{acq_time[:2]}:{acq_time[2:]}:00Z"


def synthetic_zones() -> list[dict]:
    return [
        {
            "zone_id": "ZONE_A",
            "name": "Quesnel River West",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-121.895, 52.600],
                    [-121.855, 52.600],
                    [-121.855, 52.620],
                    [-121.895, 52.620],
                    [-121.895, 52.600],
                ]],
            },
            "centroid": {"lat": 52.610, "lon": -121.875},
            "population": 420,
            "households": 168,
            "vulnerable_count": 38,
            "vehicle_access_score": 0.72,
            "priority_notes": "Rural residential area west of a real DriveBC road closure.",
        },
        {
            "zone_id": "ZONE_B",
            "name": "Likely East Bench",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-121.678, 52.612],
                    [-121.642, 52.612],
                    [-121.642, 52.632],
                    [-121.678, 52.632],
                    [-121.678, 52.612],
                ]],
            },
            "centroid": {"lat": 52.622, "lon": -121.660},
            "population": 610,
            "households": 244,
            "vulnerable_count": 71,
            "vehicle_access_score": 0.64,
            "priority_notes": "East-side area shares limited rural approaches with Zone A traffic.",
        },
        {
            "zone_id": "ZONE_C",
            "name": "Little Lake Clinic District",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-121.818, 52.626],
                    [-121.782, 52.626],
                    [-121.782, 52.646],
                    [-121.818, 52.646],
                    [-121.818, 52.626],
                ]],
            },
            "centroid": {"lat": 52.635, "lon": -121.800},
            "population": 260,
            "households": 96,
            "vulnerable_count": 92,
            "vehicle_access_score": 0.28,
            "priority_notes": "Clinic, assisted-living wing, and low vehicle access near the closure.",
        },
    ]


def synthetic_shelters() -> list[dict]:
    updated_at = now_iso()
    return [
        {
            "shelter_id": "SHELTER_A",
            "name": "Likely Community Hall",
            "location": {"lat": 52.617, "lon": -121.594},
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
            "name": "Williams Lake ESS Reception Centre",
            "location": {"lat": 52.1415, "lon": -122.1417},
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
            "name": "Quesnel Reception Centre",
            "location": {"lat": 52.9784, "lon": -122.4931},
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
    docs = []
    with FIRMS_SNAPSHOT_CSV.open(newline="") as file:
        for row in csv.DictReader(file):
            acquired_at = _firms_acquired_at(row)
            docs.append({
                "source": "NASA_FIRMS_HISTORICAL_SNAPSHOT",
                "external_id": _firms_external_id(row),
                "location": {"lat": _float(row.get("latitude")), "lon": _float(row.get("longitude"))},
                "brightness": _float(row.get("bright_ti4") or row.get("brightness")),
                "confidence": str(row.get("confidence", "unknown")),
                "frp": _float(row.get("frp")),
                "scan": _float(row.get("scan")),
                "track": _float(row.get("track")),
                "acquired_at": acquired_at,
                "updated_at": acquired_at,
                "ingested_at": ingested_at,
                "source_url": FIRMS_SNAPSHOT_URL,
                "raw": {
                    **row,
                    "historical_replay": True,
                    "source_snapshot": True,
                    "snapshot_file": "data/replay/bc_demo/firms_snapshot.csv",
                    "captured_from": FIRMS_SNAPSHOT_URL,
                },
            })
    return docs


def replay_fire_perimeters() -> list[dict]:
    ingested_at = now_iso()
    return [
        {
            "source": "BC_WILDFIRE_REPLAY",
            "fire_name": "Quesnel River Replay Perimeter",
            "fire_number": "BC-REPLAY-QSR-001",
            "status": "Out of Control",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-121.742, 52.610],
                    [-121.676, 52.612],
                    [-121.660, 52.646],
                    [-121.728, 52.656],
                    [-121.742, 52.610],
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
            "source": "DRIVEBC_OPEN511_SNAPSHOT",
            "external_id": "drivebc.ca/DBC-90684",
            "title": "Little Lake Quesnel River Road closed near Williams Lake",
            "description": "Little Lake Quesnel River Road. Washout at West of Likely Road Turnoff near Williams Lake. Road closed. Geotechnical investigation. Assessment in progress. Road closed 10 km West of Likely Road Turnoff. No detour. Next update time Mon Jun 1 at 12:00 PM PDT. Last updated Thu Apr 30 at 3:28 PM PDT. (DBC-90684)",
            "event_type": "INCIDENT",
            "severity": "MAJOR",
            "road_name": "Little Lake Quesnel River Road",
            "location": {"lat": 52.623474, "lon": -121.761311},
            "geometry": {
                "type": "Point",
                "coordinates": [-121.761311, 52.623474],
            },
            "starts_at": "2026-04-30T15:28:34-07:00",
            "ends_at": None,
            "updated_at": "2026-04-30T15:28:34-07:00",
            "ingested_at": ingested_at,
            "source_url": "https://api.open511.gov.bc.ca/events/drivebc.ca/DBC-90684",
            "raw": {
                "source_snapshot": True,
                "captured_from": "https://api.open511.gov.bc.ca/events/drivebc.ca/DBC-90684",
                "source_shape": "DriveBC Open511 events",
            },
        }
    ]


def replay_weather() -> list[dict]:
    ingested_at = now_iso()
    return [
        {
            "weather_id": "WEATHER_REPLAY_001",
            "source": "OPEN_METEO_REPLAY",
            "location": {"lat": 52.622, "lon": -121.660},
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
            "location": {"lat": 52.632, "lon": -121.790},
            "capacity": 36,
        },
        {
            "asset_id": "DISPATCH_ENGINE_04",
            "asset_type": "fire_engine",
            "status": "available",
            "location": {"lat": 52.620, "lon": -121.742},
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
