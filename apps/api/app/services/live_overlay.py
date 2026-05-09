from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.config import Settings
from app.services.fivetran import _filter_fire_hotspots_to_bc, _query_bigquery
from app.services.ingest import ingest_bc_perimeters, ingest_firms, ingest_road_events, ingest_weather
from app.services.store import FireGuardStore
from app.services.time import now_iso


LIVE_STREAMS: dict[str, dict[str, Any]] = {
    "fire_hotspots": {
        "index": "live_fire_hotspots",
        "id_field": "external_id",
    },
    "fire_perimeters": {
        "index": "live_fire_perimeters",
        "id_field": "fire_number",
    },
    "road_events": {
        "index": "live_road_events",
        "id_field": "external_id",
    },
    "weather_observations": {
        "index": "live_weather_observations",
        "id_field": "weather_id",
    },
}


def _is_replay_or_snapshot(doc: dict[str, Any]) -> bool:
    raw = doc.get("raw") if isinstance(doc.get("raw"), dict) else {}
    source = str(doc.get("source", "")).upper()
    return bool(
        doc.get("ingestion_mode") in {"replay", "bigquery_empty_replay_fallback"}
        or raw.get("historical_replay")
        or raw.get("source_snapshot")
        or raw.get("replay")
        or "REPLAY" in source
        or "SNAPSHOT" in source
    )


def _live_doc(doc: dict[str, Any], stream: str, source_url: str | None, provider_path: str) -> dict[str, Any]:
    lineage_label = (
        "Current live/open source overlay loaded from Fivetran BigQuery output; displayed separately from replay decision evidence."
        if provider_path == "fivetran_bigquery"
        else "Current live/open source overlay loaded by direct source adapters; displayed separately from replay decision evidence."
    )
    return {
        **doc,
        "context_role": "live_overlay",
        "decision_eligible": False,
        "source_temporal_scope": "current_live",
        "source_lineage_label": lineage_label,
        "live_overlay_stream": stream,
        "live_overlay_provider": provider_path,
        "source_url": doc.get("source_url") or source_url,
    }


def _replace_live_indices(store: FireGuardStore, docs_by_stream: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for stream, config in LIVE_STREAMS.items():
        docs = docs_by_stream.get(stream, [])
        store.replace_index(config["index"], docs, config["id_field"])
        counts[stream] = len(docs)
    return counts


def _persist_live_overlay_run(
    store: FireGuardStore,
    *,
    docs_by_stream: dict[str, list[dict[str, Any]]],
    stream_summaries: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
    data_quality_warnings: list[dict[str, Any]],
    provider_path: str,
    fallback_active: bool,
    fivetran_error: str | None,
) -> dict[str, Any]:
    counts = _replace_live_indices(store, docs_by_stream)
    run_id = f"LIVE_OVERLAY_SYNC_{now_iso()}"
    run = {
        "run_id": run_id,
        "provider": "live_overlay",
        "source_provider": "fivetran" if provider_path == "fivetran_bigquery" else "direct_source_adapters",
        "provider_path": provider_path,
        "status": "synced",
        "mode": "live_overlay",
        "decision_eligible": False,
        "streams": counts,
        "stream_summaries": stream_summaries,
        "warnings": warnings,
        "data_quality_warnings": data_quality_warnings,
        "fallback_active": fallback_active,
        "fivetran_error": fivetran_error,
        "created_at": now_iso(),
        "decision_rule": "Live overlay records are displayed alongside the replay incident but are not used as temporal evidence for the replay evacuation plan.",
    }
    store.upsert("ingestion_runs", run_id, run)
    return run


def _run_fivetran_bigquery(
    settings: Settings,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    streams = _query_bigquery(settings)
    data_quality_warnings = _filter_fire_hotspots_to_bc(streams)
    docs_by_stream: dict[str, list[dict[str, Any]]] = {}
    stream_summaries: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []

    for stream in LIVE_STREAMS:
        docs = streams.get(stream, [])
        live_docs = [
            _live_doc(doc, stream, doc.get("source_url"), "fivetran_bigquery")
            for doc in docs
            if not _is_replay_or_snapshot(doc)
        ]
        docs_by_stream[stream] = live_docs
        stream_summaries[stream] = {
            "source_mode": "fivetran_bigquery",
            "source_provider": "fivetran",
            "raw_count": len(docs),
            "live_count": len(live_docs),
        }
        if not live_docs:
            warnings.append({
                "stream": stream,
                "status": "fivetran_live_overlay_empty",
                "count": len(docs),
                "source_mode": "fivetran_bigquery",
                "reason": "Fivetran BigQuery returned no current live records for this stream after replay/snapshot records were excluded.",
            })
        elif len(live_docs) < len(docs):
            warnings.append({
                "stream": stream,
                "status": "fivetran_snapshot_records_excluded",
                "count": len(docs) - len(live_docs),
                "source_mode": "fivetran_bigquery",
                "reason": "Replay/snapshot records from Fivetran output were excluded from the live overlay.",
            })

    return docs_by_stream, stream_summaries, warnings, data_quality_warnings


async def _run_source(
    stream: str,
    fetch: Callable[[], Awaitable[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    try:
        result = await fetch()
    except Exception as exc:
        return [], {
            "source_mode": "error",
            "source_url": None,
            "raw_count": 0,
            "live_count": 0,
            "error": str(exc),
        }, [{
            "stream": stream,
            "status": "live_overlay_source_error",
            "count": 0,
            "source_mode": "error",
            "reason": str(exc),
        }]
    docs = result.get("docs", [])
    live_docs = [
        _live_doc(doc, stream, result.get("source_url"), "direct_source_adapters")
        for doc in docs
        if result.get("mode") == "live" and not _is_replay_or_snapshot(doc)
    ]
    warnings: list[dict[str, Any]] = []
    if not live_docs:
        warnings.append({
            "stream": stream,
            "status": "live_overlay_empty",
            "count": len(docs),
            "source_mode": result.get("mode"),
            "reason": result.get("reason")
            or "The source returned no current live records after replay/snapshot records were excluded.",
        })
    elif len(live_docs) < len(docs):
        warnings.append({
            "stream": stream,
            "status": "snapshot_records_excluded",
            "count": len(docs) - len(live_docs),
            "source_mode": result.get("mode"),
            "reason": "Replay/snapshot records were excluded from the live overlay.",
        })
    summary = {
        "source_mode": result.get("mode"),
        "source_url": result.get("source_url"),
        "raw_count": len(docs),
        "live_count": len(live_docs),
    }
    return live_docs, summary, warnings


async def sync_live_overlay(store: FireGuardStore, settings: Settings) -> dict[str, Any]:
    try:
        docs_by_stream, stream_summaries, warnings, data_quality_warnings = _run_fivetran_bigquery(settings)
        if sum(len(docs) for docs in docs_by_stream.values()) > 0:
            return _persist_live_overlay_run(
                store,
                docs_by_stream=docs_by_stream,
                stream_summaries=stream_summaries,
                warnings=warnings,
                data_quality_warnings=data_quality_warnings,
                provider_path="fivetran_bigquery",
                fallback_active=False,
                fivetran_error=None,
            )
        fivetran_error = "Fivetran BigQuery returned zero current live overlay records across all streams."
    except Exception as exc:
        fivetran_error = str(exc)

    fetchers: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
        "fire_hotspots": lambda: ingest_firms(settings),
        "fire_perimeters": ingest_bc_perimeters,
        "road_events": ingest_road_events,
        "weather_observations": ingest_weather,
    }
    stream_summaries: dict[str, dict[str, Any]] = {}
    docs_by_stream: dict[str, list[dict[str, Any]]] = {}
    warnings: list[dict[str, Any]] = [{
        "stream": "all",
        "status": "fivetran_live_overlay_fallback",
        "count": 0,
        "source_mode": "fivetran_bigquery",
        "reason": f"Fivetran BigQuery live overlay was unavailable, so direct source adapters were used: {fivetran_error[:500]}",
    }]

    for stream in LIVE_STREAMS:
        docs, summary, stream_warnings = await _run_source(stream, fetchers[stream])
        docs_by_stream[stream] = docs
        stream_summaries[stream] = summary
        warnings.extend(stream_warnings)

    return _persist_live_overlay_run(
        store,
        docs_by_stream=docs_by_stream,
        stream_summaries=stream_summaries,
        warnings=warnings,
        data_quality_warnings=[],
        provider_path="direct_source_adapters",
        fallback_active=True,
        fivetran_error=fivetran_error,
    )
