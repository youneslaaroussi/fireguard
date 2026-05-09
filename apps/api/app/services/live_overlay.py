from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.config import Settings
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


def _live_doc(doc: dict[str, Any], stream: str, source_url: str | None) -> dict[str, Any]:
    return {
        **doc,
        "context_role": "live_overlay",
        "decision_eligible": False,
        "source_temporal_scope": "current_live",
        "source_lineage_label": "Current live/open source overlay; displayed separately from replay decision evidence.",
        "live_overlay_stream": stream,
        "source_url": doc.get("source_url") or source_url,
    }


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
        _live_doc(doc, stream, result.get("source_url"))
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
    fetchers: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
        "fire_hotspots": lambda: ingest_firms(settings),
        "fire_perimeters": ingest_bc_perimeters,
        "road_events": ingest_road_events,
        "weather_observations": ingest_weather,
    }
    stream_summaries: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    warnings: list[dict[str, Any]] = []

    for stream, config in LIVE_STREAMS.items():
        docs, summary, stream_warnings = await _run_source(stream, fetchers[stream])
        store.replace_index(config["index"], docs, config["id_field"])
        stream_summaries[stream] = summary
        counts[stream] = len(docs)
        warnings.extend(stream_warnings)

    run_id = f"LIVE_OVERLAY_SYNC_{now_iso()}"
    run = {
        "run_id": run_id,
        "provider": "live_overlay",
        "status": "synced",
        "mode": "live_overlay",
        "decision_eligible": False,
        "streams": counts,
        "stream_summaries": stream_summaries,
        "warnings": warnings,
        "fallback_active": False,
        "created_at": now_iso(),
        "decision_rule": "Live overlay records are displayed alongside the replay incident but are not used as temporal evidence for the replay evacuation plan.",
    }
    store.upsert("ingestion_runs", run_id, run)
    return run
