from __future__ import annotations

from collections import defaultdict
import json
from typing import Any

from app.config import Settings
from app.services import demo_data
from app.services.actions import github_issue_tasks_enabled
from app.services.geo import haversine_km
from app.services.time import freshness_minutes, iso_string, now_iso


INDEX_NAMES = [
    "fire_hotspots",
    "fire_perimeters",
    "road_events",
    "evacuation_zones",
    "shelters",
    "dispatch_assets",
    "resident_contacts",
    "policies",
    "weather_observations",
    "public_evacuation_orders",
    "public_ess_facilities",
    "action_logs",
    "approval_requests",
    "traces",
    "evals",
    "ingestion_runs",
    "plans",
]


INDEX_MAPPINGS: dict[str, dict[str, Any]] = {
    "fire_hotspots": {
        "properties": {
            "source": {"type": "keyword"},
            "external_id": {"type": "keyword"},
            "location": {"type": "geo_point"},
            "brightness": {"type": "float"},
            "confidence": {"type": "keyword"},
            "frp": {"type": "float"},
            "acquired_at": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    },
    "fire_perimeters": {
        "properties": {
            "source": {"type": "keyword"},
            "fire_name": {"type": "text"},
            "fire_number": {"type": "keyword"},
            "status": {"type": "keyword"},
            "geometry": {"type": "geo_shape"},
            "area_hectares": {"type": "float"},
        }
    },
    "road_events": {
        "properties": {
            "source": {"type": "keyword"},
            "external_id": {"type": "keyword"},
            "title": {"type": "text"},
            "event_type": {"type": "keyword"},
            "severity": {"type": "keyword"},
            "road_name": {"type": "keyword"},
            "location": {"type": "geo_point"},
            "geometry": {"type": "geo_shape"},
        }
    },
    "evacuation_zones": {"properties": {"zone_id": {"type": "keyword"}, "geometry": {"type": "geo_shape"}, "centroid": {"type": "geo_point"}}},
    "shelters": {"properties": {"shelter_id": {"type": "keyword"}, "location": {"type": "geo_point"}, "capacity_available": {"type": "integer"}}},
    "action_logs": {"properties": {"action_id": {"type": "keyword"}, "status": {"type": "keyword"}, "created_at": {"type": "date"}}},
    "traces": {"properties": {"trace_id": {"type": "keyword"}, "incident_id": {"type": "keyword"}, "created_at": {"type": "date"}, "phoenix_trace_ids": {"type": "keyword"}}},
    "evals": {"properties": {"eval_id": {"type": "keyword"}, "incident_id": {"type": "keyword"}, "score": {"type": "float"}, "created_at": {"type": "date"}}},
    "ingestion_runs": {"properties": {"run_id": {"type": "keyword"}, "provider": {"type": "keyword"}, "status": {"type": "keyword"}, "created_at": {"type": "date"}}},
    "public_evacuation_orders": {
        "properties": {
            "order_alert_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "status": {"type": "keyword"},
            "event_name": {"type": "text"},
            "issuing_agency": {"type": "keyword"},
            "location": {"type": "geo_point"},
            "updated_at": {"type": "date"},
            "captured_at": {"type": "date"},
        }
    },
    "public_ess_facilities": {
        "properties": {
            "facility_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "name": {"type": "text"},
            "facility_type_code": {"type": "keyword"},
            "community": {"type": "keyword"},
            "municipality": {"type": "keyword"},
            "status": {"type": "keyword"},
            "location": {"type": "geo_point"},
            "updated_at": {"type": "date"},
            "captured_at": {"type": "date"},
        }
    },
}


class FireGuardStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.indices: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.elastic_enabled = bool(settings.elasticsearch_url and settings.elasticsearch_api_key)
        self.elastic_error: str | None = None
        self.es: Any | None = None
        self._indices_ensured = False
        if settings.elasticsearch_api_key and (settings.elasticsearch_url or settings.elasticsearch_cloud_id):
            try:
                from elasticsearch import Elasticsearch

                if settings.elasticsearch_cloud_id:
                    self.es = Elasticsearch(
                        cloud_id=settings.elasticsearch_cloud_id,
                        api_key=settings.elasticsearch_api_key,
                        request_timeout=5,
                        retry_on_timeout=False,
                        max_retries=0,
                    )
                else:
                    self.es = Elasticsearch(
                        settings.elasticsearch_url,
                        api_key=settings.elasticsearch_api_key,
                        request_timeout=5,
                        retry_on_timeout=False,
                        max_retries=0,
                    )
                self.elastic_enabled = True
            except Exception as exc:  # pragma: no cover - depends on external credentials
                self.elastic_error = str(exc)
                self.es = None
                self.elastic_enabled = False

    def backend_name(self) -> str:
        if self.es and not self.elastic_error:
            return "elastic-mirrored"
        return "memory-elastic-compatible"

    def ensure_indices(self) -> dict[str, Any]:
        for index_name in INDEX_NAMES:
            self.indices.setdefault(index_name, {})
        if self._indices_ensured:
            return {"indices": INDEX_NAMES, "mappings": INDEX_MAPPINGS, "backend": self.backend_name()}
        if self.es:
            for index_name in INDEX_NAMES:
                try:
                    if not self.es.indices.exists(index=index_name):
                        self.es.indices.create(
                            index=index_name,
                            mappings=INDEX_MAPPINGS.get(index_name, {"properties": {}}),
                        )
                except Exception as exc:  # pragma: no cover - external Elastic only
                    self.elastic_error = str(exc)
                    break
        self._indices_ensured = True
        return {"indices": INDEX_NAMES, "mappings": INDEX_MAPPINGS, "backend": self.backend_name()}

    def upsert(self, index: str, doc_id: str, document: dict[str, Any]) -> dict[str, Any]:
        self.ensure_indices()
        record = {**document}
        record.setdefault("_id", doc_id)
        self.indices[index][doc_id] = record
        if self.es and not self.elastic_error:
            try:
                elastic_record = self._elastic_document(index, record)
                self.es.index(index=index, id=doc_id, document=elastic_record)
            except Exception as exc:  # pragma: no cover - external Elastic only
                self.elastic_error = str(exc)
        return record

    def _elastic_document(self, index: str, record: dict[str, Any]) -> dict[str, Any]:
        elastic_record = {key: value for key, value in record.items() if key != "_id"}
        if index == "traces":
            events = elastic_record.pop("events", [])
            elastic_record["event_count"] = len(events) if isinstance(events, list) else 0
            elastic_record["events_json"] = json.dumps(events, default=str)[:20000]
        return elastic_record

    def bulk_upsert(self, index: str, docs: list[dict[str, Any]], id_field: str) -> list[dict[str, Any]]:
        return [self.upsert(index, str(doc[id_field]), doc) for doc in docs if doc.get(id_field)]

    def list(self, index: str) -> list[dict[str, Any]]:
        self.ensure_indices()
        return list(self.indices[index].values())

    def get(self, index: str, doc_id: str) -> dict[str, Any] | None:
        self.ensure_indices()
        return self.indices[index].get(doc_id)

    def search_text(self, indices: list[str], query: str) -> list[dict[str, Any]]:
        if self.es and not self.elastic_error:
            try:
                response = self.es.search(
                    index=",".join(indices),
                    size=10,
                    query={
                        "multi_match": {
                            "query": query,
                            "fields": ["title^2", "description", "body", "name", "fire_name", "priority_notes"],
                            "lenient": True,
                        }
                    },
                    highlight={"fields": {"*": {}}},
                )
                return list(response["hits"]["hits"])
            except Exception as exc:  # pragma: no cover - external Elastic only
                self.elastic_error = str(exc)

        terms = {term.lower() for term in query.replace(",", " ").split() if len(term) > 2}
        hits: list[dict[str, Any]] = []
        for index in indices:
            for doc_id, doc in self.indices[index].items():
                blob = " ".join(str(value) for value in doc.values()).lower()
                score = sum(1 for term in terms if term in blob)
                if score:
                    hits.append({"_index": index, "_id": doc_id, "_score": score, "_source": doc})
        return sorted(hits, key=lambda hit: hit["_score"], reverse=True)

    def nearby(self, index: str, point: dict[str, float], distance_km: float) -> list[dict[str, Any]]:
        if self.es and not self.elastic_error:
            location_field = "location" if index not in {"evacuation_zones"} else "centroid"
            try:
                response = self.es.search(
                    index=index,
                    size=50,
                    query={
                        "geo_distance": {
                            "distance": f"{distance_km}km",
                            location_field: {"lat": point["lat"], "lon": point["lon"]},
                        }
                    },
                    sort=[
                        {
                            "_geo_distance": {
                                location_field: {"lat": point["lat"], "lon": point["lon"]},
                                "order": "asc",
                                "unit": "km",
                            }
                        }
                    ],
                )
                return list(response["hits"]["hits"])
            except Exception as exc:  # pragma: no cover - external Elastic only
                self.elastic_error = str(exc)

        hits = []
        for doc_id, doc in self.indices[index].items():
            location = doc.get("location") or doc.get("centroid")
            if not location:
                continue
            distance = haversine_km(point, location)
            if distance <= distance_km:
                hits.append({"_index": index, "_id": doc_id, "distance_km": round(distance, 2), "_source": doc})
        return sorted(hits, key=lambda hit: hit["distance_km"])

    def seed_demo(self) -> dict[str, Any]:
        self.ensure_indices()
        self.indices.clear()
        self.ensure_indices()
        self.bulk_upsert("evacuation_zones", demo_data.evacuation_zones(), "zone_id")
        self.bulk_upsert("shelters", demo_data.synthetic_shelters(), "shelter_id")
        self.bulk_upsert("fire_hotspots", demo_data.replay_fire_hotspots(), "external_id")
        self.bulk_upsert("fire_perimeters", demo_data.replay_fire_perimeters(), "fire_number")
        self.bulk_upsert("road_events", demo_data.replay_road_events(), "external_id")
        self.bulk_upsert("weather_observations", demo_data.replay_weather(), "weather_id")
        self.bulk_upsert("public_evacuation_orders", demo_data.public_evacuation_orders_alerts(), "order_alert_id")
        self.bulk_upsert("public_ess_facilities", demo_data.public_ess_facilities(), "facility_id")
        self.bulk_upsert("dispatch_assets", demo_data.dispatch_assets(), "asset_id")
        self.bulk_upsert("resident_contacts", demo_data.resident_contacts(self.settings.demo_resident_zone_a_phone), "resident_id")
        self.bulk_upsert("policies", demo_data.policies(), "policy_id")
        run_id = f"FIVETRAN_REPLAY_{now_iso()}"
        self.upsert(
            "ingestion_runs",
            run_id,
            {
                "run_id": run_id,
                "provider": "fivetran",
                "status": "replay_seeded",
                "mode": "replay",
                "streams": {
                    "fire_hotspots": len(self.indices["fire_hotspots"]),
                    "fire_perimeters": len(self.indices["fire_perimeters"]),
                    "road_events": len(self.indices["road_events"]),
                    "weather_observations": len(self.indices["weather_observations"]),
                    "public_evacuation_orders": len(self.indices["public_evacuation_orders"]),
                    "public_ess_facilities": len(self.indices["public_ess_facilities"]),
                },
                "fallback_active": True,
                "warnings": [
                    {
                        "stream": "all",
                        "status": "fallback_active",
                        "count": sum(
                            len(self.indices[index])
                            for index in ["fire_hotspots", "fire_perimeters", "road_events", "weather_observations"]
                        ),
                        "reason": "Demo seed loaded replay/snapshot records before a Fivetran warehouse sync.",
                    }
                ],
                "created_at": now_iso(),
            },
        )
        trace_id = f"TRACE_SEED_{now_iso()}"
        self.upsert("traces", trace_id, {"trace_id": trace_id, "incident_id": demo_data.INCIDENT_ID, "events": [], "created_at": now_iso()})
        return {"status": "seeded", "incident_id": demo_data.INCIDENT_ID, "backend": self.backend_name()}

    def incident_context(self, incident_id: str = demo_data.INCIDENT_ID) -> dict[str, Any]:
        self.ensure_seeded()
        weather = self.list("weather_observations")
        disclosures = demo_data.demo_disclosures()
        if github_issue_tasks_enabled(self.settings):
            disclosures = [
                {
                    **item,
                    "label": "Real GitHub issue task backend",
                    "detail": "Shelter notification, road-ops task, and dispatch task actions create real GitHub issues in the configured demo repository after human approval. They are still not official emergency-system integrations.",
                    "synthetic": False,
                }
                if item.get("scope") == "shelter_road_ops_dispatch_actions"
                else item
                for item in disclosures
            ]
        context = {
            "incident_id": incident_id,
            "mode": "replay" if self.settings.demo_mode else "live",
            "store_backend": self.backend_name(),
            "fires": self.list("fire_hotspots"),
            "perimeters": self.list("fire_perimeters"),
            "road_events": self.list("road_events"),
            "weather": weather[0] if weather else {},
            "zones": self.list("evacuation_zones"),
            "shelters": self.list("shelters"),
            "dispatch_assets": self.list("dispatch_assets"),
            "public_evacuation_orders": self.list("public_evacuation_orders"),
            "public_ess_facilities": self.list("public_ess_facilities"),
            "policies": self.list("policies"),
            "data_freshness": self.data_freshness(),
            "provider_status": self.provider_status(),
            "demo_disclosures": disclosures,
        }
        return context

    def provider_status(self) -> dict[str, Any]:
        ingestion_runs = sorted(self.list("ingestion_runs"), key=lambda run: run.get("created_at", ""))
        latest_ingestion = ingestion_runs[-1] if ingestion_runs else None
        phoenix_span_ids = [
            span_id
            for trace in self.list("traces")
            for span_id in trace.get("phoenix_trace_ids", [])
        ]
        return {
            "fivetran": {
                "configured": bool(self.settings.fivetran_api_key and self.settings.fivetran_api_secret),
                "destination": self.settings.fivetran_destination_name,
                "dataset": self.settings.fivetran_bigquery_dataset,
                "latest_run": latest_ingestion,
                "fallback_active": bool(latest_ingestion and latest_ingestion.get("fallback_active")),
                "warnings": latest_ingestion.get("warnings", []) if latest_ingestion else [],
            },
            "elastic": {
                "configured": bool(self.settings.elasticsearch_api_key and (self.settings.elasticsearch_url or self.settings.elasticsearch_cloud_id)),
                "backend": self.backend_name(),
                "error": self.elastic_error,
            },
            "gemini": {
                "configured": bool(self.settings.google_cloud_project),
                "model": self.settings.gemini_model,
                "location": self.settings.google_cloud_location,
                "vertexai": self.settings.google_genai_use_vertexai,
                "assessment_enabled": self.settings.gemini_assessment_enabled,
            },
            "phoenix": {
                "enabled": self.settings.phoenix_tracing_enabled,
                "endpoint": self.settings.phoenix_collector_endpoint,
                "project": self.settings.phoenix_project_name,
                "exported_span_count": len(phoenix_span_ids),
            },
            "action_tasks": {
                "backend": self.settings.action_task_backend,
                "github_repo": self.settings.github_repo,
                "configured": github_issue_tasks_enabled(self.settings),
                "official_emergency_system": False,
            },
        }

    def data_freshness(self) -> list[dict[str, Any]]:
        freshness = []
        for index in [
            "fire_hotspots",
            "fire_perimeters",
            "road_events",
            "weather_observations",
            "shelters",
            "public_evacuation_orders",
            "public_ess_facilities",
        ]:
            docs = self.list(index)
            if not docs:
                freshness.append({"source": index, "freshness_minutes": None, "stale": True, "status": "missing"})
                continue
            timestamp_field = "captured_at" if index.startswith("public_") else "updated_at"
            newest = max(
                iso_string(doc.get(timestamp_field) or doc.get("updated_at") or doc.get("ingested_at") or now_iso())
                for doc in docs
            )
            minutes = freshness_minutes(newest)
            stale_after = 180 if index == "road_events" else 1440 if index.startswith("public_") else 360
            status = "stale" if minutes > stale_after else "fresh"
            if index.startswith("public_"):
                status = "snapshot_stale" if minutes > stale_after else "source_snapshot"
            freshness.append({
                "source": index,
                "freshness_minutes": round(minutes, 1),
                "stale": minutes > stale_after,
                "status": status,
            })
        return freshness

    def ensure_seeded(self) -> None:
        self.ensure_indices()
        if not self.indices["evacuation_zones"]:
            self.seed_demo()


_store: FireGuardStore | None = None


def get_store(settings: Settings) -> FireGuardStore:
    global _store
    if _store is None:
        _store = FireGuardStore(settings)
        _store.seed_demo()
    return _store
