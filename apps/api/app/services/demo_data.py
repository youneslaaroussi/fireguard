from __future__ import annotations

import csv
import json
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
PUBLIC_BC_CONTEXT_SNAPSHOT = REPO_ROOT / "data" / "public" / "bc" / "public_emergency_context_snapshot.json"
HISTORICAL_EVACUATION_ZONES_SNAPSHOT = (
    REPO_ROOT / "data" / "public" / "bc" / "historical_fire_evacuation_zones_snapshot.json"
)
SYNTHETIC_MUNICIPAL_LABEL = "Synthetic demo municipality; not official municipal data."
PUBLIC_BC_CONTEXT_LABEL = "Official BC EmergencyMapBC public data snapshot."
PUBLIC_BC_HISTORICAL_LABEL = "Official BC Historical Orders and Alerts source snapshot."


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


def _historical_zone_snapshot() -> dict[str, Any]:
    with HISTORICAL_EVACUATION_ZONES_SNAPSHOT.open() as file:
        return json.load(file)


def _outer_ring(geometry: dict[str, Any]) -> list[list[float]]:
    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") == "Polygon" and coordinates:
        return coordinates[0]
    if geometry.get("type") == "MultiPolygon" and coordinates:
        rings = [polygon[0] for polygon in coordinates if polygon]
        return max(rings, key=len) if rings else []
    return []


def _centroid_from_geometry(geometry: dict[str, Any]) -> dict[str, float]:
    ring = _outer_ring(geometry)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if not ring:
        return {"lat": 0.0, "lon": 0.0}
    lon = sum(point[0] for point in ring) / len(ring)
    lat = sum(point[1] for point in ring) / len(ring)
    return {"lat": round(lat, 6), "lon": round(lon, 6)}


def _zone_from_historical_feature(
    feature: dict[str, Any],
    zone_id: str,
    vulnerability_ratio: float,
    vehicle_access_score: float,
    priority_notes: str,
) -> dict:
    snapshot = _historical_zone_snapshot()
    props = feature["properties"]
    population = int(props.get("MULTI_SOURCED_POPULATION") or 0)
    homes = int(props.get("MULTI_SOURCED_HOMES") or 0)
    source_record_id = str(props["EMRG_OAAH_SYSID"])
    return {
        "zone_id": zone_id,
        "name": props["ORDER_ALERT_NAME"],
        "data_origin": "bc_historical_orders_alerts_snapshot",
        "source": "BC_HISTORICAL_ORDERS_ALERTS",
        "source_label": PUBLIC_BC_HISTORICAL_LABEL,
        "source_url": snapshot["source_url"],
        "source_query": snapshot["query"],
        "source_record_id": source_record_id,
        "source_record_url": f"{snapshot['source_url']}/{source_record_id}",
        "captured_at": snapshot["captured_at"],
        "geometry_simplification": "ArcGIS maxAllowableOffset=0.05; geometryPrecision=5",
        "geometry": feature["geometry"],
        "centroid": _centroid_from_geometry(feature["geometry"]),
        "population": population,
        "population_source_field": "MULTI_SOURCED_POPULATION",
        "households": homes,
        "households_source_field": "MULTI_SOURCED_HOMES",
        "vulnerable_count": max(1, round(population * vulnerability_ratio)),
        "vulnerable_count_estimated": True,
        "vulnerability_source_label": "Derived demo estimate pending StatsCan demographic overlay; not an official source field.",
        "vehicle_access_score": vehicle_access_score,
        "vehicle_access_score_estimated": True,
        "vehicle_access_source_label": "Derived demo access score pending official transport/accessibility data.",
        "priority_notes": priority_notes,
        "event_name": props["EVENT_NAME"],
        "event_type": props["EVENT_TYPE"],
        "order_alert_status": props["ORDER_ALERT_STATUS"],
        "issuing_agency": props["ISSUING_AGENCY"],
        "municipality": props.get("MUNICIPALITY"),
        "event_start_date_ms": props.get("EVENT_START_DATE"),
        "all_clear_date_ms": props.get("ALL_CLEAR_DATE"),
        "synthetic": False,
    }


def evacuation_zones() -> list[dict]:
    snapshot = _historical_zone_snapshot()
    features_by_id = {
        feature["properties"]["EMRG_OAAH_SYSID"]: feature
        for feature in snapshot["features"]
    }
    return [
        _zone_from_historical_feature(
            features_by_id[186],
            "ZONE_A",
            vulnerability_ratio=0.16,
            vehicle_access_score=0.62,
            priority_notes="Official historical Central Cariboo evacuation polygon used as the primary demo evacuation zone near the DriveBC closure corridor.",
        ),
        _zone_from_historical_feature(
            features_by_id[2989],
            "ZONE_B",
            vulnerability_ratio=0.14,
            vehicle_access_score=0.68,
            priority_notes="Official historical Williams Lake River Valley evacuation polygon staged after Zone A to avoid overloading the shared reception workflow.",
        ),
        _zone_from_historical_feature(
            features_by_id[3011],
            "ZONE_C",
            vulnerability_ratio=0.50,
            vehicle_access_score=0.28,
            priority_notes="Official historical Browntop Mountain evacuation polygon used for the dispatch-assisted/shelter-in-place branch because of low access score.",
        ),
    ]


def synthetic_shelters() -> list[dict]:
    updated_at = now_iso()
    return [
        {
            "shelter_id": "SHELTER_A",
            "name": "Likely Community Hall",
            "data_origin": "synthetic_demo_shelter",
            "source_label": SYNTHETIC_MUNICIPAL_LABEL,
            "location": {"lat": 52.617, "lon": -121.594},
            "capacity_total": 500,
            "capacity_available": 120,
            "pet_friendly": True,
            "medical_support": False,
            "accessible": True,
            "status": "near_capacity",
            "updated_at": updated_at,
            "synthetic": True,
        },
        {
            "shelter_id": "SHELTER_B",
            "name": "Williams Lake ESS Reception Centre",
            "data_origin": "synthetic_demo_shelter",
            "source_label": SYNTHETIC_MUNICIPAL_LABEL,
            "location": {"lat": 52.1415, "lon": -122.1417},
            "capacity_total": 3500,
            "capacity_available": 3200,
            "pet_friendly": True,
            "medical_support": True,
            "accessible": True,
            "status": "open",
            "updated_at": updated_at,
            "synthetic": True,
        },
        {
            "shelter_id": "SHELTER_C",
            "name": "Quesnel Reception Centre",
            "data_origin": "synthetic_demo_shelter",
            "source_label": SYNTHETIC_MUNICIPAL_LABEL,
            "location": {"lat": 52.9784, "lon": -122.4931},
            "capacity_total": 1200,
            "capacity_available": 900,
            "pet_friendly": False,
            "medical_support": True,
            "accessible": True,
            "status": "open",
            "updated_at": updated_at,
            "synthetic": True,
        },
    ]


def _public_bc_snapshot() -> dict[str, Any]:
    with PUBLIC_BC_CONTEXT_SNAPSHOT.open() as file:
        return json.load(file)


def public_evacuation_orders_alerts() -> list[dict]:
    snapshot = _public_bc_snapshot()
    source = snapshot["evacuation_orders_alerts"]
    ingested_at = now_iso()
    return [
        {
            **record,
            "source": "BC_EMERGENCYMAPBC_EVACUATION_ORDERS_ALERTS",
            "source_url": source["source_url"],
            "source_query": source["query"],
            "source_label": PUBLIC_BC_CONTEXT_LABEL,
            "data_origin": "bc_emergencymapbc_public_snapshot",
            "captured_at": snapshot["captured_at"],
            "ingested_at": ingested_at,
            "synthetic": False,
        }
        for record in source["records"]
    ]


def public_ess_facilities() -> list[dict]:
    snapshot = _public_bc_snapshot()
    source = snapshot["ess_facilities"]
    ingested_at = now_iso()
    return [
        {
            **record,
            "source": "BC_EMERGENCYMAPBC_ESS_FACILITIES",
            "source_url": source["source_url"],
            "source_query": source["query"],
            "source_label": PUBLIC_BC_CONTEXT_LABEL,
            "data_origin": "bc_emergencymapbc_public_snapshot",
            "captured_at": snapshot["captured_at"],
            "ingested_at": ingested_at,
            "synthetic": False,
        }
        for record in source["records"]
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
            "data_origin": "synthetic_demo_dispatch",
            "source_label": SYNTHETIC_MUNICIPAL_LABEL,
            "status": "available",
            "location": {"lat": 52.632, "lon": -121.790},
            "capacity": 36,
            "synthetic": True,
        },
        {
            "asset_id": "DISPATCH_ENGINE_04",
            "asset_type": "fire_engine",
            "data_origin": "synthetic_demo_dispatch",
            "source_label": SYNTHETIC_MUNICIPAL_LABEL,
            "status": "available",
            "location": {"lat": 52.620, "lon": -121.742},
            "capacity": 4,
            "synthetic": True,
        },
    ]


def policies() -> list[dict]:
    return [
        {
            "policy_id": "POLICY_APPROVAL_PUBLIC_ACTIONS",
            "title": "Human approval for public-facing actions",
            "data_origin": "synthetic_demo_policy",
            "source_label": "Synthetic safety policy for hackathon demo; not official emergency doctrine.",
            "body": "Resident alerts, evacuation orders, shelter-in-place instructions, road closure instructions, and dispatch movement require incident commander approval before execution.",
            "synthetic": True,
        },
        {
            "policy_id": "POLICY_SHELTER_IN_PLACE",
            "title": "Shelter in place when evacuation routes are unsafe",
            "data_origin": "synthetic_demo_policy",
            "source_label": "Synthetic safety policy for hackathon demo; not official emergency doctrine.",
            "body": "If all self-evacuation routes cross active fire risk or known full closures, recommend temporary shelter-in-place and dispatch-assisted evacuation rather than blind evacuation.",
            "synthetic": True,
        },
    ]


def resident_contacts(zone_a_phone: str | None = None) -> list[dict]:
    zone_a_number = zone_a_phone or "+15555550123"
    return [
        {"resident_id": "RES_A_001", "zone_id": "ZONE_A", "phone": zone_a_number, "allowlisted": True, "data_origin": "synthetic_demo_resident", "source_label": SYNTHETIC_MUNICIPAL_LABEL, "synthetic": True},
        {"resident_id": "RES_B_001", "zone_id": "ZONE_B", "phone": "+15555550124", "allowlisted": True, "data_origin": "synthetic_demo_resident", "source_label": SYNTHETIC_MUNICIPAL_LABEL, "synthetic": True},
        {"resident_id": "RES_C_001", "zone_id": "ZONE_C", "phone": "+15555550125", "allowlisted": False, "data_origin": "synthetic_demo_resident", "source_label": SYNTHETIC_MUNICIPAL_LABEL, "synthetic": True},
    ]


def demo_disclosures() -> list[dict[str, Any]]:
    return [
        {
            "scope": "wildfire_road_weather_sources",
            "label": "Real/open or recorded source snapshots",
            "detail": "Fire, road, perimeter, and weather evidence must cite NASA FIRMS, BC Wildfire/ArcGIS, DriveBC/Open511, or Open-Meteo records. Replay records are labeled as snapshots.",
            "synthetic": False,
        },
        {
            "scope": "evacuation_zones",
            "label": PUBLIC_BC_HISTORICAL_LABEL,
            "detail": "Core demo evacuation zones now come from official BC Historical Orders and Alerts fire order/alert polygons. Population and home counts use source fields; vulnerability and vehicle-access scores are derived demo estimates.",
            "synthetic": False,
        },
        {
            "scope": "shelters_residents_dispatch",
            "label": SYNTHETIC_MUNICIPAL_LABEL,
            "detail": "Shelter capacities, resident contacts, and dispatch assets remain synthetic operational data built for a safe BC demo scenario.",
            "synthetic": True,
        },
        {
            "scope": "public_bc_emergency_context",
            "label": PUBLIC_BC_CONTEXT_LABEL,
            "detail": "Current BC Evacuation Orders/Alerts and ESS facility candidates are stored from official public ArcGIS layers. They provide source-backed context, but FireGuard does not infer shelter capacity from ESS facility status.",
            "synthetic": False,
        },
        {
            "scope": "shelter_road_ops_dispatch_actions",
            "label": "Simulated municipal action endpoints",
            "detail": "Shelter notification, road-ops task, and dispatch task actions are logged as simulated webhooks. They are not sent to official emergency systems.",
            "synthetic": True,
        },
        {
            "scope": "resident_sms",
            "label": "Real Twilio only for allowlisted test numbers",
            "detail": "Resident SMS actions require human approval and can only send to numbers in TWILIO_ALLOWLIST.",
            "synthetic": False,
        },
    ]
