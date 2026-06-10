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
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)


FIRMS_SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")
MAX_DAYS = 5
BCWS_CACHE_SECONDS = 60 * 60
BCWS_ACTIVE_FIRES_URL = "https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/BCWS_ActiveFires_PublicView/FeatureServer/0/query"
BCWS_PERIMETERS_URL = "https://services6.arcgis.com/ubm4tcTYICKBpist/ArcGIS/rest/services/BCWS_FirePerimeters_PublicView/FeatureServer/0/query"
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
    limit: int = Field(default=5000, gt=1, le=50000)


def env(name):
    value = os.environ.get(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"missing {name}")
    return value


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
    for name, body in (
        (index_name(), event_body),
        (cache_index_name(), cache_body),
        (bcws_incident_index_name(), bcws_incident_body),
        (bcws_perimeter_index_name(), bcws_perimeter_body),
        (bcws_cache_index_name(), bcws_cache_body),
    ):
        try:
            es("PUT", f"/{name}", body)
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
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
    url = "/".join(
        [
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv",
            urllib.parse.quote(env("NASA_FIRMS_MAP_KEY")),
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


def query_events(req, start, days, area_bounds, remaining, source=None):
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
        "size": remaining,
        "sort": [{"acquired_at": "asc"}],
        "query": {
            "bool": {
                "filter": filters
            }
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
    hits = es("POST", f"/{index_name()}/_search", body)["hits"]["hits"]
    return [hit["_source"] for hit in hits]


def ndjson(payload):
    return json.dumps(payload, separators=(",", ":")) + "\n"


def replay_lines(req):
    create_indices()
    area_bounds = bbox(req.latitude, req.longitude, req.radius_km)
    area = ",".join(f"{value:.6f}" for value in area_bounds)
    weather_cache = {}
    place_cache = {}
    base_at = None
    emitted = 0
    yield ndjson({"type": "started", "area": area})
    bcws_context = {"incidents": [], "perimeters": [], "cached": False}
    try:
        bcws_context = collect_bcws_context(area, area_bounds)
        yield ndjson(
            {
                "type": "context",
                "cached": bcws_context["cached"],
                "incidents": [public_incident(doc) for doc in bcws_context["incidents"]],
                "perimeters": [public_perimeter(doc) for doc in bcws_context["perimeters"]],
            }
        )
    except Exception as exc:
        yield ndjson({"type": "error", "error": f"BCWS context failed: {exc}"})
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
            indexed, cached = collect_chunk(source, area, start, days, weather_cache, place_cache)
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
            remaining = req.limit - emitted
            if remaining <= 0:
                break
            events = query_events(req, start, days, area_bounds, remaining, source=source)
            if events and base_at is None:
                base_at = datetime.fromisoformat(events[0]["acquired_at"])
            if base_at:
                for event in events:
                    event_at = datetime.fromisoformat(event["acquired_at"])
                    event["replay_second"] = (event_at - base_at).total_seconds() / req.speed
                    attach_bcws(event, bcws_context)
            emitted += len(events)
            yield ndjson(
                {
                    "type": "events",
                    "source": source,
                    "start_date": start.isoformat(),
                    "days": days,
                    "cached": cached,
                    "indexed": indexed,
                    "events": events,
                }
            )
        if emitted >= req.limit:
            break
    yield ndjson({"type": "done", "events": emitted})


@app.on_event("startup")
def startup():
    load_env()


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
