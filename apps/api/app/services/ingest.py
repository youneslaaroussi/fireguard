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
BC_PUBLIC_ESS_FACILITIES_URL = "https://delivery.maps.gov.bc.ca/arcgis/rest/services/whse/bcgw_pub_whse_human_cultural_economic/MapServer/18/query"
BC_PUBLIC_EVACUATION_ORDERS_URL = "https://services6.arcgis.com/ubm4tcTYICKBpist/ArcGIS/rest/services/Evacuation_Orders_and_Alerts/FeatureServer/0/query"
BC_PUBLIC_ESS_QUERY = "COMMUNITY IN ('Williams Lake','Quesnel','100 Mile House') OR STATUS='OPEN'"


def stable_id(*values: Any) -> str:
    blob = "|".join(str(value) for value in values)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _arcgis_epoch_ms(value: Any) -> str | None:
    try:
        epoch_ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def _geometry_location(geometry: dict[str, Any] | None) -> dict[str, float]:
    if not geometry:
        return {"lat": 0.0, "lon": 0.0}
    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") == "Point" and len(coordinates) >= 2:
        return {"lat": round(float(coordinates[1]), 6), "lon": round(float(coordinates[0]), 6)}
    points: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            if len(value) >= 2 and all(isinstance(item, int | float) for item in value[:2]):
                points.append((float(value[0]), float(value[1])))
            else:
                for item in value:
                    visit(item)

    visit(coordinates)
    if not points:
        return {"lat": 0.0, "lon": 0.0}
    lon = sum(point[0] for point in points) / len(points)
    lat = sum(point[1] for point in points) / len(points)
    return {"lat": round(lat, 6), "lon": round(lon, 6)}


def _normalize_public_evacuation_order(feature: dict[str, Any], *, captured_at: str, source_url: str, source_query: str) -> dict[str, Any] | None:
    props = feature.get("properties", {})
    source_id = props.get("EMRG_OAA_SYSID") or props.get("OBJECTID") or feature.get("id")
    if source_id is None:
        return None
    geometry = feature.get("geometry")
    return {
        "order_alert_id": f"BC_OAA_{source_id}",
        "event_name": props.get("EVENT_NAME"),
        "event_type": props.get("EVENT_TYPE"),
        "order_alert_name": props.get("ORDER_ALERT_NAME"),
        "status": props.get("ORDER_ALERT_STATUS"),
        "issuing_agency": props.get("ISSUING_AGENCY"),
        "population": int(props.get("MULTI_SOURCED_POPULATION") or 0),
        "homes": int(props.get("MULTI_SOURCED_HOMES") or 0),
        "location": _geometry_location(geometry),
        "geometry_type": geometry.get("type") if isinstance(geometry, dict) else None,
        "event_start_date": _arcgis_epoch_ms(props.get("EVENT_START_DATE")),
        "updated_at": _arcgis_epoch_ms(props.get("DATE_MODIFIED")) or captured_at,
        "source": "BC_EMERGENCYMAPBC_EVACUATION_ORDERS_ALERTS",
        "source_url": source_url,
        "source_query": source_query,
        "source_label": "Official BC EmergencyMapBC public data live query.",
        "data_origin": "bc_emergencymapbc_public_live",
        "captured_at": captured_at,
        "ingested_at": captured_at,
        "synthetic": False,
        "raw": props,
    }


def _normalize_public_ess_facility(feature: dict[str, Any], *, captured_at: str, source_url: str, source_query: str) -> dict[str, Any] | None:
    props = feature.get("properties", {})
    source_id = props.get("ESS_FACILITY_ID") or props.get("OBJECTID") or feature.get("id")
    if source_id is None:
        return None
    return {
        "facility_id": f"BC_ESS_{source_id}",
        "name": props.get("FACILITY_NAME"),
        "facility_type_code": props.get("FACILITY_TYPE_CODE"),
        "facility_type": "Reception Centre" if props.get("FACILITY_TYPE_CODE") == "RC" else props.get("FACILITY_TYPE_CODE"),
        "address": props.get("ADDRESS"),
        "community": props.get("COMMUNITY"),
        "municipality": props.get("MUNICIPALITY"),
        "status": props.get("STATUS"),
        "location": _geometry_location(feature.get("geometry")),
        "updated_at": _arcgis_epoch_ms(props.get("STATUS_DATE")) or captured_at,
        "source": "BC_EMERGENCYMAPBC_ESS_FACILITIES",
        "source_url": source_url,
        "source_query": source_query,
        "source_label": "Official BC EmergencyMapBC public data live query.",
        "data_origin": "bc_emergencymapbc_public_live",
        "captured_at": captured_at,
        "ingested_at": captured_at,
        "synthetic": False,
        "raw": props,
    }


async def ingest_firms(settings: Settings) -> dict[str, Any]:
    if not settings.nasa_firms_map_key:
        docs = demo_data.replay_fire_hotspots()
        return {"mode": "historical_snapshot_replay", "docs": docs, "reason": "NASA_FIRMS_MAP_KEY is not configured."}

    bbox = settings.nasa_firms_bbox
    day_range = max(1, min(int(settings.nasa_firms_day_range), 5))
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{settings.nasa_firms_map_key}/{settings.nasa_firms_source}/{bbox}/{day_range}"
    redacted_url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/[MAP_KEY]/{settings.nasa_firms_source}/{bbox}/{day_range}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()
    rows = list(csv.DictReader(StringIO(response.text)))
    if not rows:
        docs = demo_data.replay_fire_hotspots()
        return {
            "mode": "live_empty_historical_snapshot_fallback",
            "docs": docs,
            "source_url": redacted_url,
            "reason": "NASA FIRMS returned zero rows for the configured bbox and lookback window.",
        }
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
    return {
        "mode": "live",
        "docs": docs,
        "source_url": redacted_url,
        "source_bbox": bbox,
        "day_range": day_range,
        "row_count": len(docs),
    }


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
            "location": {"lat": float(lat), "lon": float(lon)} if lat and lon else {"lat": 52.623474, "lon": -121.761311},
            "geometry": geography if geography else None,
            "starts_at": event.get("created") or event.get("start_date"),
            "ends_at": event.get("end_date"),
            "updated_at": event.get("updated") or ingested_at,
            "ingested_at": ingested_at,
            "raw": event,
        })
    return {"mode": "live", "docs": docs or demo_data.replay_road_events(), "source_url": DRIVEBC_EVENTS_URL}


async def ingest_weather(lat: float = 52.622, lon: float = -121.660) -> dict[str, Any]:
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


async def ingest_public_evacuation_orders() -> dict[str, Any]:
    params = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "geojson"}
    captured_at = now_iso()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(BC_PUBLIC_EVACUATION_ORDERS_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        docs = demo_data.public_evacuation_orders_alerts()
        return {"mode": "stored_snapshot_fallback", "docs": docs, "reason": str(exc), "source_url": BC_PUBLIC_EVACUATION_ORDERS_URL}

    docs = [
        doc
        for feature in payload.get("features", [])
        if (doc := _normalize_public_evacuation_order(
            feature,
            captured_at=captured_at,
            source_url=BC_PUBLIC_EVACUATION_ORDERS_URL,
            source_query="where=1=1&outFields=*&returnGeometry=true&outSR=4326&f=geojson",
        ))
    ]
    if not docs:
        docs = demo_data.public_evacuation_orders_alerts()
        return {
            "mode": "live_empty_stored_snapshot_fallback",
            "docs": docs,
            "reason": "Official BC evacuation orders/alerts live query returned zero rows.",
            "source_url": BC_PUBLIC_EVACUATION_ORDERS_URL,
        }
    return {"mode": "live", "docs": docs, "source_url": BC_PUBLIC_EVACUATION_ORDERS_URL}


async def ingest_public_ess_facilities() -> dict[str, Any]:
    params = {
        "where": BC_PUBLIC_ESS_QUERY,
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    captured_at = now_iso()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(BC_PUBLIC_ESS_FACILITIES_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        docs = demo_data.public_ess_facilities()
        return {"mode": "stored_snapshot_fallback", "docs": docs, "reason": str(exc), "source_url": BC_PUBLIC_ESS_FACILITIES_URL}

    docs = [
        doc
        for feature in payload.get("features", [])
        if (doc := _normalize_public_ess_facility(
            feature,
            captured_at=captured_at,
            source_url=BC_PUBLIC_ESS_FACILITIES_URL,
            source_query="where=COMMUNITY IN ('Williams Lake','Quesnel','100 Mile House') OR STATUS='OPEN'&outFields=*&returnGeometry=true&outSR=4326&f=geojson",
        ))
    ]
    if not docs:
        docs = demo_data.public_ess_facilities()
        return {
            "mode": "live_empty_stored_snapshot_fallback",
            "docs": docs,
            "reason": "Official BC ESS facilities live query returned zero rows.",
            "source_url": BC_PUBLIC_ESS_FACILITIES_URL,
        }
    return {"mode": "live", "docs": docs, "source_url": BC_PUBLIC_ESS_FACILITIES_URL}
