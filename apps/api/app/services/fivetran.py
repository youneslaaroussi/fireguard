from __future__ import annotations

import json
from typing import Any

from app.config import Settings
from app.services import demo_data
from app.services.store import FireGuardStore
from app.services.time import now_iso

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


def sync_fivetran_to_elastic(store: FireGuardStore) -> dict[str, Any]:
    settings = store.settings
    mode = "bigquery"
    fallbacks: dict[str, Any] = {}
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
            fallbacks["fire_hotspots"] = {
                "reason": reason,
                "replacement": "Stored NASA FIRMS historical snapshot keeps the demo threat deterministic while live FIRMS is quiet.",
                "count": len(streams["fire_hotspots"]),
            }
            mode = "bigquery_with_replay_fallback"

    counts: dict[str, int] = {}
    for stream, docs in streams.items():
        id_field = STREAMS[stream]
        store.bulk_upsert(stream, docs, id_field)
        counts[stream] = len(docs)

    run_id = f"FIVETRAN_SYNC_{now_iso()}"
    run = {
        "run_id": run_id,
        "provider": "fivetran",
        "status": "synced",
        "mode": mode,
        "streams": counts,
        "fallbacks": fallbacks,
        "source_error": source_error,
        "destination": settings.fivetran_destination_name,
        "dataset": settings.fivetran_bigquery_dataset,
        "created_at": now_iso(),
    }
    store.upsert("ingestion_runs", run_id, run)
    return run


def fivetran_status(store: FireGuardStore) -> dict[str, Any]:
    latest_run = sorted(store.list("ingestion_runs"), key=lambda run: run.get("created_at", ""))[-1:] or [None]
    return {
        "provider": "fivetran",
        "configured": bool(store.settings.fivetran_api_key and store.settings.fivetran_api_secret),
        "connection_name": store.settings.fivetran_connection_name,
        "connection_id": store.settings.fivetran_connection_id,
        "destination": store.settings.fivetran_destination_name,
        "bigquery_project": store.settings.fivetran_bigquery_project,
        "bigquery_dataset": store.settings.fivetran_bigquery_dataset,
        "streams": STREAMS,
        "latest_run": latest_run[0],
        "local_connector_path": "integrations/fivetran/fireguard_connector",
    }
