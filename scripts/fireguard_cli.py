#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import sys
import time
import urllib.parse
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agentic.config import AppConfig
from app.agentic.engine import WorkflowEngine
from app.agentic.models import CreateSessionRequest, RunStatus, StartRunRequest
from app.geo import haversine_km
from app.main import (
    BC_EVACUATION_ZONES_PATH,
    BC_PUBLIC_CONTEXT_PATH,
    BC_ROAD_EVENTS_PATH,
    FIRMS_SNAPSHOT_METADATA_PATH,
    FIRMS_SNAPSHOT_PATH,
    bbox,
    bulk,
    cache_index_name,
    cache_put,
    create_indices,
    distance_km,
    es,
    http,
    index_name,
    load_env,
    load_json_file,
    parse_time,
    ranges,
    snapshot_firms_source,
    transform,
    zone_doc_from_feature,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FireGuard terminal evacuation flow.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--threshold-frp", type=float, default=10.0)
    parser.add_argument("--radius-km", type=float, default=150.0)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--latitude", type=float, default=52.5)
    parser.add_argument("--longitude", type=float, default=-120.0)
    parser.add_argument("--collection-radius-km", type=float, default=400.0)
    parser.add_argument("--sources", default="VIIRS_NOAA20_SP,VIIRS_SNPP_SP,MODIS_SP")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--collect-firms", action="store_true")
    parser.add_argument("--skip-agent", action="store_true")
    parser.add_argument("--seed-elastic", action="store_true")
    parser.add_argument("--what-if-hwy97-blocked", action="store_true")
    parser.add_argument("--state-dir", default="data/intelligence-state-cli")
    args = parser.parse_args()

    load_env_file(ROOT / args.env)
    load_env()
    setdefault_env()

    if args.seed_elastic:
        create_indices()
    if args.collect_firms:
        create_indices()
        collection = collect_indexed_firms(args)
        print(json.dumps({"collection": collection}, indent=2))

    events = load_firms_events(args)
    zones = load_zones()
    shelters = load_shelters()
    road_events = load_road_events()
    threat = find_threat(events, zones, args.threshold_frp, args.radius_km)
    if threat is None:
        print(
            json.dumps(
                {
                    "status": "no_trigger",
                    "threshold_frp": args.threshold_frp,
                    "radius_km": args.radius_km,
                    "event_count": len(events),
                },
                indent=2,
            )
        )
        return 2
    if args.what_if_hwy97_blocked:
        threat["hypothetical_closures"] = [
            {"lat": 51.27, "lon": -121.33, "label": "Highway 97 South closure"}
        ]

    start_date, end_date = replay_window(args)
    prompt = build_prompt(threat, start_date, end_date)
    print(render_snapshot_brief(threat, shelters, road_events, args.threshold_frp))
    if args.skip_agent:
        return 0

    result = asyncio.run(run_agent(prompt, threat, start_date, end_date, args.state_dir))
    print("\n=== Agentic Workflow ===")
    print(json.dumps({k: result[k] for k in ["session_id", "run_id", "status", "tool_events"]}, indent=2))
    print("\n=== Evacuation Brief ===")
    print(result["brief"])
    return 0 if result["status"] == RunStatus.completed.value else 1


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key, value)


def setdefault_env() -> None:
    os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")
    os.environ.setdefault("ELASTICSEARCH_API_KEY", "fireguard-dev")
    os.environ.setdefault("ELASTICSEARCH_INDEX_PREFIX", "fireguard")
    os.environ.setdefault("FIREGUARD_INTELLIGENCE_PROVIDER", "vertex")
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", gcloud_value("project"))
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
    os.environ.setdefault("GEMINI_MODEL", "gemini-2.5-flash")


def gcloud_value(name: str) -> str:
    import subprocess

    try:
        completed = subprocess.run(
            ["gcloud", "config", "get-value", name],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except OSError:
        return ""
    value = completed.stdout.strip()
    return "" if value == "(unset)" else value


def source_list(args: argparse.Namespace) -> list[str]:
    return [item.strip() for item in args.sources.split(",") if item.strip()]


def replay_window(args: argparse.Namespace) -> tuple[str, str]:
    if args.start_date and args.end_date:
        return args.start_date, args.end_date
    return snapshot_window()


def load_firms_events(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.start_date and args.end_date:
        return load_indexed_firms_events(args)
    source = snapshot_firms_source()
    events: list[dict[str, Any]] = []
    with FIRMS_SNAPSHOT_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("latitude") and row.get("longitude"):
                _, doc = transform(row, source)
                events.append(doc)
    return sorted(events, key=lambda item: item.get("acquired_at", ""))


def collect_indexed_firms(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.start_date or not args.end_date:
        raise SystemExit("--collect-firms requires --start-date and --end-date")
    map_key = os.environ.get("NASA_FIRMS_MAP_KEY")
    if not map_key:
        raise SystemExit("NASA_FIRMS_MAP_KEY must be set to collect FIRMS data")
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    area_bounds = bbox(args.latitude, args.longitude, args.collection_radius_km)
    area = ",".join(f"{value:.6f}" for value in area_bounds)
    summary: list[dict[str, Any]] = []
    for chunk_start, days in ranges(start, end):
        for source in source_list(args):
            es(
                "POST",
                f"/{cache_index_name()}/_delete_by_query?refresh=true",
                {
                    "query": {
                        "bool": {
                            "filter": [
                                {"term": {"area": area}},
                                {"term": {"start_date": chunk_start.isoformat()}},
                                {"term": {"days": days}},
                                {"term": {"source": source}},
                            ]
                        }
                    }
                },
            )
            url = "/".join(
                [
                    "https://firms.modaps.eosdis.nasa.gov/api/area/csv",
                    urllib.parse.quote(map_key),
                    source,
                    area,
                    str(days),
                    chunk_start.isoformat(),
                ]
            )
            rows = csv.DictReader(io.StringIO(http("GET", url)))
            batch = [
                transform(row, source)
                for row in rows
                if row.get("latitude") and row.get("longitude")
            ]
            indexed = 0
            for offset in range(0, len(batch), 1000):
                indexed += bulk(batch[offset : offset + 1000])
            cache_put(source, area, chunk_start, days, indexed)
            summary.append(
                {
                    "source": source,
                    "start_date": chunk_start.isoformat(),
                    "days": days,
                    "indexed": indexed,
                }
            )
    return summary


def load_indexed_firms_events(args: argparse.Namespace) -> list[dict[str, Any]]:
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date) + timedelta(days=1)
    west, south, east, north = bbox(args.latitude, args.longitude, args.collection_radius_km)
    body = {
        "size": int(args.limit),
        "sort": [{"frp": "desc"}],
        "query": {
            "bool": {
                "filter": [
                    {"range": {"acquired_at": {"gte": start.isoformat(), "lt": end.isoformat()}}},
                    {"terms": {"source": source_list(args)}},
                    {
                        "geo_bounding_box": {
                            "location": {
                                "top_left": {"lat": north, "lon": west},
                                "bottom_right": {"lat": south, "lon": east},
                            }
                        }
                    },
                ]
            }
        },
        "_source": [
            "source",
            "latitude",
            "longitude",
            "acquired_at",
            "satellite",
            "instrument",
            "confidence",
            "frp",
            "brightness",
            "weather",
            "place",
        ],
    }
    hits = es("POST", f"/{index_name()}/_search", body)["hits"]["hits"]
    return [hit["_source"] for hit in hits]


def load_zones() -> list[dict[str, Any]]:
    snapshot = load_json_file(BC_EVACUATION_ZONES_PATH, {})
    features = snapshot.get("features") if isinstance(snapshot, dict) else []
    zones = []
    for feature in features:
        if isinstance(feature, dict):
            doc = zone_doc_from_feature(feature)
            if doc is not None:
                zones.append(doc)
    return zones


def load_shelters() -> list[dict[str, Any]]:
    public_context = load_json_file(BC_PUBLIC_CONTEXT_PATH, {})
    ess_source = public_context.get("ess_facilities") if isinstance(public_context, dict) else {}
    records = ess_source.get("records") if isinstance(ess_source, dict) else []
    return [record for record in records if isinstance(record, dict)]


def load_road_events() -> list[dict[str, Any]]:
    snapshot = load_json_file(BC_ROAD_EVENTS_PATH, [])
    return [record for record in snapshot if isinstance(record, dict)]


def find_threat(
    events: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    threshold_frp: float,
    radius_km: float,
) -> dict[str, Any] | None:
    best: tuple[float, float, dict[str, Any], dict[str, Any]] | None = None
    for event in events:
        frp = event.get("frp")
        lat = event.get("latitude")
        lon = event.get("longitude")
        if not isinstance(frp, int | float) or not isinstance(lat, int | float) or not isinstance(lon, int | float):
            continue
        if float(frp) < threshold_frp:
            continue
        nearest: tuple[float, dict[str, Any]] | None = None
        for zone in zones:
            location = zone.get("location") if isinstance(zone.get("location"), dict) else {}
            zlat = location.get("lat")
            zlon = location.get("lon")
            if not isinstance(zlat, int | float) or not isinstance(zlon, int | float):
                continue
            dist = distance_km(float(lat), float(lon), float(zlat), float(zlon))
            if dist > radius_km:
                continue
            if nearest is None or dist < nearest[0]:
                nearest = (dist, zone)
        if nearest is None:
            continue
        dist, zone = nearest
        rank = float(frp)
        if best is None or rank > best[0] or (rank == best[0] and dist < best[1]):
            best = (rank, dist, event, zone)
    if best is None:
        return None
    _, dist, event, zone = best
    location = zone["location"]
    return {
        "hotspot": {
            "lat": event["latitude"],
            "lon": event["longitude"],
            "frp": event["frp"],
            "confidence": event.get("confidence"),
            "source": event.get("source"),
            "acquired_at": event.get("acquired_at"),
        },
        "zone": {
            "name": zone.get("name"),
            "population": zone.get("population"),
            "homes": zone.get("homes"),
            "latitude": location.get("lat"),
            "longitude": location.get("lon"),
            "distance_km": round(dist, 2),
        },
    }


def snapshot_window() -> tuple[str, str]:
    metadata = load_json_file(FIRMS_SNAPSHOT_METADATA_PATH, {})
    start = metadata.get("query_start_date") if isinstance(metadata, dict) else None
    days = metadata.get("query_day_range") if isinstance(metadata, dict) else None
    if isinstance(start, str) and isinstance(days, int):
        start_date = date.fromisoformat(start)
        return start_date.isoformat(), (start_date + timedelta(days=days - 1)).isoformat()
    return "2024-07-10", "2024-07-14"


def build_prompt(threat: dict[str, Any], start_date: str, end_date: str) -> str:
    return "\n".join(
        [
            "Run the FireGuard evacuation workflow for this replay threat.",
            f"Hotspot: lat {threat['hotspot']['lat']}, lon {threat['hotspot']['lon']}, FRP {threat['hotspot']['frp']}, acquired {threat['hotspot'].get('acquired_at')}, source {threat['hotspot'].get('source')}.",
            f"Affected zone: {threat['zone']['name']}, population {threat['zone'].get('population')}, homes {threat['zone'].get('homes')}, centroid lat {threat['zone'].get('latitude')}, centroid lon {threat['zone'].get('longitude')}, hotspot distance {threat['zone'].get('distance_km')} km.",
            f"Replay window: {start_date} through {end_date}.",
            "Scan affected zones, shelters, road events, and fire detections; evaluate routes to open shelters; then produce the evacuation brief and recommended action.",
        ]
    )


def render_snapshot_brief(
    threat: dict[str, Any],
    shelters: list[dict[str, Any]],
    road_events: list[dict[str, Any]],
    threshold_frp: float,
) -> str:
    open_shelters = [item for item in shelters if item.get("status") == "OPEN"]
    closed_shelters = [item for item in shelters if item.get("status") == "CLOSED"]
    target = open_shelters[0] if open_shelters else {}
    target_location = target.get("location") if isinstance(target.get("location"), dict) else {}
    route_distance = None
    if target_location:
        route_distance = haversine_km(
            {"lat": threat["zone"]["latitude"], "lon": threat["zone"]["longitude"]},
            {"lat": target_location["lat"], "lon": target_location["lon"]},
        )
    lines = [
        "=== FireGuard CLI Replay ===",
        f"Trigger threshold: FRP >= {threshold_frp}",
        f"Hotspot: {threat['hotspot']['lat']:.5f}, {threat['hotspot']['lon']:.5f} FRP {threat['hotspot']['frp']}",
        f"Zone: {threat['zone']['name']} ({threat['zone'].get('population')} people, {threat['zone'].get('homes')} homes)",
        f"Shelters: {len(open_shelters)} open, {len(closed_shelters)} closed",
        f"Road events: {len(road_events)}",
    ]
    if target:
        distance_text = f"{route_distance:.1f} km" if route_distance is not None else "distance unavailable"
        lines.append(f"Primary shelter: {target.get('name')} ({target.get('community')}), {distance_text} straight-line")
    return "\n".join(lines)


async def run_agent(
    prompt: str,
    threat: dict[str, Any],
    start_date: str,
    end_date: str,
    state_dir: str,
) -> dict[str, Any]:
    config = AppConfig(
        provider=os.environ.get("FIREGUARD_INTELLIGENCE_PROVIDER", "vertex"),
        state_dir=Path(state_dir),
        fireguard_elasticsearch_url=os.environ.get("ELASTICSEARCH_URL", "http://127.0.0.1:9200"),
        fireguard_elasticsearch_api_key=os.environ.get("ELASTICSEARCH_API_KEY", ""),
        fireguard_elasticsearch_index_prefix=os.environ.get("ELASTICSEARCH_INDEX_PREFIX", "fireguard"),
        google_cloud_project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        google_cloud_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
    )
    engine = WorkflowEngine.from_config(config)
    await engine.start()
    try:
        session = engine.create_session(
            CreateSessionRequest(title="FireGuard CLI evacuation", metadata={"source": "cli"})
        )
        run = engine.start_run(
            session.session_id,
            StartRunRequest(
                prompt=prompt,
                workflow_id="fireguard_evacuation",
                payload={
                    "source": "cli",
                    "threat": {**threat, "start_date": start_date, "end_date": end_date},
                    "session_context": {
                        "replay": {"start_date": start_date, "end_date": end_date},
                        "threat_alert": threat,
                    },
                },
            ),
        )
        deadline = time.time() + 180
        while time.time() < deadline:
            current = engine.store.load_run(session.session_id, run.run_id)
            if current.status in {RunStatus.completed, RunStatus.failed, RunStatus.stopped, RunStatus.rejected}:
                events = engine.store.read_events(session.session_id, run.run_id)
                return {
                    "session_id": session.session_id,
                    "run_id": run.run_id,
                    "status": current.status.value,
                    "tool_events": len([event for event in events if event.event_type == "tool.completed"]),
                    "brief": final_brief(current),
                }
            await asyncio.sleep(0.25)
        current = engine.store.load_run(session.session_id, run.run_id)
        return {
            "session_id": session.session_id,
            "run_id": run.run_id,
            "status": current.status.value,
            "tool_events": 0,
            "brief": "Timed out waiting for workflow completion.",
        }
    finally:
        await engine.close()


def final_brief(run: Any) -> str:
    for node_id in ("terminal", "style_agent", "writer_agent", "research_agent"):
        state = run.node_states.get(node_id)
        if state is None or state.output_payload is None:
            continue
        output = state.output_payload
        if isinstance(output, dict):
            message = output.get("message")
            if isinstance(message, str) and message.strip():
                return message
            handoff = output.get("handoff")
            if isinstance(handoff, dict):
                task = handoff.get("task")
                if isinstance(task, dict):
                    report = task.get("report_markdown") or task.get("research_notes")
                    if isinstance(report, str) and report.strip():
                        return report
    return json.dumps(run.model_dump(mode="json"), indent=2, default=str)


if __name__ == "__main__":
    raise SystemExit(main())
