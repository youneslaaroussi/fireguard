#!/usr/bin/env python3
import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone


def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)


def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"missing {name}")
    return value


def request(method, url, api_key=None, body=None, content_type=None, timeout=120):
    headers = {}
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"
    if content_type:
        headers["Content-Type"] = content_type
    data = body.encode("utf-8") if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def es_request(method, path, body=None):
    base = require_env("ELASTICSEARCH_URL").rstrip("/")
    api_key = require_env("ELASTICSEARCH_API_KEY")
    return request(method, f"{base}{path}", api_key, body, "application/json" if body else None)


def create_index(index):
    mapping = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
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
            }
        },
    }
    try:
        es_request("PUT", f"/{index}", json.dumps(mapping))
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise


def parse_time(row):
    acq_date = row["acq_date"]
    acq_time = row.get("acq_time", "").zfill(4)
    return datetime.strptime(f"{acq_date} {acq_time}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)


def as_float(row, key):
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


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


def bulk_index(index, docs, chunk_size):
    sent = 0
    chunk = []
    for doc_id, doc in docs:
        chunk.append(json.dumps({"index": {"_index": index, "_id": doc_id}}, separators=(",", ":")))
        chunk.append(json.dumps(doc, separators=(",", ":")))
        if len(chunk) >= chunk_size * 2:
            sent += flush_bulk(chunk)
            chunk = []
    if chunk:
        sent += flush_bulk(chunk)
    return sent


def flush_bulk(lines):
    body = "\n".join(lines) + "\n"
    response = json.loads(es_request("POST", "/_bulk", body))
    if response.get("errors"):
        failures = [item for item in response["items"] if item["index"].get("error")]
        raise SystemExit(json.dumps(failures[:3], indent=2))
    return len(response["items"])


def fetch_csv(map_key, source, area, days, start):
    parts = [
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv",
        urllib.parse.quote(map_key),
        source,
        area,
        str(days),
    ]
    if start:
        parts.append(start.isoformat())
    url = "/".join(parts)
    return request("GET", url, timeout=300)


def date_chunks(start, end, max_days):
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=max_days - 1))
        yield current, (chunk_end - current).days + 1
        current = chunk_end + timedelta(days=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env")
    parser.add_argument("--index")
    parser.add_argument("--area", default="world")
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--chunk-size", type=int, default=5000)
    args = parser.parse_args()

    load_env(args.env)
    prefix = require_env("ELASTICSEARCH_INDEX_PREFIX")
    index = args.index or f"{prefix}-firms"
    map_key = require_env("NASA_FIRMS_MAP_KEY")
    create_index(index)

    ranges = []
    if args.start or args.end:
        if not args.start or not args.end:
            raise SystemExit("--start and --end must be used together")
        ranges = list(date_chunks(date.fromisoformat(args.start), date.fromisoformat(args.end), 5))
    else:
        ranges = [(None, args.days)]

    total = 0
    for source in args.source:
        for start, days in ranges:
            label = start.isoformat() if start else "latest"
            print(json.dumps({"source": source, "range_start": label, "days": days, "status": "fetching"}), flush=True)
            csv_text = fetch_csv(map_key, source, args.area, days, start)
            reader = csv.DictReader(io.StringIO(csv_text))
            docs = (transform(row, source) for row in reader if row.get("latitude") and row.get("longitude"))
            count = bulk_index(index, docs, args.chunk_size)
            total += count
            print(json.dumps({"source": source, "range_start": label, "days": days, "indexed": count}), flush=True)
            time.sleep(0.5)

    print(json.dumps({"index": index, "indexed_total": total}), flush=True)


if __name__ == "__main__":
    main()
