from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from io import StringIO
from typing import Any

import httpx

from app.config import Settings
from app.services import demo_data
from app.services.time import now_iso

BC_PERIMETERS_URL = "https://delivery.maps.gov.bc.ca/arcgis/rest/services/mpcm/bcgwpub/MapServer/624/query"
DRIVEBC_EVENTS_URL = "https://api.open511.gov.bc.ca/events"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def stable_id(*values: Any) -> str:
    blob = "|".join(str(value) for value in values)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


async def ingest_firms(settings: Settings) -> dict[str, Any]:
    if not settings.nasa_firms_map_key:
        docs = demo_data.replay_fire_hotspots()
        return {"mode": "replay", "docs": docs, "reason": "NASA_FIRMS_MAP_KEY is not configured."}

    bbox = settings.nasa_firms_bbox
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{settings.nasa_firms_map_key}/{settings.nasa_firms_source}/{bbox}/1"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()
    rows = csv.DictReader(StringIO(response.text))
    docs = []
    ingested_at = now_iso()
    for row in rows:
        external_id = stable_id(row.get("latitude"), row.get("longitude"), row.get("acq_date"), row.get("acq_time"), row.get("satellite"))
        acq_time = str(row.get("acq_time", "0000")).zfill(4)
        acquired_at = f"{row.get('acq_date')}T{acq_time[:2]}:{acq_time[2:]}:00Z"
        docs.append({
            "source": "NASA_FIRMS",
            "external_id": external_id,
            "location": {"lat": float(row["latitude"]), "lon": float(row["longitude"])},
            "brightness": float(row.get("bright_ti4") or row.get("brightness") or 0),
            "confidence": str(row.get("confidence", "unknown")),
            "frp": float(row.get("frp") or 0),
            "scan": float(row.get("scan") or 0),
            "track": float(row.get("track") or 0),
            "acquired_at": acquired_at,
            "updated_at": acquired_at,
            "ingested_at": ingested_at,
            "raw": row,
        })
    return {"mode": "live", "docs": docs, "source_url": url}


async def ingest_bc_perimeters() -> dict[str, Any]:
    params = {"f": "geojson", "where": "1=1", "outFields": "*", "returnGeometry": "true", "resultRecordCount": "1000"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(BC_PERIMETERS_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {"mode": "replay", "docs": demo_data.replay_fire_perimeters(), "reason": str(exc)}

    ingested_at = now_iso()
    docs = []
    for feature in payload.get("features", []):
        props = feature.get("properties", {})
        fire_number = props.get("FIRE_NUMBER") or props.get("fire_number") or props.get("OBJECTID")
        if not fire_number:
            continue
        docs.append({
            "source": "BC_WILDFIRE",
            "fire_name": props.get("FIRE_NAME") or props.get("FIRELABEL") or "Unnamed BC wildfire",
            "fire_number": str(fire_number),
            "status": props.get("FIRE_STATUS") or props.get("STATUS") or "unknown",
            "geometry": feature.get("geometry"),
            "area_hectares": props.get("FIRE_SIZE_HECTARES") or props.get("AREA_HA"),
            "updated_at": ingested_at,
            "ingested_at": ingested_at,
            "raw": props,
        })
    return {"mode": "live", "docs": docs or demo_data.replay_fire_perimeters(), "source_url": BC_PERIMETERS_URL}


async def ingest_road_events() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(DRIVEBC_EVENTS_URL, params={"format": "json"})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {"mode": "replay", "docs": demo_data.replay_road_events(), "reason": str(exc)}

    ingested_at = now_iso()
    docs = []
    events = payload.get("events") if isinstance(payload, dict) else payload
    for event in events or []:
        event_id = event.get("id") or event.get("identifier") or event.get("url") or stable_id(event)
        geography = event.get("geography") or {}
        coords = geography.get("coordinates") if isinstance(geography, dict) else None
        lon, lat = (coords[:2] if isinstance(coords, list) and len(coords) >= 2 else (None, None))
        docs.append({
            "source": "DRIVEBC_OPEN511",
            "external_id": str(event_id),
            "title": event.get("headline") or event.get("event_type") or "DriveBC event",
            "description": event.get("description") or event.get("headline") or "",
            "event_type": event.get("event_type") or "road_event",
            "severity": event.get("severity") or "unknown",
            "road_name": event.get("roads", [{}])[0].get("name") if event.get("roads") else "unknown",
            "location": {"lat": float(lat), "lon": float(lon)} if lat and lon else {"lat": 50.241, "lon": -121.548},
            "geometry": geography if geography else None,
            "starts_at": event.get("created") or event.get("start_date"),
            "ends_at": event.get("end_date"),
            "updated_at": event.get("updated") or ingested_at,
            "ingested_at": ingested_at,
            "raw": event,
        })
    return {"mode": "live", "docs": docs or demo_data.replay_road_events(), "source_url": DRIVEBC_EVENTS_URL}


async def ingest_weather(lat: float = 50.247, lon: float = -121.568) -> dict[str, Any]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "kmh",
        "timezone": "UTC",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(OPEN_METEO_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {"mode": "replay", "docs": demo_data.replay_weather(), "reason": str(exc)}

    current = payload.get("current", {})
    timestamp = current.get("time")
    updated_at = datetime.fromisoformat(timestamp).replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if timestamp else now_iso()
    doc = {
        "weather_id": f"OPEN_METEO_{stable_id(lat, lon, updated_at)}",
        "source": "OPEN_METEO",
        "location": {"lat": lat, "lon": lon},
        "wind_speed_kph": current.get("wind_speed_10m"),
        "wind_direction_degrees": current.get("wind_direction_10m"),
        "wind_gusts_kph": current.get("wind_gusts_10m"),
        "forecast_horizon_hours": 1,
        "updated_at": updated_at,
        "ingested_at": now_iso(),
        "raw": payload,
    }
    return {"mode": "live", "docs": [doc], "source_url": OPEN_METEO_URL}
