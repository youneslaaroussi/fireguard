import csv
import hashlib
import io
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agentic.api import create_app as create_agentic_app


ROOT = Path(__file__).resolve().parents[1]


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key, value)


FIRMS_SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT", "VIIRS_NOAA20_SP", "VIIRS_SNPP_SP", "MODIS_SP")
MAX_DAYS = 5
BCWS_CACHE_SECONDS = 60 * 60
BCWS_ACTIVE_FIRES_URL = "https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/BCWS_ActiveFires_PublicView/FeatureServer/0/query"
BCWS_PERIMETERS_URL = "https://services6.arcgis.com/ubm4tcTYICKBpist/ArcGIS/rest/services/BCWS_FirePerimeters_PublicView/FeatureServer/0/query"
BC_EVACUATION_ZONES_PATH = ROOT / "data/public/bc/historical_fire_evacuation_zones_snapshot.json"
BC_PUBLIC_CONTEXT_PATH = ROOT / "data/public/bc/public_emergency_context_snapshot.json"
BC_POLICY_SNIPPETS_PATH = ROOT / "data/public/bc/official_policy_snippets.json"
BC_ROAD_EVENTS_PATH = ROOT / "data/replay/bc_cariboo/road_events_snapshot.json"
BC_WEATHER_SNAPSHOT_PATH = ROOT / "data/replay/bc_cariboo/weather_snapshot.json"
FIRMS_SNAPSHOT_PATH = ROOT / "data/replay/bc_cariboo/firms_snapshot.csv"
FIRMS_SNAPSHOT_METADATA_PATH = ROOT / "data/replay/bc_cariboo/firms_snapshot.metadata.json"
load_env()
agentic_app = create_agentic_app()

app = FastAPI(title="FireGuard API")
app.mount("/api/intelligence", agentic_app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:5174", "http://localhost:5174"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReplayRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=250, gt=1, le=2000)
    start_date: date
    end_date: date
    sources: list[str] = Field(default_factory=lambda: list(FIRMS_SOURCES))
    speed: float = Field(default=3600, gt=1)


def env(name):
    value = os.environ.get(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"missing {name}")
    return value


def data_env_ready():
    return all(
        os.environ.get(name)
        for name in ("ELASTICSEARCH_URL", "ELASTICSEARCH_API_KEY", "ELASTICSEARCH_INDEX_PREFIX")
    )


def http(method, url, body=None, headers=None, timeout=300):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def es(method, path, body=None):
    headers = {"Authorization": f"ApiKey {env('ELASTICSEARCH_API_KEY')}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return json.loads(http(method, env("ELASTICSEARCH_URL").rstrip("/") + path, data, headers))


def es_maybe(method, path, body=None):
    try:
        return es(method, path, body)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def index_name():
    return f"{env('ELASTICSEARCH_INDEX_PREFIX')}-firms"


def cache_index_name():
    return f"{env('ELASTICSEARCH_INDEX_PREFIX')}-firms-cache"


def bcws_incident_index_name():
    return f"{env('ELASTICSEARCH_INDEX_PREFIX')}-bcws-incidents"


def bcws_perimeter_index_name():
    return f"{env('ELASTICSEARCH_INDEX_PREFIX')}-bcws-perimeters"


def bcws_cache_index_name():
    return f"{env('ELASTICSEARCH_INDEX_PREFIX')}-bcws-cache"


def zones_index_name():
    return f"{env('ELASTICSEARCH_INDEX_PREFIX')}-zones"


def shelters_index_name():
    return f"{env('ELASTICSEARCH_INDEX_PREFIX')}-shelters"


def road_events_index_name():
    return f"{env('ELASTICSEARCH_INDEX_PREFIX')}-road-events"


def event_mapping():
    return {
        "location": {"type": "geo_point"},
        "acquired_at": {"type": "date"},
        "acq_date": {"type": "date"},
        "source": {"type": "keyword"},
        "satellite": {"type": "keyword"},
        "instrument": {"type": "keyword"},
        "confidence": {"type": "keyword"},
        "daynight": {"type": "keyword"},
        "version": {"type": "keyword"},
        "frp": {"type": "float"},
        "brightness": {"type": "float"},
        "weather": {
            "properties": {
                "time": {"type": "date"},
                "temperature_2m": {"type": "float"},
                "relative_humidity_2m": {"type": "float"},
                "precipitation": {"type": "float"},
                "wind_speed_10m": {"type": "float"},
                "wind_direction_10m": {"type": "float"},
                "wind_gusts_10m": {"type": "float"},
                "source": {"type": "keyword"},
            }
        },
        "place": {
            "properties": {
                "formatted_address": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "place_id": {"type": "keyword"},
                "types": {"type": "keyword"},
                "source": {"type": "keyword"},
            }
        },
    }


def create_indices():
    event_body = {"settings": {"number_of_shards": 1, "number_of_replicas": 0}, "mappings": {"properties": event_mapping()}}
    cache_body = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "area": {"type": "keyword"},
                "source": {"type": "keyword"},
                "start_date": {"type": "date"},
                "days": {"type": "integer"},
                "status": {"type": "keyword"},
                "indexed": {"type": "integer"},
                "updated_at": {"type": "date"},
            }
        },
    }
    bcws_incident_body = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "area": {"type": "keyword"},
                "source": {"type": "keyword"},
                "fire_number": {"type": "keyword"},
                "incident_name": {"type": "keyword"},
                "fire_status": {"type": "keyword"},
                "fire_cause": {"type": "keyword"},
                "fire_type": {"type": "keyword"},
                "current_size_ha": {"type": "float"},
                "ignition_date": {"type": "date"},
                "fire_out_date": {"type": "date"},
                "geographic_description": {"type": "text"},
                "fire_url": {"type": "keyword"},
                "location": {"type": "geo_point"},
                "updated_at": {"type": "date"},
            }
        },
    }
    bcws_perimeter_body = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "area": {"type": "keyword"},
                "source": {"type": "keyword"},
                "fire_number": {"type": "keyword"},
                "fire_status": {"type": "keyword"},
                "fire_size_hectares": {"type": "float"},
                "track_date": {"type": "date"},
                "load_date": {"type": "date"},
                "fire_url": {"type": "keyword"},
                "feature_area_sqm": {"type": "float"},
                "feature_length_m": {"type": "float"},
                "geometry": {"type": "geo_shape"},
                "updated_at": {"type": "date"},
            }
        },
    }
    bcws_cache_body = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "area": {"type": "keyword"},
                "status": {"type": "keyword"},
                "incident_count": {"type": "integer"},
                "perimeter_count": {"type": "integer"},
                "updated_at": {"type": "date"},
            }
        },
    }
    zones_body = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "zone_id": {"type": "keyword"},
                "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "population": {"type": "integer"},
                "homes": {"type": "integer"},
                "issuing_agency": {"type": "keyword"},
                "event_name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "location": {"type": "geo_point"},
                "geometry": {"type": "geo_shape"},
            }
        },
    }
    shelters_body = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "facility_id": {"type": "keyword"},
                "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "facility_type": {"type": "keyword"},
                "address": {"type": "text"},
                "community": {"type": "keyword"},
                "municipality": {"type": "keyword"},
                "status": {"type": "keyword"},
                "location": {"type": "geo_point"},
                "capacity": {"type": "integer"},
                "updated_at": {"type": "date"},
                "source": {"type": "keyword"},
                "source_url": {"type": "keyword"},
            }
        },
    }
    road_events_body = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "event_id": {"type": "keyword"},
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "description": {"type": "text"},
                "road_name": {"type": "keyword"},
                "event_type": {"type": "keyword"},
                "severity": {"type": "keyword"},
                "status": {"type": "keyword"},
                "location": {"type": "geo_point"},
                "geometry": {"type": "geo_shape"},
                "starts_at": {"type": "date"},
                "ends_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "source": {"type": "keyword"},
                "source_url": {"type": "keyword"},
            }
        },
    }
    for name, body in (
        (index_name(), event_body),
        (cache_index_name(), cache_body),
        (bcws_incident_index_name(), bcws_incident_body),
        (bcws_perimeter_index_name(), bcws_perimeter_body),
        (bcws_cache_index_name(), bcws_cache_body),
        (zones_index_name(), zones_body),
        (shelters_index_name(), shelters_body),
        (road_events_index_name(), road_events_body),
    ):
        try:
            es("PUT", f"/{name}", body)
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
    seed_evacuation_zones()
    seed_shelters()
    seed_road_events()
    seed_firms_snapshot()
    try:
        es("PUT", f"/{index_name()}/_mapping", {"properties": event_mapping()})
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise


def bbox(lat, lon, radius_km):
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / max(1.0, 111.0 * math.cos(math.radians(lat)))
    return (
        max(-180, lon - lon_delta),
        max(-90, lat - lat_delta),
        min(180, lon + lon_delta),
        min(90, lat + lat_delta),
    )


def ranges(start, end):
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=MAX_DAYS - 1))
        yield current, (chunk_end - current).days + 1
        current = chunk_end + timedelta(days=1)


def parse_time(row):
    value = f"{row['acq_date']} {row.get('acq_time', '').zfill(4)}"
    return datetime.strptime(value, "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)


def as_float(row, key):
    try:
        return float(row[key]) if row.get(key) not in (None, "") else None
    except ValueError:
        return None


def at(values, key, index):
    series = values.get(key)
    if not series or index >= len(series):
        return None
    return series[index]


def point_weather(lat, lon, acquired_at):
    when = acquired_at.astimezone(timezone.utc)
    params = {
        "latitude": f"{lat:.6f}",
        "longitude": f"{lon:.6f}",
        "start_date": when.date().isoformat(),
        "end_date": when.date().isoformat(),
        "hourly": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ]
        ),
        "timezone": "UTC",
    }
    url = f"https://archive-api.open-meteo.com/v1/archive?{urllib.parse.urlencode(params)}"
    data = json.loads(http("GET", url, timeout=30))
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    target = when.replace(minute=0, second=0, microsecond=0).replace(tzinfo=None)
    parsed = [datetime.fromisoformat(value) for value in times]
    index = min(range(len(parsed)), key=lambda i: abs((parsed[i] - target).total_seconds()))
    return {
        "time": times[index],
        "temperature_2m": at(hourly, "temperature_2m", index),
        "relative_humidity_2m": at(hourly, "relative_humidity_2m", index),
        "precipitation": at(hourly, "precipitation", index),
        "wind_speed_10m": at(hourly, "wind_speed_10m", index),
        "wind_direction_10m": at(hourly, "wind_direction_10m", index),
        "wind_gusts_10m": at(hourly, "wind_gusts_10m", index),
        "source": "Open-Meteo",
    }


def reverse_geocode(lat, lon):
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        return None
    params = urllib.parse.urlencode({"latlng": f"{lat},{lon}", "key": key})
    data = json.loads(http("GET", f"https://maps.googleapis.com/maps/api/geocode/json?{params}", timeout=30))
    if data.get("status") != "OK" or not data.get("results"):
        return None
    result = data["results"][0]
    return {
        "formatted_address": result.get("formatted_address"),
        "place_id": result.get("place_id"),
        "types": result.get("types", []),
        "source": "Google Maps",
    }


def safe_point_weather(lat, lon, acquired_at):
    try:
        return point_weather(lat, lon, acquired_at)
    except Exception:
        return None


def safe_reverse_geocode(lat, lon):
    try:
        return reverse_geocode(lat, lon)
    except Exception:
        return None


def iso_from_ms(value):
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def compact_doc(doc):
    return {key: value for key, value in doc.items() if value is not None}


def ring_centroid(ring):
    if not ring:
        return None
    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if len(points) < 3:
        lon = sum(point[0] for point in points) / max(1, len(points))
        lat = sum(point[1] for point in points) / max(1, len(points))
        return lon, lat, 0.0
    twice_area = 0.0
    cx = 0.0
    cy = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        cross = point[0] * next_point[1] - next_point[0] * point[1]
        twice_area += cross
        cx += (point[0] + next_point[0]) * cross
        cy += (point[1] + next_point[1]) * cross
    if abs(twice_area) < 1e-12:
        lon = sum(point[0] for point in points) / len(points)
        lat = sum(point[1] for point in points) / len(points)
        return lon, lat, 0.0
    return cx / (3 * twice_area), cy / (3 * twice_area), twice_area / 2


def geometry_centroid(geometry):
    if not isinstance(geometry, dict):
        return None
    weighted_lon = 0.0
    weighted_lat = 0.0
    total_area = 0.0
    polygons = []
    if geometry.get("type") == "Polygon":
        polygons = [geometry.get("coordinates") or []]
    elif geometry.get("type") == "MultiPolygon":
        polygons = geometry.get("coordinates") or []
    for polygon in polygons:
        if not polygon:
            continue
        centroid = ring_centroid(polygon[0])
        if centroid is None:
            continue
        lon, lat, area = centroid
        weight = abs(area) if area else 1.0
        weighted_lon += lon * weight
        weighted_lat += lat * weight
        total_area += weight
    if total_area <= 0:
        return None
    return {"lon": weighted_lon / total_area, "lat": weighted_lat / total_area}


def zone_doc_from_feature(feature):
    props = feature.get("properties") or {}
    geometry = feature.get("geometry")
    zone_id = props.get("EMRG_OAAH_SYSID")
    centroid = geometry_centroid(geometry)
    if zone_id is None or centroid is None or geometry is None:
        return None
    return compact_doc(
        {
            "zone_id": str(zone_id),
            "name": props.get("ORDER_ALERT_NAME"),
            "population": props.get("MULTI_SOURCED_POPULATION"),
            "homes": props.get("MULTI_SOURCED_HOMES"),
            "issuing_agency": props.get("ISSUING_AGENCY"),
            "event_name": props.get("EVENT_NAME"),
            "location": centroid,
            "geometry": geometry,
        }
    )


def seed_evacuation_zones():
    existing = es("GET", f"/{zones_index_name()}/_count")
    if int(existing.get("count", 0)) > 0:
        return {"seeded": False, "count": existing.get("count", 0)}
    snapshot = load_json_file(BC_EVACUATION_ZONES_PATH, {})
    features = snapshot.get("features") if isinstance(snapshot, dict) else []
    docs = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        doc = zone_doc_from_feature(feature)
        if doc is not None:
            docs.append((doc["zone_id"], doc))
    indexed = bulk(docs, zones_index_name())
    es("POST", f"/{zones_index_name()}/_refresh")
    return {"seeded": True, "count": indexed}


def shelter_doc_from_record(record, source, source_url):
    location = record.get("location") or {}
    lat = location.get("lat")
    lon = location.get("lon")
    facility_id = record.get("facility_id")
    if facility_id is None or lat is None or lon is None:
        return None
    return compact_doc(
        {
            "facility_id": str(facility_id),
            "name": record.get("name"),
            "facility_type": record.get("facility_type"),
            "address": record.get("address"),
            "community": record.get("community"),
            "municipality": record.get("municipality"),
            "status": record.get("status"),
            "location": {"lat": lat, "lon": lon},
            "capacity": record.get("capacity"),
            "updated_at": record.get("updated_at"),
            "source": source,
            "source_url": source_url,
        }
    )


def seed_shelters():
    existing = es("GET", f"/{shelters_index_name()}/_count")
    if int(existing.get("count", 0)) > 0:
        return {"seeded": False, "count": existing.get("count", 0)}
    public_context = load_json_file(BC_PUBLIC_CONTEXT_PATH, {})
    ess_source = public_context.get("ess_facilities") if isinstance(public_context, dict) else {}
    if not isinstance(ess_source, dict):
        return {"seeded": False, "count": 0}
    docs = []
    for record in ess_source.get("records", []):
        if not isinstance(record, dict):
            continue
        doc = shelter_doc_from_record(record, ess_source.get("source"), ess_source.get("source_url"))
        if doc is not None:
            docs.append((doc["facility_id"], doc))
    indexed = bulk(docs, shelters_index_name())
    es("POST", f"/{shelters_index_name()}/_refresh")
    return {"seeded": True, "count": indexed}


def road_event_doc_from_record(record):
    location = record.get("location") or {}
    lat = location.get("lat")
    lon = location.get("lon")
    event_id = record.get("external_id") or record.get("event_id")
    if event_id is None or lat is None or lon is None:
        return None
    return compact_doc(
        {
            "event_id": str(event_id),
            "title": record.get("title"),
            "description": record.get("description"),
            "road_name": record.get("road_name"),
            "event_type": record.get("event_type"),
            "severity": record.get("severity"),
            "status": record.get("status") or "ACTIVE",
            "location": {"lat": lat, "lon": lon},
            "geometry": record.get("geometry"),
            "starts_at": record.get("starts_at"),
            "ends_at": record.get("ends_at"),
            "updated_at": record.get("updated_at"),
            "source": record.get("source"),
            "source_url": record.get("source_url"),
        }
    )


def seed_road_events():
    existing = es("GET", f"/{road_events_index_name()}/_count")
    if int(existing.get("count", 0)) > 0:
        return {"seeded": False, "count": existing.get("count", 0)}
    snapshot = load_json_file(BC_ROAD_EVENTS_PATH, [])
    docs = []
    for record in snapshot:
        if not isinstance(record, dict):
            continue
        doc = road_event_doc_from_record(record)
        if doc is not None:
            docs.append((doc["event_id"], doc))
    indexed = bulk(docs, road_events_index_name())
    es("POST", f"/{road_events_index_name()}/_refresh")
    return {"seeded": True, "count": indexed}


def snapshot_firms_source():
    metadata = load_json_file(FIRMS_SNAPSHOT_METADATA_PATH, {})
    if isinstance(metadata, dict) and isinstance(metadata.get("source_product"), str):
        return metadata["source_product"]
    return "VIIRS_NOAA20_SP"


def seed_firms_snapshot():
    existing = es("GET", f"/{index_name()}/_count")
    if int(existing.get("count", 0)) > 0 or not FIRMS_SNAPSHOT_PATH.exists():
        return {"seeded": False, "count": existing.get("count", 0)}
    source = snapshot_firms_source()
    docs = []
    with FIRMS_SNAPSHOT_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("latitude") and row.get("longitude"):
                docs.append(transform(row, source))
    indexed = bulk(docs, index_name())
    es("POST", f"/{index_name()}/_refresh")
    return {"seeded": True, "count": indexed}


def arcgis_features(url, area_bounds, fields):
    west, south, east, north = area_bounds
    features = []
    offset = 0
    page_size = 1000
    while True:
        params = {
            "where": "1=1",
            "outFields": fields,
            "f": "geojson",
            "geometry": f"{west},{south},{east},{north}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": "true",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        data = json.loads(http("GET", f"{url}?{urllib.parse.urlencode(params)}", timeout=120))
        batch = data.get("features") or []
        features.extend(batch)
        if len(batch) < page_size:
            return features
        offset += page_size


def normalize_bcws_incident(feature, area):
    props = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or [props.get("LONGITUDE"), props.get("LATITUDE")]
    lon = float(coords[0])
    lat = float(coords[1])
    return compact_doc(
        {
            "area": area,
            "source": "BCWS",
            "fire_number": props.get("FIRE_NUMBER"),
            "incident_name": props.get("INCIDENT_NAME"),
            "fire_status": props.get("FIRE_STATUS"),
            "fire_cause": props.get("FIRE_CAUSE"),
            "fire_type": props.get("FIRE_TYPE"),
            "current_size_ha": props.get("CURRENT_SIZE"),
            "ignition_date": iso_from_ms(props.get("IGNITION_DATE")),
            "fire_out_date": iso_from_ms(props.get("FIRE_OUT_DATE")),
            "geographic_description": props.get("GEOGRAPHIC_DESCRIPTION"),
            "fire_url": props.get("FIRE_URL"),
            "latitude": lat,
            "longitude": lon,
            "location": {"lat": lat, "lon": lon},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def normalize_bcws_perimeter(feature, area):
    props = feature.get("properties") or {}
    return compact_doc(
        {
            "area": area,
            "source": "BCWS",
            "fire_number": props.get("FIRE_NUMBER"),
            "fire_status": props.get("FIRE_STATUS"),
            "fire_size_hectares": props.get("FIRE_SIZE_HECTARES"),
            "track_date": iso_from_ms(props.get("TRACK_DATE")),
            "load_date": iso_from_ms(props.get("LOAD_DATE")),
            "fire_url": props.get("FIRE_URL"),
            "feature_area_sqm": props.get("FEATURE_AREA_SQM"),
            "feature_length_m": props.get("FEATURE_LENGTH_M"),
            "geometry": feature.get("geometry"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def bcws_doc_id(area, kind, doc):
    key = "|".join([area, kind, str(doc.get("fire_number")), str(doc.get("track_date")), str(doc.get("latitude")), str(doc.get("longitude"))])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def bcws_cache_id(area):
    return hashlib.sha256(f"bcws-v3|{area}".encode("utf-8")).hexdigest()


def bcws_cache_get(area):
    doc = es_maybe("GET", f"/{bcws_cache_index_name()}/_doc/{bcws_cache_id(area)}")
    if not doc:
        return None
    source_doc = doc.get("_source") or {}
    if source_doc.get("status") != "done":
        return None
    updated_at = source_doc.get("updated_at")
    if not updated_at:
        return None
    age = datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)
    return source_doc if age.total_seconds() <= BCWS_CACHE_SECONDS else None


def bcws_cache_put(area, incident_count, perimeter_count):
    es(
        "PUT",
        f"/{bcws_cache_index_name()}/_doc/{bcws_cache_id(area)}",
        {
            "area": area,
            "status": "done",
            "incident_count": incident_count,
            "perimeter_count": perimeter_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def delete_area(index, area):
    es("POST", f"/{index}/_delete_by_query?refresh=true", {"query": {"term": {"area": area}}})


def query_area_docs(index, area, size=1000):
    body = {
        "size": size,
        "query": {"term": {"area": area}},
        "sort": [{"updated_at": "desc"}],
    }
    hits = es("POST", f"/{index}/_search", body)["hits"]["hits"]
    return [hit["_source"] for hit in hits]


def collect_bcws_context(area, area_bounds):
    cached = bcws_cache_get(area)
    if cached:
        return {
            "cached": True,
            "incidents": query_area_docs(bcws_incident_index_name(), area),
            "perimeters": query_area_docs(bcws_perimeter_index_name(), area),
        }
    incident_features = arcgis_features(
        BCWS_ACTIVE_FIRES_URL,
        area_bounds,
        "FIRE_NUMBER,INCIDENT_NAME,FIRE_STATUS,CURRENT_SIZE,FIRE_CAUSE,FIRE_TYPE,GEOGRAPHIC_DESCRIPTION,FIRE_URL,IGNITION_DATE,FIRE_OUT_DATE,LATITUDE,LONGITUDE",
    )
    perimeter_features = arcgis_features(
        BCWS_PERIMETERS_URL,
        area_bounds,
        "FIRE_NUMBER,FIRE_STATUS,FIRE_SIZE_HECTARES,TRACK_DATE,LOAD_DATE,FIRE_URL,FEATURE_AREA_SQM,FEATURE_LENGTH_M",
    )
    incidents = [normalize_bcws_incident(feature, area) for feature in incident_features]
    perimeters = [normalize_bcws_perimeter(feature, area) for feature in perimeter_features if feature.get("geometry")]
    delete_area(bcws_incident_index_name(), area)
    delete_area(bcws_perimeter_index_name(), area)
    bulk([(bcws_doc_id(area, "incident", doc), doc) for doc in incidents], bcws_incident_index_name())
    bulk([(bcws_doc_id(area, "perimeter", doc), doc) for doc in perimeters], bcws_perimeter_index_name())
    bcws_cache_put(area, len(incidents), len(perimeters))
    return {"cached": False, "incidents": incidents, "perimeters": perimeters}


def load_json_file(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def in_replay_radius(record, req):
    lat = record.get("latitude")
    lon = record.get("longitude")
    if lat is None or lon is None:
        return False
    return distance_km(req.latitude, req.longitude, lat, lon) <= req.radius_km


def public_evacuation_zone(feature, source_url):
    props = feature.get("properties") or {}
    return compact_doc(
        {
            "id": props.get("EMRG_OAAH_SYSID"),
            "event_name": props.get("EVENT_NAME"),
            "event_type": props.get("EVENT_TYPE"),
            "order_alert_name": props.get("ORDER_ALERT_NAME"),
            "status": props.get("ORDER_ALERT_STATUS"),
            "issuing_agency": props.get("ISSUING_AGENCY"),
            "municipality": props.get("MUNICIPALITY"),
            "population": props.get("MULTI_SOURCED_POPULATION"),
            "homes": props.get("MULTI_SOURCED_HOMES"),
            "event_start_date": iso_from_ms(props.get("EVENT_START_DATE")),
            "all_clear_date": iso_from_ms(props.get("ALL_CLEAR_DATE")),
            "geometry": feature.get("geometry"),
            "source": "BC_EVACUATION_ZONES_SNAPSHOT",
            "source_url": source_url,
        }
    )


def public_evacuation_record(record, source, source_url):
    location = record.get("location") or {}
    return compact_doc(
        {
            "order_alert_id": record.get("order_alert_id"),
            "event_name": record.get("event_name"),
            "event_type": record.get("event_type"),
            "order_alert_name": record.get("order_alert_name"),
            "status": record.get("status"),
            "issuing_agency": record.get("issuing_agency"),
            "population": record.get("population"),
            "homes": record.get("homes"),
            "latitude": location.get("lat"),
            "longitude": location.get("lon"),
            "event_start_date": record.get("event_start_date"),
            "updated_at": record.get("updated_at"),
            "source": source,
            "source_url": source_url,
        }
    )


def public_ess_facility(record, source, source_url):
    location = record.get("location") or {}
    return compact_doc(
        {
            "facility_id": record.get("facility_id"),
            "name": record.get("name"),
            "facility_type": record.get("facility_type"),
            "address": record.get("address"),
            "community": record.get("community"),
            "municipality": record.get("municipality"),
            "status": record.get("status"),
            "latitude": location.get("lat"),
            "longitude": location.get("lon"),
            "updated_at": record.get("updated_at"),
            "source": source,
            "source_url": source_url,
        }
    )


def public_road_event(record):
    location = record.get("location") or {}
    return compact_doc(
        {
            "source": record.get("source"),
            "external_id": record.get("external_id"),
            "title": record.get("title"),
            "description": record.get("description"),
            "event_type": record.get("event_type"),
            "severity": record.get("severity"),
            "road_name": record.get("road_name"),
            "latitude": location.get("lat"),
            "longitude": location.get("lon"),
            "geometry": record.get("geometry"),
            "starts_at": record.get("starts_at"),
            "ends_at": record.get("ends_at"),
            "updated_at": record.get("updated_at"),
            "source_url": record.get("source_url"),
        }
    )


def public_weather_snapshot(record):
    location = record.get("location") or {}
    return compact_doc(
        {
            "source": record.get("source"),
            "latitude": location.get("lat"),
            "longitude": location.get("lon"),
            "wind_speed_kph": record.get("wind_speed_kph"),
            "wind_direction_degrees": record.get("wind_direction_degrees"),
            "wind_gusts_kph": record.get("wind_gusts_kph"),
            "forecast_horizon_hours": record.get("forecast_horizon_hours"),
        }
    )


def load_replay_local_context(req):
    zones_snapshot = load_json_file(BC_EVACUATION_ZONES_PATH, {})
    public_context = load_json_file(BC_PUBLIC_CONTEXT_PATH, {})
    policy_snapshot = load_json_file(BC_POLICY_SNIPPETS_PATH, {})
    road_snapshot = load_json_file(BC_ROAD_EVENTS_PATH, [])
    weather_snapshot = load_json_file(BC_WEATHER_SNAPSHOT_PATH, {})

    zone_source_url = zones_snapshot.get("source_url") if isinstance(zones_snapshot, dict) else None
    zone_features = zones_snapshot.get("features") if isinstance(zones_snapshot, dict) else []
    evacuation_zones = [
        public_evacuation_zone(feature, zone_source_url)
        for feature in zone_features
        if isinstance(feature, dict) and feature.get("geometry")
    ]

    evacuation_source = public_context.get("evacuation_orders_alerts") if isinstance(public_context, dict) else {}
    if not isinstance(evacuation_source, dict):
        evacuation_source = {}
    ess_source = public_context.get("ess_facilities") if isinstance(public_context, dict) else {}
    if not isinstance(ess_source, dict):
        ess_source = {}
    evacuation_records = [
        item
        for item in (
            public_evacuation_record(record, evacuation_source.get("source"), evacuation_source.get("source_url"))
            for record in evacuation_source.get("records", [])
            if isinstance(record, dict)
        )
        if in_replay_radius(item, req)
    ]
    ess_facilities = [
        item
        for item in (
            public_ess_facility(record, ess_source.get("source"), ess_source.get("source_url"))
            for record in ess_source.get("records", [])
            if isinstance(record, dict)
        )
        if in_replay_radius(item, req)
    ]
    road_events = [
        item
        for item in (public_road_event(record) for record in road_snapshot if isinstance(record, dict))
        if in_replay_radius(item, req)
    ]
    weather = public_weather_snapshot(weather_snapshot) if isinstance(weather_snapshot, dict) else {}
    if weather and not in_replay_radius(weather, req):
        weather = {}
    policies = policy_snapshot.get("records") if isinstance(policy_snapshot, dict) else []

    return {
        "evacuation_zones": evacuation_zones,
        "evacuation_records": evacuation_records,
        "ess_facilities": ess_facilities,
        "road_events": road_events,
        "weather_snapshot": weather or None,
        "policy_snippets": [
            compact_doc(
                {
                    "policy_id": record.get("policy_id"),
                    "title": record.get("title"),
                    "source": record.get("source"),
                    "source_url": record.get("source_url"),
                    "body": record.get("body"),
                    "applies_to": record.get("applies_to"),
                }
            )
            for record in policies
            if isinstance(record, dict)
        ],
    }


def distance_km(lat1, lon1, lat2, lon2):
    radius = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point_in_ring(lon, lat, ring):
    inside = False
    if not ring:
        return False
    previous = ring[-1]
    for current in ring:
        xi, yi = current[0], current[1]
        xj, yj = previous[0], previous[1]
        crosses = (yi > lat) != (yj > lat)
        if crosses:
            x_at_lat = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_at_lat:
                inside = not inside
        previous = current
    return inside


def point_in_polygon(lon, lat, rings):
    if not rings or not point_in_ring(lon, lat, rings[0]):
        return False
    return not any(point_in_ring(lon, lat, ring) for ring in rings[1:])


def geometry_contains_point(geometry, lon, lat):
    if not geometry:
        return False
    if geometry.get("type") == "Polygon":
        return point_in_polygon(lon, lat, geometry.get("coordinates") or [])
    if geometry.get("type") == "MultiPolygon":
        return any(point_in_polygon(lon, lat, polygon) for polygon in geometry.get("coordinates") or [])
    return False


def public_incident(doc, distance=None):
    out = {
        "fire_number": doc.get("fire_number"),
        "incident_name": doc.get("incident_name"),
        "fire_status": doc.get("fire_status"),
        "current_size_ha": doc.get("current_size_ha"),
        "fire_cause": doc.get("fire_cause"),
        "fire_type": doc.get("fire_type"),
        "geographic_description": doc.get("geographic_description"),
        "fire_url": doc.get("fire_url"),
        "latitude": doc.get("latitude"),
        "longitude": doc.get("longitude"),
        "source": doc.get("source"),
    }
    if distance is not None:
        out["distance_km"] = distance
    return compact_doc(out)


def public_perimeter(doc):
    return compact_doc(
        {
            "fire_number": doc.get("fire_number"),
            "fire_status": doc.get("fire_status"),
            "fire_size_hectares": doc.get("fire_size_hectares"),
            "track_date": doc.get("track_date"),
            "load_date": doc.get("load_date"),
            "fire_url": doc.get("fire_url"),
            "feature_area_sqm": doc.get("feature_area_sqm"),
            "feature_length_m": doc.get("feature_length_m"),
            "geometry": doc.get("geometry"),
            "source": doc.get("source"),
        }
    )


def attach_bcws(event, context):
    lat = event["latitude"]
    lon = event["longitude"]
    nearest = None
    for incident in context.get("incidents", []):
        if incident.get("latitude") is None or incident.get("longitude") is None:
            continue
        distance = distance_km(lat, lon, incident["latitude"], incident["longitude"])
        if nearest is None or distance < nearest[0]:
            nearest = (distance, incident)
    contained = None
    for perimeter in context.get("perimeters", []):
        if geometry_contains_point(perimeter.get("geometry"), lon, lat):
            contained = perimeter
            break
    event["bcws"] = {
        "incident": public_incident(nearest[1], nearest[0]) if nearest and nearest[0] <= 25 else None,
        "perimeter": public_perimeter(contained) if contained else None,
    }


def weather_cache_key(doc):
    acquired_at = datetime.fromisoformat(doc["acquired_at"]).astimezone(timezone.utc)
    hour = acquired_at.replace(minute=0, second=0, microsecond=0).isoformat()
    return (round(doc["latitude"], 1), round(doc["longitude"], 1), hour)


def place_cache_key(doc):
    return (round(doc["latitude"], 2), round(doc["longitude"], 2))


def transform(row, source):
    lat = float(row["latitude"])
    lon = float(row["longitude"])
    acquired_at = parse_time(row)
    brightness = as_float(row, "bright_ti4")
    if brightness is None:
        brightness = as_float(row, "brightness")
    doc = {
        "source": source,
        "latitude": lat,
        "longitude": lon,
        "location": {"lat": lat, "lon": lon},
        "acq_date": row["acq_date"],
        "acq_time": row.get("acq_time"),
        "acquired_at": acquired_at.isoformat(),
        "satellite": row.get("satellite"),
        "instrument": row.get("instrument"),
        "confidence": row.get("confidence"),
        "version": row.get("version"),
        "daynight": row.get("daynight"),
        "frp": as_float(row, "frp"),
        "brightness": brightness,
        "raw": row,
    }
    key = "|".join(
        [
            source,
            row.get("latitude", ""),
            row.get("longitude", ""),
            row.get("acq_date", ""),
            row.get("acq_time", ""),
            row.get("satellite", ""),
            row.get("instrument", ""),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest(), doc


def enrich(doc, weather_cache, place_cache):
    weather_key = weather_cache_key(doc)
    if weather_key not in weather_cache:
        weather_cache[weather_key] = safe_point_weather(doc["latitude"], doc["longitude"], datetime.fromisoformat(doc["acquired_at"]))
    place_key = place_cache_key(doc)
    if place_key not in place_cache:
        place_cache[place_key] = safe_reverse_geocode(doc["latitude"], doc["longitude"])
    doc["weather"] = weather_cache[weather_key]
    doc["place"] = place_cache[place_key]


def bulk(docs, target_index=None):
    lines = []
    for doc_id, doc in docs:
        lines.append(json.dumps({"index": {"_index": target_index or index_name(), "_id": doc_id}}, separators=(",", ":")))
        lines.append(json.dumps(doc, separators=(",", ":")))
    if not lines:
        return 0
    headers = {"Authorization": f"ApiKey {env('ELASTICSEARCH_API_KEY')}", "Content-Type": "application/x-ndjson"}
    raw = http("POST", env("ELASTICSEARCH_URL").rstrip("/") + "/_bulk", ("\n".join(lines) + "\n").encode("utf-8"), headers)
    out = json.loads(raw)
    if out.get("errors"):
        raise RuntimeError("bulk index failed")
    return len(out["items"])


def cache_id(source, area, start, days):
    return hashlib.sha256(f"{source}|{area}|{start.isoformat()}|{days}".encode("utf-8")).hexdigest()


def cache_get(source, area, start, days):
    doc = es_maybe("GET", f"/{cache_index_name()}/_doc/{cache_id(source, area, start, days)}")
    if not doc:
        return None
    source_doc = doc.get("_source") or {}
    return source_doc if source_doc.get("status") == "done" else None


def cache_put(source, area, start, days, indexed):
    doc = {
        "source": source,
        "area": area,
        "start_date": start.isoformat(),
        "days": days,
        "status": "done",
        "indexed": indexed,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    es("PUT", f"/{cache_index_name()}/_doc/{cache_id(source, area, start, days)}", doc)


def collect_chunk(source, area, start, days, weather_cache, place_cache):
    cached = cache_get(source, area, start, days)
    if cached:
        return cached.get("indexed", 0), True
    map_key = os.environ.get("NASA_FIRMS_MAP_KEY")
    if not map_key:
        seeded = seed_firms_snapshot()
        cache_put(source, area, start, days, int(seeded.get("count", 0)))
        return int(seeded.get("count", 0)), True
    url = "/".join(
        [
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv",
            urllib.parse.quote(map_key),
            source,
            area,
            str(days),
            start.isoformat(),
        ]
    )
    rows = csv.DictReader(io.StringIO(http("GET", url)))
    indexed = 0
    batch = []
    for row in rows:
        if row.get("latitude") and row.get("longitude"):
            doc_id, doc = transform(row, source)
            enrich(doc, weather_cache, place_cache)
            batch.append((doc_id, doc))
        if len(batch) >= 1000:
            indexed += bulk(batch)
            batch = []
    if batch:
        indexed += bulk(batch)
    cache_put(source, area, start, days, indexed)
    return indexed, False


def query_events(req, start, days, area_bounds, source=None):
    west, south, east, north = area_bounds
    end = start + timedelta(days=days)
    filters = [
        {"range": {"acquired_at": {"gte": start.isoformat(), "lt": end.isoformat()}}},
        {"geo_bounding_box": {"location": {"top_left": {"lat": north, "lon": west}, "bottom_right": {"lat": south, "lon": east}}}},
    ]
    if source:
        filters.append({"term": {"source": source}})
    else:
        filters.append({"terms": {"source": req.sources}})
    body = {
        "size": 1000,
        "sort": [{"acquired_at": "asc"}],
        "query": {
            "bool": {
                "filter": filters
            },
        },
        "_source": [
            "source",
            "acquired_at",
            "latitude",
            "longitude",
            "confidence",
            "frp",
            "brightness",
            "satellite",
            "instrument",
            "weather",
            "place",
        ],
    }
    scroll_id = None
    try:
        response = es("POST", f"/{index_name()}/_search?scroll=1m", body)
        scroll_id = response.get("_scroll_id")
        while True:
            hits = response["hits"]["hits"]
            if not hits:
                break
            for hit in hits:
                yield hit["_source"]
            if not scroll_id:
                break
            response = es("POST", "/_search/scroll", {"scroll": "1m", "scroll_id": scroll_id})
            scroll_id = response.get("_scroll_id")
    finally:
        if scroll_id:
            try:
                es("DELETE", "/_search/scroll", {"scroll_id": [scroll_id]})
            except Exception:
                pass


def load_zone_centroids():
    body = {
        "size": 1000,
        "query": {"match_all": {}},
        "_source": ["zone_id", "name", "population", "homes", "issuing_agency", "event_name", "location"],
    }
    hits = es("POST", f"/{zones_index_name()}/_search", body)["hits"]["hits"]
    zones = []
    for hit in hits:
        source = hit.get("_source") or {}
        location = source.get("location") or {}
        zone_lat = location.get("lat")
        zone_lon = location.get("lon")
        if zone_lat is None or zone_lon is None:
            continue
        zones.append(
            {
                "name": source.get("name"),
                "population": source.get("population"),
                "homes": source.get("homes"),
                "latitude": zone_lat,
                "longitude": zone_lon,
            }
        )
    return zones


def threat_for_event(event, zones):
    frp = event.get("frp")
    lat = event.get("latitude")
    lon = event.get("longitude")
    if frp is None or frp < 50 or lat is None or lon is None:
        return None
    nearest = None
    for zone in zones:
        distance = distance_km(lat, lon, zone["latitude"], zone["longitude"])
        if distance > 150:
            continue
        if nearest is None or distance < nearest[1]:
            nearest = (zone, distance)
    if nearest is None:
        return None
    zone, distance = nearest
    return {
        "type": "threat",
        "hotspot": {
            "lat": lat,
            "lon": lon,
            "frp": frp,
            "confidence": event.get("confidence"),
            "source": event.get("source"),
            "acquired_at": event.get("acquired_at"),
        },
        "zone": {
            "name": zone.get("name"),
            "population": zone.get("population"),
            "homes": zone.get("homes"),
            "latitude": zone.get("latitude"),
            "longitude": zone.get("longitude"),
            "distance_km": round(distance, 2),
        },
    }


def ndjson(payload):
    return json.dumps(payload, separators=(",", ":")) + "\n"


def replay_lines(req):
    create_indices()
    area_bounds = bbox(req.latitude, req.longitude, req.radius_km)
    area = ",".join(f"{value:.6f}" for value in area_bounds)
    weather_cache = {}
    place_cache = {}
    emitted = 0
    threat_emitted = False
    zones = load_zone_centroids()
    yield ndjson({"type": "started", "area": area})
    bcws_context = {"incidents": [], "perimeters": [], "cached": False}
    local_context = load_replay_local_context(req)
    try:
        bcws_context = collect_bcws_context(area, area_bounds)
        yield ndjson(
            {
                "type": "context",
                "cached": bcws_context["cached"],
                "incidents": [public_incident(doc) for doc in bcws_context["incidents"]],
                "perimeters": [public_perimeter(doc) for doc in bcws_context["perimeters"]],
                **local_context,
            }
        )
    except Exception as exc:
        yield ndjson({"type": "error", "error": f"BCWS context failed: {exc}"})
        yield ndjson(
            {
                "type": "context",
                "cached": False,
                "incidents": [],
                "perimeters": [],
                **local_context,
            }
        )
    for start, days in ranges(req.start_date, req.end_date):
        for source in req.sources:
            if source not in FIRMS_SOURCES:
                yield ndjson({"type": "error", "error": f"unsupported source {source}"})
                return
            yield ndjson(
                {
                    "type": "chunk_start",
                    "source": source,
                    "start_date": start.isoformat(),
                    "days": days,
                    "cached": cache_get(source, area, start, days) is not None,
                }
            )
            try:
                indexed, cached = collect_chunk(source, area, start, days, weather_cache, place_cache)
            except Exception as exc:
                yield ndjson(
                    {
                        "type": "error",
                        "error": f"{source} {start.isoformat()} collection failed: {exc}",
                    }
                )
                continue
            yield ndjson(
                {
                    "type": "chunk",
                    "source": source,
                    "start_date": start.isoformat(),
                    "days": days,
                    "cached": cached,
                    "indexed": indexed,
                }
            )
            time.sleep(0.1)

    replay_days = (req.end_date - req.start_date).days + 1
    base_at = None
    sim_clock = None
    for event in query_events(req, req.start_date, replay_days, area_bounds):
        event_at = datetime.fromisoformat(event["acquired_at"])
        if base_at is None:
            base_at = event_at
            sim_clock = event_at
        wait_seconds = max(0, (event_at - sim_clock).total_seconds() / req.speed)
        if wait_seconds:
            time.sleep(wait_seconds)
        sim_clock = event_at
        event["replay_second"] = (event_at - base_at).total_seconds() / req.speed
        attach_bcws(event, bcws_context)
        if not threat_emitted:
            threat = threat_for_event(event, zones)
            if threat is not None:
                yield ndjson(threat)
                threat_emitted = True
        emitted += 1
        yield ndjson({"type": "event", "event": event})
    yield ndjson({"type": "done", "events": emitted})


@app.on_event("startup")
def startup():
    load_env()
    if data_env_ready():
        create_indices()


@app.on_event("startup")
async def agentic_startup():
    await agentic_app.state.engine.start()


@app.on_event("shutdown")
async def agentic_shutdown():
    await agentic_app.state.engine.close()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {"mapbox_access_token": os.environ.get("MAPBOX_ACCESS_TOKEN", "")}


@app.get("/api/stats")
def stats():
    create_indices()
    firms = es(
        "POST",
        f"/{index_name()}/_search",
        {
            "size": 0,
            "track_total_hits": True,
            "aggs": {
                "min_time": {"min": {"field": "acquired_at"}},
                "max_time": {"max": {"field": "acquired_at"}},
                "sources": {"terms": {"field": "source", "size": 20}},
            },
        },
    )
    incidents = es("GET", f"/{bcws_incident_index_name()}/_count")
    perimeters = es("GET", f"/{bcws_perimeter_index_name()}/_count")
    total = firms["hits"]["total"]
    return {
        "firms_count": total["value"] if isinstance(total, dict) else total,
        "bcws_incident_count": incidents["count"],
        "bcws_perimeter_count": perimeters["count"],
        "min_acquired_at": firms["aggregations"]["min_time"].get("value_as_string"),
        "max_acquired_at": firms["aggregations"]["max_time"].get("value_as_string"),
        "sources": [
            {"source": bucket["key"], "count": bucket["doc_count"]}
            for bucket in firms["aggregations"]["sources"]["buckets"]
        ],
    }


@app.post("/api/replay/stream")
def replay_stream(req: ReplayRequest):
    if req.end_date < req.start_date:
        raise HTTPException(status_code=400, detail="end before start")
    return StreamingResponse(replay_lines(req), media_type="application/x-ndjson")
