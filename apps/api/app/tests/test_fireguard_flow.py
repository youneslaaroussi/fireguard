from app.config import Settings
from app.services.actions import approve_actions, execute_action
from app.services.agent import run_assessment
from app.services.evals import evaluate_incident
from app.services.fivetran import fivetran_status, sync_fivetran_to_elastic
from app.services.risk import compute_all_zone_risks
from app.services.routes import best_safe_route, compute_routes
from app.services.store import FireGuardStore


def seeded_store() -> FireGuardStore:
    settings = Settings(
        demo_mode=True,
        twilio_allowlist="+15555550123,+15555550124",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
    )
    store = FireGuardStore(settings)
    store.seed_demo()
    return store


def test_route_closure_rejects_obvious_route() -> None:
    store = seeded_store()
    routes = compute_routes(store.incident_context())
    obvious = [route for route in routes if route.origin_id == "ZONE_A" and route.destination_id == "SHELTER_A"][0]
    alternate = best_safe_route(routes, "ZONE_A")

    assert obvious.safe is False
    assert "closure" in " ".join(obvious.risk_flags).lower()
    assert "drivebc.ca/DBC-90684" in obvious.evidence_ids
    assert any(evidence_id.startswith("FIRMS_N20_20240710") for evidence_id in obvious.evidence_ids)
    assert alternate is not None
    assert alternate.destination_id == "SHELTER_B"


def test_firms_replay_uses_real_historical_snapshot() -> None:
    store = seeded_store()
    fires = store.list("fire_hotspots")

    assert len(fires) == 45
    assert fires[0]["source"] == "NASA_FIRMS_HISTORICAL_SNAPSHOT"
    assert fires[0]["raw"]["snapshot_file"] == "data/replay/bc_demo/firms_snapshot.csv"
    assert "/[MAP_KEY]/" in fires[0]["source_url"]


def test_shelter_capacity_overflow_is_reflected_in_plan() -> None:
    store = seeded_store()
    assessment = run_assessment(store)

    rejected = " ".join(item["reason"] for item in assessment.plan.rejected_alternatives)
    assert "Shelter A has insufficient capacity" in rejected
    assert assessment.plan.steps[0].destination_id == "SHELTER_B"


def test_unsafe_zone_uses_shelter_in_place_dispatch() -> None:
    store = seeded_store()
    assessment = run_assessment(store)
    zone_c_step = [step for step in assessment.plan.steps if step.zone_id == "ZONE_C"][0]

    assert zone_c_step.strategy == "shelter_in_place_dispatch_assisted"
    assert "Dispatch-assisted evacuation" in zone_c_step.message


def test_stale_data_reduces_confidence() -> None:
    store = seeded_store()
    for event in store.list("road_events"):
        event["updated_at"] = "2024-01-01T00:00:00Z"
        store.upsert("road_events", event["external_id"], event)

    context = store.incident_context()
    risks = compute_all_zone_risks(context)

    assert any(item["source"] == "road_events" and item["stale"] for item in context["data_freshness"])
    assert min(risk.confidence for risk in risks) < 0.8


def test_sms_allowlist_blocks_unapproved_numbers() -> None:
    store = seeded_store()
    assessment = run_assessment(store)
    actions = [action.model_dump() for action in assessment.actions]
    approval = assessment.approval.model_dump()
    approved_actions, _ = approve_actions(actions, approval)
    zone_c_sms = [action for action in approved_actions if action["action_type"] == "resident_sms" and action["target"] == "ZONE_C"][0]

    executed = execute_action(zone_c_sms, store.settings, store.list("resident_contacts"))

    assert executed["status"] == "failed"
    assert executed["payload"]["blocked_recipients"] == ["+15555550125"]


def test_full_assessment_creates_auditable_action_bundle() -> None:
    store = seeded_store()
    assessment = run_assessment(store)

    assert assessment.bundle_id.startswith("BUNDLE_")
    assert assessment.approval.status == "pending"
    assert len(assessment.actions) >= 6
    assert any(event["tool"] == "search_operational_memory" for event in assessment.trace)
    assert any("closure" in alt["reason"].lower() for alt in assessment.plan.rejected_alternatives)


def test_fivetran_sync_indexes_provider_lineage() -> None:
    store = seeded_store()
    result = sync_fivetran_to_elastic(store)

    assert result["provider"] == "fivetran"
    assert result["mode"] == "replay"
    assert result["fallback_active"] is True
    assert result["warnings"][0]["status"] == "fallback_active"
    assert result["streams"]["fire_hotspots"] >= 2
    assert all(doc["ingestion_provider"] == "fivetran" for doc in store.list("fire_hotspots"))


def test_fivetran_status_exposes_latest_run() -> None:
    store = seeded_store()
    sync_fivetran_to_elastic(store)
    status = fivetran_status(store)

    assert status["provider"] == "fivetran"
    assert status["latest_run"]["status"] == "synced"
    assert status["fallback_active"] is True
    assert status["warnings"]
    assert "fire_hotspots" in status["streams"]


def test_eval_records_safety_and_grounding() -> None:
    store = seeded_store()
    assessment = run_assessment(store)
    result = evaluate_incident(store, assessment.incident_id)

    assert result["score"] >= 0.84
    assert result["checks"]["route_safety"] is True
    assert result["checks"]["approval_enforcement"] is True
