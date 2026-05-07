from __future__ import annotations

import csv
import hashlib
from io import StringIO
import math
from typing import Any

import httpx

from app.services.geo import haversine_km
from app.services.store import FireGuardStore
from app.services.time import now_iso


STATCAN_PROFILE_URL_TEMPLATE = (
    "https://api.statcan.gc.ca/census-recensement/profile/sdmx/rest/data/"
    "STC_CP,{dataflow}/A5.{ref_area}.1.1%2B24%2B29.1"
)
BC_DRA_WFS_URL = "https://openmaps.gov.bc.ca/geo/pub/ows"
BC_DRA_TYPENAME = "pub:WHSE_BASEMAPPING.DRA_DGTL_ROAD_ATLAS_MPAR_SP"
SOURCE_TYPE = "official_statscan_dra_zone_context"


ZONE_SOURCE_PROFILES = {
    "ZONE_A": {
        "dataflow": "DF_CD",
        "ref_area": "2021A00035941",
        "label": "Statistics Canada 2021 Census Profile: Cariboo census division",
    },
    "ZONE_B": {
        "dataflow": "DF_CSD",
        "ref_area": "2021A00055941009",
        "label": "Statistics Canada 2021 Census Profile: Williams Lake census subdivision",
    },
    "ZONE_C": {
        "dataflow": "DF_CD",
        "ref_area": "2021A00035941",
        "label": "Statistics Canada 2021 Census Profile: Cariboo census division",
    },
}


def source_backed_zone_context_status(store: FireGuardStore) -> dict[str, Any]:
    updates = [update for update in store.zone_updates() if update.get("source_type") == SOURCE_TYPE]
    latest = sorted(updates, key=lambda item: item.get("ingested_at") or item.get("updated_at") or "")[-1] if updates else None
    return {
        "provider": "statscan_bc_dra",
        "configured": True,
        "source_type": SOURCE_TYPE,
        "latest_update_count": len(updates),
        "latest_update_at": latest.get("ingested_at") if latest else None,
    }


def sync_source_backed_zone_context(store: FireGuardStore) -> dict[str, Any]:
    ingested_at = now_iso()
    context = store.incident_context()
    road_events = context.get("road_events", [])
    updates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for zone in context.get("zones", []):
        zone_id = zone.get("zone_id")
        try:
            profile_config = ZONE_SOURCE_PROFILES[zone_id]
            demographics = fetch_statscan_demographics(profile_config)
            road_access = fetch_bc_dra_road_access(zone, road_events)
            update = build_zone_context_update(
                zone,
                demographics,
                road_access,
                profile_config,
                ingested_at=ingested_at,
            )
            store.upsert("zone_updates", update["update_id"], update)
            updates.append(update)
        except Exception as exc:  # pragma: no cover - provider/network dependent
            errors.append({"zone_id": zone_id, "reason": str(exc)[:300]})

    return {
        "provider": "statscan_bc_dra",
        "status": "synced" if not errors else "partial" if updates else "failed",
        "source_type": SOURCE_TYPE,
        "updated_count": len(updates),
        "skipped_count": len(errors),
        "updated_zone_ids": [update["zone_id"] for update in updates],
        "errors": errors,
        "ingested_at": ingested_at,
    }


def fetch_statscan_demographics(profile_config: dict[str, str]) -> dict[str, Any]:
    url = STATCAN_PROFILE_URL_TEMPLATE.format(
        dataflow=profile_config["dataflow"],
        ref_area=profile_config["ref_area"],
    )
    response = httpx.get(url, params={"format": "csvfile"}, timeout=20)
    response.raise_for_status()
    rows = list(csv.DictReader(StringIO(response.text)))
    values: dict[str, int] = {}
    for row in rows:
        characteristic = str(row.get("CHARACTERISTIC") or "")
        try:
            values[characteristic] = int(float(row.get("OBS_VALUE") or 0))
        except ValueError:
            values[characteristic] = 0
    population = values.get("1", 0)
    age_65_plus = values.get("24", 0)
    age_85_plus = values.get("29", 0)
    if population <= 0:
        raise ValueError(f"StatsCan profile returned no population for {profile_config['ref_area']}.")
    return {
        "population": population,
        "age_65_plus": age_65_plus,
        "age_85_plus": age_85_plus,
        "age_65_plus_ratio": age_65_plus / population,
        "age_85_plus_ratio": age_85_plus / population,
        "source_url": url,
    }


def fetch_bc_dra_road_access(zone: dict[str, Any], road_events: list[dict[str, Any]]) -> dict[str, Any]:
    centroid = zone["centroid"]
    bbox = _bbox_around_point(centroid, radius_km=8)
    response = httpx.get(
        BC_DRA_WFS_URL,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": BC_DRA_TYPENAME,
            "srsName": "EPSG:4326",
            "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:4326",
            "count": "500",
            "outputFormat": "json",
        },
        timeout=30,
    )
    response.raise_for_status()
    features = response.json().get("features", [])
    return summarize_road_access(features, centroid, road_events)


def build_zone_context_update(
    zone: dict[str, Any],
    demographics: dict[str, Any],
    road_access: dict[str, Any],
    profile_config: dict[str, str],
    *,
    ingested_at: str,
) -> dict[str, Any]:
    senior_ratio = float(demographics["age_65_plus_ratio"])
    vulnerable_count = max(1, round(int(zone.get("population") or 0) * senior_ratio))
    access_score = float(road_access["access_score"])
    basis = (
        f"{zone['zone_id']}:{profile_config['ref_area']}:{vulnerable_count}:"
        f"{access_score}:{road_access['road_segment_count']}:{ingested_at}"
    )
    row_hash = hashlib.sha256(basis.encode()).hexdigest()[:12]
    update_id = f"SOURCE_ZONE_CONTEXT_{zone['zone_id']}_{row_hash}"
    source_label = (
        f"{profile_config['label']} plus BC Digital Road Atlas WFS road-access analysis. "
        "Vulnerable count is a Census 65+ proportional proxy applied to the BC evacuation-zone "
        "population field; it is not an individual vulnerable-person registry."
    )
    return {
        "update_id": update_id,
        "zone_id": zone["zone_id"],
        "vulnerable_count": vulnerable_count,
        "vehicle_access_score": access_score,
        "updated_by": "statscan_bc_dra_sync",
        "updated_at": ingested_at,
        "ingested_at": ingested_at,
        "note": "Source-backed demographic and road-access context replacing demo-derived zone inputs.",
        "source_type": SOURCE_TYPE,
        "source_label": source_label,
        "official_zone_operations_feed": False,
        "vulnerability_method": "zone_population * Statistics Canada Census Profile 65+ ratio",
        "vulnerability_source": {
            "provider": "Statistics Canada",
            "dataflow": profile_config["dataflow"],
            "ref_area": profile_config["ref_area"],
            "label": profile_config["label"],
            "characteristics": {
                "1": "Population, 2021",
                "24": "65 years and over",
                "29": "85 years and over",
            },
            "profile_population": demographics["population"],
            "age_65_plus": demographics["age_65_plus"],
            "age_85_plus": demographics["age_85_plus"],
            "age_65_plus_ratio": round(demographics["age_65_plus_ratio"], 4),
            "source_url": demographics["source_url"],
        },
        "road_access_method": (
            "BC Digital Road Atlas road segments within an 8 km centroid box; score rewards "
            "paved/highway/named-road access and penalizes rough-road dominance and nearby closures."
        ),
        "road_access_source": {
            "provider": "Government of British Columbia",
            "dataset": "Digital Road Atlas Master Partially-Attributed Roads",
            "wfs_url": BC_DRA_WFS_URL,
            "type_name": BC_DRA_TYPENAME,
            **road_access,
        },
    }


def summarize_road_access(
    features: list[dict[str, Any]],
    centroid: dict[str, float],
    road_events: list[dict[str, Any]],
) -> dict[str, Any]:
    props = [feature.get("properties", {}) for feature in features]
    total_km = _sum_km(props)
    paved_km = _sum_km([item for item in props if "paved" in str(item.get("ROAD_SURFACE") or "").lower()])
    rough_km = _sum_km([item for item in props if "rough" in str(item.get("ROAD_SURFACE") or "").lower()])
    highway_km = _sum_km([
        item
        for item in props
        if item.get("HIGHWAY_ROUTE_NUMBER") or str(item.get("ROAD_CLASS") or "").lower() in {"highway", "arterial"}
    ])
    named_roads = sorted({str(item.get("ROAD_NAME_FULL")) for item in props if item.get("ROAD_NAME_FULL")})[:20]
    class_counts: dict[str, int] = {}
    for item in props:
        road_class = str(item.get("ROAD_CLASS") or "unknown").lower()
        class_counts[road_class] = class_counts.get(road_class, 0) + 1

    nearby_closures = [
        event.get("external_id")
        for event in road_events
        if _road_event_is_closure(event) and haversine_km(centroid, event.get("location") or {"lat": 0, "lon": 0}) <= 12
    ]
    score = _road_access_score(
        total_km=total_km,
        paved_km=paved_km,
        rough_km=rough_km,
        highway_km=highway_km,
        named_road_count=len(named_roads),
        has_nearby_closure=bool(nearby_closures),
    )
    return {
        "access_score": score,
        "road_segment_count": len(props),
        "sample_cap": 500,
        "total_road_km_sampled": round(total_km, 2),
        "paved_road_km_sampled": round(paved_km, 2),
        "rough_road_km_sampled": round(rough_km, 2),
        "highway_or_arterial_km_sampled": round(highway_km, 2),
        "named_road_count_sampled": len(named_roads),
        "sample_named_roads": named_roads,
        "road_class_counts": class_counts,
        "nearby_closure_ids": [item for item in nearby_closures if item],
    }


def _bbox_around_point(point: dict[str, float], radius_km: float) -> tuple[float, float, float, float]:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * max(0.2, math.cos(math.radians(point["lat"]))))
    return (
        round(point["lon"] - lon_delta, 6),
        round(point["lat"] - lat_delta, 6),
        round(point["lon"] + lon_delta, 6),
        round(point["lat"] + lat_delta, 6),
    )


def _sum_km(props: list[dict[str, Any]]) -> float:
    total_m = 0.0
    for item in props:
        try:
            total_m += float(item.get("SEGMENT_LENGTH_2D") or item.get("LEN") or 0)
        except (TypeError, ValueError):
            continue
    return total_m / 1000


def _road_access_score(
    *,
    total_km: float,
    paved_km: float,
    rough_km: float,
    highway_km: float,
    named_road_count: int,
    has_nearby_closure: bool,
) -> float:
    rough_ratio = rough_km / total_km if total_km else 1.0
    score = (
        0.2
        + min(total_km / 250, 0.18)
        + min(paved_km / 25, 0.24)
        + min(highway_km / 15, 0.22)
        + min(named_road_count / 25, 0.12)
        - rough_ratio * 0.22
        - (0.12 if has_nearby_closure else 0)
    )
    return round(max(0.05, min(0.95, score)), 2)


def _road_event_is_closure(event: dict[str, Any]) -> bool:
    blob = " ".join(str(event.get(field, "")) for field in ["event_type", "severity", "title", "description"]).lower()
    return "closure" in blob or "road closed" in blob or "closed in both directions" in blob
