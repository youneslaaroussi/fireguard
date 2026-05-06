from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from io import StringIO
from typing import Any, Iterable

import requests
from fivetran_connector_sdk import Connector, Logging as log, Operations as op

BC_PERIMETERS_URL = "https://delivery.maps.gov.bc.ca/arcgis/rest/services/mpcm/bcgwpub/MapServer/624/query"
DRIVEBC_EVENTS_URL = "https://api.open511.gov.bc.ca/events"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_datetime(value: Any) -> str:
    text = str(value or now_iso())
    if len(text) == 16 and text[10] == "T":
        text = f"{text}:00"
    if len(text) == 19 and text[10] == "T":
        text = f"{text}Z"
    return text


def stable_id(*values: Any) -> str:
    blob = "|".join(str(value) for value in values)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def first_lon_lat(value: Any) -> tuple[float | None, float | None]:
    if isinstance(value, dict):
        return first_lon_lat(value.get("coordinates"))
    if isinstance(value, list):
        if len(value) >= 2 and all(isinstance(part, int | float) for part in value[:2]):
            return float(value[0]), float(value[1])
        for item in value:
            lon, lat = first_lon_lat(item)
            if lon is not None and lat is not None:
                return lon, lat
    return None, None


def schema(configuration: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "table": "fire_hotspots",
            "primary_key": ["external_id"],
            "columns": {
                "external_id": "STRING",
                "source": "STRING",
                "latitude": "DOUBLE",
                "longitude": "DOUBLE",
                "brightness": "DOUBLE",
                "confidence": "STRING",
                "frp": "DOUBLE",
                "scan": "DOUBLE",
                "track": "DOUBLE",
                "acquired_at": "UTC_DATETIME",
                "updated_at": "UTC_DATETIME",
                "ingested_at": "UTC_DATETIME",
                "raw_json": "STRING",
            },
        },
        {
            "table": "fire_perimeters",
            "primary_key": ["fire_number"],
            "columns": {
                "fire_number": "STRING",
                "source": "STRING",
                "fire_name": "STRING",
                "status": "STRING",
                "geometry_json": "STRING",
                "area_hectares": "DOUBLE",
                "updated_at": "UTC_DATETIME",
                "ingested_at": "UTC_DATETIME",
                "raw_json": "STRING",
            },
        },
        {
            "table": "road_events",
            "primary_key": ["external_id"],
            "columns": {
                "external_id": "STRING",
                "source": "STRING",
                "title": "STRING",
                "description": "STRING",
                "event_type": "STRING",
                "severity": "STRING",
                "road_name": "STRING",
                "latitude": "DOUBLE",
                "longitude": "DOUBLE",
                "geometry_json": "STRING",
                "starts_at": "UTC_DATETIME",
                "ends_at": "UTC_DATETIME",
                "updated_at": "UTC_DATETIME",
                "ingested_at": "UTC_DATETIME",
                "raw_json": "STRING",
            },
        },
        {
            "table": "weather_observations",
            "primary_key": ["weather_id"],
            "columns": {
                "weather_id": "STRING",
                "source": "STRING",
                "latitude": "DOUBLE",
                "longitude": "DOUBLE",
                "wind_speed_kph": "DOUBLE",
                "wind_direction_degrees": "DOUBLE",
                "wind_gusts_kph": "DOUBLE",
                "forecast_horizon_hours": "INT",
                "updated_at": "UTC_DATETIME",
                "ingested_at": "UTC_DATETIME",
                "raw_json": "STRING",
            },
        },
        {
            "table": "ingestion_runs",
            "primary_key": ["run_id"],
            "columns": {
                "run_id": "STRING",
                "provider": "STRING",
                "status": "STRING",
                "streams_json": "STRING",
                "created_at": "UTC_DATETIME",
            },
        },
    ]


def _request_json(url: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _request_text(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def _firms_rows(configuration: dict[str, Any]) -> Iterable[dict[str, Any]]:
    map_key = configuration.get("nasa_firms_map_key")
    if not map_key:
        log.warning("NASA FIRMS map key missing; emitting replay-shaped FIRMS rows.")
        yield from _replay_fire_hotspots()
        return

    source = configuration.get("nasa_firms_source", "VIIRS_SNPP_NRT")
    bbox = configuration.get("nasa_firms_bbox", "-122.2,52.0,-121.3,52.9")
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{source}/{bbox}/1"
    ingested_at = now_iso()
    try:
        text = _request_text(url)
    except Exception as exc:
        log.warning(f"NASA FIRMS fetch failed; emitting labeled replay FIRMS rows: {exc}")
        yield from _replay_fire_hotspots()
        return
    for row in csv.DictReader(StringIO(text)):
        external_id = stable_id(row.get("latitude"), row.get("longitude"), row.get("acq_date"), row.get("acq_time"), row.get("satellite"))
        acq_time = str(row.get("acq_time", "0000")).zfill(4)
        acquired_at = f"{row.get('acq_date')}T{acq_time[:2]}:{acq_time[2:]}:00Z"
        yield {
            "external_id": external_id,
            "source": "NASA_FIRMS",
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "brightness": float(row.get("bright_ti4") or row.get("brightness") or 0),
            "confidence": str(row.get("confidence", "unknown")),
            "frp": float(row.get("frp") or 0),
            "scan": float(row.get("scan") or 0),
            "track": float(row.get("track") or 0),
            "acquired_at": acquired_at,
            "updated_at": acquired_at,
            "ingested_at": ingested_at,
            "raw_json": json.dumps(row),
        }


def _bc_perimeter_rows() -> Iterable[dict[str, Any]]:
    params = {"f": "geojson", "where": "1=1", "outFields": "*", "returnGeometry": "true", "resultRecordCount": "1000"}
    ingested_at = now_iso()
    try:
        payload = _request_json(BC_PERIMETERS_URL, params)
    except Exception as exc:
        log.warning(f"BC perimeter fetch failed; emitting labeled replay perimeter rows: {exc}")
        yield from _replay_fire_perimeters()
        return
    for feature in payload.get("features", []):
        props = feature.get("properties", {})
        fire_number = props.get("FIRE_NUMBER") or props.get("fire_number") or props.get("OBJECTID")
        if not fire_number:
            continue
        yield {
            "fire_number": str(fire_number),
            "source": "BC_WILDFIRE",
            "fire_name": props.get("FIRE_NAME") or props.get("FIRELABEL") or "Unnamed BC wildfire",
            "status": props.get("FIRE_STATUS") or props.get("STATUS") or "unknown",
            "geometry_json": json.dumps(feature.get("geometry")),
            "area_hectares": props.get("FIRE_SIZE_HECTARES") or props.get("AREA_HA"),
            "updated_at": ingested_at,
            "ingested_at": ingested_at,
            "raw_json": json.dumps(props),
        }


def _road_event_rows() -> Iterable[dict[str, Any]]:
    ingested_at = now_iso()
    try:
        payload = _request_json(DRIVEBC_EVENTS_URL, {"format": "json"})
    except Exception as exc:
        log.warning(f"DriveBC/Open511 fetch failed; emitting labeled replay road-event rows: {exc}")
        yield from _replay_road_events()
        return
    events = payload.get("events") if isinstance(payload, dict) else payload
    for event in events or []:
        event_id = event.get("id") or event.get("identifier") or event.get("url") or stable_id(event)
        geography = event.get("geography") or {}
        lon, lat = first_lon_lat(geography)
        road = event.get("roads", [{}])[0] if event.get("roads") else {}
        yield {
            "external_id": str(event_id),
            "source": "DRIVEBC_OPEN511",
            "title": event.get("headline") or event.get("event_type") or "DriveBC event",
            "description": event.get("description") or event.get("headline") or "",
            "event_type": event.get("event_type") or "road_event",
            "severity": event.get("severity") or "unknown",
            "road_name": road.get("name") or "unknown",
            "latitude": float(lat) if lat else 52.623474,
            "longitude": float(lon) if lon else -121.761311,
            "geometry_json": json.dumps(geography) if geography else None,
            "starts_at": event.get("created") or event.get("start_date"),
            "ends_at": event.get("end_date"),
            "updated_at": event.get("updated") or ingested_at,
            "ingested_at": ingested_at,
            "raw_json": json.dumps(event),
        }


def _weather_rows(configuration: dict[str, Any]) -> Iterable[dict[str, Any]]:
    lat = float(configuration.get("weather_latitude", 52.622))
    lon = float(configuration.get("weather_longitude", -121.660))
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "kmh",
        "timezone": "UTC",
    }
    try:
        payload = _request_json(OPEN_METEO_URL, params)
    except Exception as exc:
        log.warning(f"Open-Meteo fetch failed; emitting labeled replay weather row: {exc}")
        yield {
            "weather_id": f"OPEN_METEO_REPLAY_{stable_id(lat, lon)}",
            "source": "OPEN_METEO_REPLAY",
            "latitude": lat,
            "longitude": lon,
            "wind_speed_kph": 34.0,
            "wind_direction_degrees": 248,
            "wind_gusts_kph": 49.0,
            "forecast_horizon_hours": 3,
            "updated_at": now_iso(),
            "ingested_at": now_iso(),
            "raw_json": json.dumps({"replay": True, "source_error": str(exc)}),
        }
        return
    current = payload.get("current", {})
    updated_at = utc_datetime(current.get("time"))
    yield {
        "weather_id": f"OPEN_METEO_{stable_id(lat, lon, updated_at)}",
        "source": "OPEN_METEO",
        "latitude": lat,
        "longitude": lon,
        "wind_speed_kph": current.get("wind_speed_10m"),
        "wind_direction_degrees": current.get("wind_direction_10m"),
        "wind_gusts_kph": current.get("wind_gusts_10m"),
        "forecast_horizon_hours": 1,
        "updated_at": updated_at,
        "ingested_at": now_iso(),
        "raw_json": json.dumps(payload),
    }


def _replay_fire_hotspots() -> Iterable[dict[str, Any]]:
    ingested_at = now_iso()
    rows = [
        (52.626, -121.700, 334.2, "high", 62.4),
        (52.635, -121.720, 329.7, "nominal", 48.9),
    ]
    for lat, lon, brightness, confidence, frp in rows:
        yield {
            "external_id": f"FIRMS_REPLAY_{stable_id(lat, lon)}",
            "source": "NASA_FIRMS_REPLAY",
            "latitude": lat,
            "longitude": lon,
            "brightness": brightness,
            "confidence": confidence,
            "frp": frp,
            "scan": 0.43,
            "track": 0.39,
            "acquired_at": "2024-07-23T21:14:00Z",
            "updated_at": ingested_at,
            "ingested_at": ingested_at,
            "raw_json": json.dumps({"replay": True}),
        }


def _replay_fire_perimeters() -> Iterable[dict[str, Any]]:
    ingested_at = now_iso()
    yield {
        "fire_number": "BC_PERIMETER_REPLAY_001",
        "source": "BC_WILDFIRE_REPLAY",
        "fire_name": "Quesnel River Replay Perimeter",
        "status": "out_of_control",
        "geometry_json": json.dumps({
            "type": "Polygon",
            "coordinates": [[
                [-121.742, 52.610],
                [-121.676, 52.612],
                [-121.660, 52.646],
                [-121.728, 52.656],
                [-121.742, 52.610],
            ]],
        }),
        "area_hectares": 740.0,
        "updated_at": ingested_at,
        "ingested_at": ingested_at,
        "raw_json": json.dumps({"replay": True}),
    }


def _replay_road_events() -> Iterable[dict[str, Any]]:
    ingested_at = now_iso()
    yield {
        "external_id": "drivebc.ca/DBC-90684",
        "source": "DRIVEBC_OPEN511_SNAPSHOT",
        "title": "Little Lake Quesnel River Road closed near Williams Lake",
        "description": "Little Lake Quesnel River Road. Washout at West of Likely Road Turnoff near Williams Lake. Road closed. Geotechnical investigation. Assessment in progress. Road closed 10 km West of Likely Road Turnoff. No detour. Next update time Mon Jun 1 at 12:00 PM PDT. Last updated Thu Apr 30 at 3:28 PM PDT. (DBC-90684)",
        "event_type": "INCIDENT",
        "severity": "MAJOR",
        "road_name": "Little Lake Quesnel River Road",
        "latitude": 52.623474,
        "longitude": -121.761311,
        "geometry_json": json.dumps({
            "type": "Point",
            "coordinates": [-121.761311, 52.623474],
        }),
        "starts_at": "2026-04-30T15:28:34-07:00",
        "ends_at": None,
        "updated_at": "2026-04-30T15:28:34-07:00",
        "ingested_at": ingested_at,
        "raw_json": json.dumps({
            "source_snapshot": True,
            "captured_from": "https://api.open511.gov.bc.ca/events/drivebc.ca/DBC-90684",
        }),
    }


def update(configuration: dict[str, Any], state: dict[str, Any]) -> Iterable[Any]:
    stream_counts: dict[str, int] = {}
    streams = {
        "fire_hotspots": _firms_rows(configuration),
        "fire_perimeters": _bc_perimeter_rows(),
        "road_events": _road_event_rows(),
        "weather_observations": _weather_rows(configuration),
    }
    for table, rows in streams.items():
        count = 0
        for row in rows:
            count += 1
            yield op.upsert(table=table, data=row)
        stream_counts[table] = count

    run_id = f"FIVETRAN_RUN_{now_iso()}"
    yield op.upsert(
        table="ingestion_runs",
        data={
            "run_id": run_id,
            "provider": "fivetran",
            "status": "synced",
            "streams_json": json.dumps(stream_counts),
            "created_at": now_iso(),
        },
    )
    yield op.checkpoint(state={"last_run_id": run_id, "last_synced_at": now_iso()})


connector = Connector(update=update, schema=schema)

if __name__ == "__main__":
    connector.debug()
