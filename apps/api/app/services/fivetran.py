from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.services import demo_data
from app.services.bc_boundary import classify_bc_location
from app.services.store import FireGuardStore
from app.services.time import now_iso

FIVETRAN_API_BASE_URL = "https://api.fivetran.com/v1"
STREAMS = {
    "fire_hotspots": "external_id",
    "fire_perimeters": "fire_number",
    "road_events": "external_id",
    "weather_observations": "weather_id",
}


def _with_lineage(doc: dict[str, Any], stream: str, mode: str) -> dict[str, Any]:
    return {
        **doc,
        "ingestion_provider": "fivetran",
        "ingestion_mode": mode,
        "fivetran_stream": stream,
    }


def _replay_stream_docs() -> dict[str, list[dict[str, Any]]]:
    return {
        "fire_hotspots": [_with_lineage(doc, "fire_hotspots", "replay") for doc in demo_data.replay_fire_hotspots()],
        "fire_perimeters": [_with_lineage(doc, "fire_perimeters", "replay") for doc in demo_data.replay_fire_perimeters()],
        "road_events": [_with_lineage(doc, "road_events", "replay") for doc in demo_data.replay_road_events()],
        "weather_observations": [_with_lineage(doc, "weather_observations", "replay") for doc in demo_data.replay_weather()],
    }


def _replay_fallback_docs(stream: str, reason: str) -> list[dict[str, Any]]:
    replay_streams = _replay_stream_docs()
    docs = []
    for doc in replay_streams[stream]:
        docs.append({
            **doc,
            "ingestion_mode": "bigquery_empty_replay_fallback",
            "fallback_reason": reason,
            "source_record_kind": "real_source_replay_snapshot",
        })
    return docs


def _fallback_reason_from_doc(doc: dict[str, Any]) -> str | None:
    raw = doc.get("raw") if isinstance(doc.get("raw"), dict) else {}
    source = str(doc.get("source", "")).upper()
    if doc.get("fallback_reason"):
        return str(doc["fallback_reason"])
    if raw.get("fallback_reason"):
        return str(raw["fallback_reason"])
    if raw.get("source_error"):
        return f"Source fetch failed: {raw['source_error']}"
    if doc.get("ingestion_mode") in {"replay", "bigquery_empty_replay_fallback"}:
        return "Replay records are being used instead of current Fivetran warehouse rows."
    if raw.get("historical_replay") or raw.get("source_snapshot") or raw.get("replay"):
        return "Stored source snapshot or replay record is being used."
    if "REPLAY" in source or "SNAPSHOT" in source:
        return "Source label indicates replay or stored snapshot data."
    return None


def _fallbacks_from_streams(streams: dict[str, list[dict[str, Any]]], source_error: str | None = None) -> dict[str, Any]:
    fallbacks: dict[str, Any] = {}
    for stream, docs in streams.items():
        reasons = sorted({reason for doc in docs if (reason := _fallback_reason_from_doc(doc))})
        if source_error and docs and all(doc.get("ingestion_mode") == "replay" for doc in docs):
            reasons.insert(0, f"BigQuery sync unavailable: {source_error[:500]}")
        if reasons:
            fallbacks[stream] = {
                "stream": stream,
                "status": "fallback_active",
                "count": len(docs),
                "reason": reasons[0],
                "all_reasons": reasons[:5],
            }
    return fallbacks


def _fivetran_get(settings: Settings, endpoint: str) -> dict[str, Any]:
    if not settings.fivetran_api_key or not settings.fivetran_api_secret:
        raise RuntimeError("Fivetran API credentials are not configured.")
    url = f"{FIVETRAN_API_BASE_URL}/{endpoint.lstrip('/')}"
    with httpx.Client(timeout=8, auth=(settings.fivetran_api_key, settings.fivetran_api_secret)) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def _managed_connection_summary(connection: dict[str, Any]) -> dict[str, Any]:
    status = connection.get("status") if isinstance(connection.get("status"), dict) else {}
    return {
        "id": connection.get("id"),
        "service": connection.get("service"),
        "schema": connection.get("schema"),
        "group_id": connection.get("group_id"),
        "paused": connection.get("paused"),
        "setup_state": status.get("setup_state"),
        "schema_status": status.get("schema_status"),
        "sync_state": status.get("sync_state"),
        "update_state": status.get("update_state"),
        "is_historical_sync": status.get("is_historical_sync"),
        "task_count": len(status.get("tasks") or []),
        "warning_count": len(status.get("warnings") or []),
        "created_at": connection.get("created_at"),
        "succeeded_at": connection.get("succeeded_at"),
        "failed_at": connection.get("failed_at"),
        "sync_frequency": connection.get("sync_frequency"),
    }


def _managed_destination_summary(destination: dict[str, Any]) -> dict[str, Any]:
    config = destination.get("config") if isinstance(destination.get("config"), dict) else {}
    return {
        "id": destination.get("id"),
        "group_id": destination.get("group_id"),
        "service": destination.get("service"),
        "region": destination.get("region"),
        "setup_status": destination.get("setup_status"),
        "project_id": config.get("project_id"),
        "location": config.get("location"),
        "data_set_location": config.get("data_set_location"),
    }


def managed_fivetran_status(settings: Settings) -> dict[str, Any]:
    if not settings.fivetran_api_key or not settings.fivetran_api_secret:
        return {"configured": False, "status": "skipped", "reason": "Fivetran API credentials are not configured."}

    try:
        if settings.fivetran_connection_id:
            connection_payload = _fivetran_get(settings, f"connections/{settings.fivetran_connection_id}")
            connection = connection_payload.get("data") or {}
        else:
            list_payload = _fivetran_get(settings, "connections")
            items = list_payload.get("data", {}).get("items", [])
            connection = next((item for item in items if item.get("schema") == settings.fivetran_bigquery_dataset), items[0] if items else {})
    except Exception as exc:
        return {
            "configured": True,
            "status": "failed",
            "reason": f"Fivetran API status check failed: {str(exc)[:300]}",
        }

    connection_summary = _managed_connection_summary(connection)
    destination_summary = None
    group_summary = None
    group_id = connection_summary.get("group_id")
    if group_id:
        try:
            destination_payload = _fivetran_get(settings, f"destinations/{group_id}")
            destination_summary = _managed_destination_summary(destination_payload.get("data") or {})
        except Exception as exc:
            destination_summary = {"status": "failed", "reason": f"Destination status check failed: {str(exc)[:300]}"}
        try:
            group_payload = _fivetran_get(settings, f"groups/{group_id}")
            group = group_payload.get("data") or {}
            group_summary = {"id": group.get("id"), "name": group.get("name"), "created_at": group.get("created_at")}
        except Exception as exc:
            group_summary = {"status": "failed", "reason": f"Group status check failed: {str(exc)[:300]}"}

    connected = connection_summary.get("setup_state") == "connected" and connection_summary.get("sync_state") in {"scheduled", "syncing", "rescheduled"}
    return {
        "configured": True,
        "status": "ok" if connected else "needs_attention",
        "connection": connection_summary,
        "destination": destination_summary,
        "group": group_summary,
    }


def _row_to_doc(stream: str, row: dict[str, Any]) -> dict[str, Any]:
    raw_json = row.get("raw_json")
    raw = json.loads(raw_json) if isinstance(raw_json, str) and raw_json else row.get("raw", {})
    geometry_json = row.get("geometry_json")
    geometry = json.loads(geometry_json) if isinstance(geometry_json, str) and geometry_json else row.get("geometry")

    if stream == "fire_hotspots":
        return _with_lineage(
            {
                "source": row.get("source", "FIVETRAN_FIRE"),
                "external_id": row["external_id"],
                "location": {"lat": float(row["latitude"]), "lon": float(row["longitude"])},
                "brightness": row.get("brightness"),
                "confidence": row.get("confidence"),
                "frp": row.get("frp"),
                "scan": row.get("scan"),
                "track": row.get("track"),
                "acquired_at": row.get("acquired_at"),
                "updated_at": row.get("updated_at") or row.get("ingested_at") or now_iso(),
                "ingested_at": row.get("ingested_at") or now_iso(),
                "raw": raw,
            },
            stream,
            "bigquery",
        )
    if stream == "fire_perimeters":
        return _with_lineage(
            {
                "source": row.get("source", "FIVETRAN_BC_WILDFIRE"),
                "fire_name": row.get("fire_name"),
                "fire_number": row["fire_number"],
                "status": row.get("status"),
                "geometry": geometry,
                "area_hectares": row.get("area_hectares"),
                "updated_at": row.get("updated_at") or row.get("ingested_at") or now_iso(),
                "ingested_at": row.get("ingested_at") or now_iso(),
                "raw": raw,
            },
            stream,
            "bigquery",
        )
    if stream == "road_events":
        return _with_lineage(
            {
                "source": row.get("source", "FIVETRAN_ROADS"),
                "external_id": row["external_id"],
                "title": row.get("title"),
                "description": row.get("description"),
                "event_type": row.get("event_type"),
                "severity": row.get("severity"),
                "road_name": row.get("road_name"),
                "location": {"lat": float(row["latitude"]), "lon": float(row["longitude"])},
                "geometry": geometry,
                "starts_at": row.get("starts_at"),
                "ends_at": row.get("ends_at"),
                "updated_at": row.get("updated_at") or row.get("ingested_at") or now_iso(),
                "ingested_at": row.get("ingested_at") or now_iso(),
                "raw": raw,
            },
            stream,
            "bigquery",
        )
    if stream == "weather_observations":
        return _with_lineage(
            {
                "weather_id": row["weather_id"],
                "source": row.get("source", "FIVETRAN_WEATHER"),
                "location": {"lat": float(row["latitude"]), "lon": float(row["longitude"])},
                "wind_speed_kph": row.get("wind_speed_kph"),
                "wind_direction_degrees": row.get("wind_direction_degrees"),
                "wind_gusts_kph": row.get("wind_gusts_kph"),
                "forecast_horizon_hours": row.get("forecast_horizon_hours"),
                "updated_at": row.get("updated_at") or row.get("ingested_at") or now_iso(),
                "ingested_at": row.get("ingested_at") or now_iso(),
                "raw": raw,
            },
            stream,
            "bigquery",
        )
    raise ValueError(f"Unsupported Fivetran stream {stream}")


def _query_bigquery(settings: Settings) -> dict[str, list[dict[str, Any]]]:
    if not settings.fivetran_bigquery_project:
        raise RuntimeError("FIVETRAN_BIGQUERY_PROJECT is not configured.")
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install the API with the bigquery extra to read Fivetran BigQuery output.") from exc

    credentials = None
    if settings.google_application_credentials:
        credentials = service_account.Credentials.from_service_account_file(settings.google_application_credentials)
    client = bigquery.Client(project=settings.fivetran_bigquery_project, credentials=credentials)
    streams: dict[str, list[dict[str, Any]]] = {}
    for stream in STREAMS:
        table = f"`{settings.fivetran_bigquery_project}.{settings.fivetran_bigquery_dataset}.{stream}`"
        rows = client.query(f"SELECT * FROM {table} ORDER BY ingested_at DESC LIMIT 500").result()
        streams[stream] = [_row_to_doc(stream, dict(row)) for row in rows]
    return streams


def _filter_fire_hotspots_to_bc(streams: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    docs = streams.get("fire_hotspots", [])
    if not docs:
        return []

    kept = []
    removed = []
    methods = set()
    warnings = set()
    for doc in docs:
        classification = classify_bc_location(doc["location"])
        methods.add(classification["method"])
        if classification.get("warning"):
            warnings.add(classification["warning"])
        doc["raw"] = {
            **(doc.get("raw") if isinstance(doc.get("raw"), dict) else {}),
            "bc_region_filter": classification["method"],
            "bc_region_filter_source_url": classification["source_url"],
        }
        if classification["inside"]:
            kept.append(doc)
        else:
            removed.append(doc)
    streams["fire_hotspots"] = kept
    if not removed and not warnings:
        return []
    return [{
        "stream": "fire_hotspots",
        "status": "region_filtered",
        "count_removed": len(removed),
        "count_kept": len(kept),
        "method": sorted(methods),
        "warnings": sorted(warnings),
        "reason": "FIRMS Area API is rectangular; rows outside the BC provincial boundary are excluded before Elastic indexing.",
    }]


def sync_fivetran_to_elastic(store: FireGuardStore) -> dict[str, Any]:
    settings = store.settings
    mode = "bigquery"
    try:
        streams = _query_bigquery(settings)
    except Exception as exc:
        mode = "replay"
        streams = _replay_stream_docs()
        source_error = str(exc)
    else:
        source_error = None
        if not streams.get("fire_hotspots"):
            reason = "Fivetran BigQuery FIRMS stream returned zero current hotspot rows for the configured BC bbox."
            streams["fire_hotspots"] = _replay_fallback_docs("fire_hotspots", reason)
            mode = "bigquery_with_replay_fallback"
    data_quality_warnings = _filter_fire_hotspots_to_bc(streams)

    fallbacks = _fallbacks_from_streams(streams, source_error)
    warnings = list(fallbacks.values())

    counts: dict[str, int] = {}
    for stream, docs in streams.items():
        id_field = STREAMS[stream]
        store.replace_index(stream, docs, id_field)
        counts[stream] = len(docs)

    run_id = f"FIVETRAN_SYNC_{now_iso()}"
    run = {
        "run_id": run_id,
        "provider": "fivetran",
        "status": "synced",
        "mode": mode,
        "streams": counts,
        "fallbacks": fallbacks,
        "fallback_active": bool(warnings),
        "warnings": warnings,
        "data_quality_warnings": data_quality_warnings,
        "source_error": source_error,
        "destination": settings.fivetran_destination_name,
        "dataset": settings.fivetran_bigquery_dataset,
        "created_at": now_iso(),
    }
    store.upsert("ingestion_runs", run_id, run)
    return run


def fivetran_status(store: FireGuardStore) -> dict[str, Any]:
    fivetran_runs = [
        run for run in store.list("ingestion_runs") if run.get("provider") == "fivetran"
    ]
    latest_run = sorted(fivetran_runs, key=lambda run: run.get("created_at", ""))[-1:] or [None]
    run = latest_run[0]
    warnings = run.get("warnings", []) if isinstance(run, dict) else []
    managed_status = managed_fivetran_status(store.settings)
    return {
        "provider": "fivetran",
        "configured": bool(store.settings.fivetran_api_key and store.settings.fivetran_api_secret),
        "managed_api": managed_status,
        "connection_name": store.settings.fivetran_connection_name,
        "connection_id": store.settings.fivetran_connection_id,
        "destination": store.settings.fivetran_destination_name,
        "bigquery_project": store.settings.fivetran_bigquery_project,
        "bigquery_dataset": store.settings.fivetran_bigquery_dataset,
        "streams": STREAMS,
        "latest_run": run,
        "fallback_active": bool(run and run.get("fallback_active")),
        "warnings": warnings,
        "local_connector_path": "integrations/fivetran/fireguard_connector",
    }
