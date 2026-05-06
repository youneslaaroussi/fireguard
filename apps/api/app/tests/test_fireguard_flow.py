import json
from pathlib import Path

from app.config import Settings
from app.routers.actions import execute as execute_bundle
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
    assert "Operator-entered capacity assumption" in rejected
    assert any(
        "ASSUMPTION_SHELTER_A_CAPACITY" in item.get("assumption_ids", [])
        for item in assessment.plan.rejected_alternatives
    )
    assert any(
        item["assumption_id"] == "ASSUMPTION_SHELTER_B_CAPACITY"
        for item in assessment.plan.operational_assumptions
    )
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


def test_context_labels_source_backed_zones_and_synthetic_operations() -> None:
    store = seeded_store()
    context = store.incident_context()

    assert any(item["scope"] == "evacuation_zones" and item["synthetic"] is False for item in context["demo_disclosures"])
    assert any(item["scope"] == "shelters_residents_dispatch" and item["synthetic"] for item in context["demo_disclosures"])
    assert all(zone["synthetic"] is False and zone["data_origin"] == "bc_historical_orders_alerts_snapshot" for zone in context["zones"])
    assert all(zone["source_record_id"] for zone in context["zones"])
    assert all(zone["population_source_field"] == "MULTI_SOURCED_POPULATION" for zone in context["zones"])
    assert all(zone["vulnerable_count_estimated"] is True for zone in context["zones"])
    assert all(policy["synthetic"] is False and policy["data_origin"] == "official_bc_public_guidance_snapshot" for policy in context["policies"])
    assert any(item["scope"] == "emergency_guidance_policies" and item["synthetic"] is False for item in context["demo_disclosures"])
    shelters = {shelter["shelter_id"]: shelter for shelter in context["shelters"]}
    assert shelters["SHELTER_A"]["synthetic"] is True
    assert shelters["SHELTER_A"]["data_origin"] == "operator_entered_demo_shelter"
    assert shelters["SHELTER_B"]["synthetic"] is False
    assert shelters["SHELTER_B"]["source_record_id"] == "BC_ESS_86"
    assert shelters["SHELTER_C"]["synthetic"] is False
    assert shelters["SHELTER_C"]["source_record_id"] == "BC_ESS_85"
    assert all(shelter["capacity_is_operator_assumption"] is True for shelter in context["shelters"])
    assert any(
        item["assumption_id"] == "ASSUMPTION_SHELTER_A_CAPACITY"
        and item["status"] == "needs_authoritative_feed"
        for item in context["operational_assumptions"]
    )
    assert any(
        item["assumption_id"] == "ASSUMPTION_RES_B_001_CONTACT"
        and item["blocks_execution"] is True
        for item in context["operational_assumptions"]
    )


def test_action_metadata_labels_simulated_endpoints() -> None:
    store = seeded_store()
    assessment = run_assessment(store)
    by_type = {action.action_type: action for action in assessment.actions}

    assert by_type["resident_sms"].is_simulated_endpoint is False
    assert by_type["resident_sms"].external_system == "twilio_allowlisted_sms"
    for action_type in ["shelter_notify", "road_ops_task", "dispatch_task"]:
        assert by_type[action_type].is_simulated_endpoint is True
        assert by_type[action_type].external_system == "simulated_municipal_webhook"
    shelter_action = by_type["shelter_notify"]
    assert shelter_action.payload["capacity_is_operator_assumption"] is True
    assert "ASSUMPTION_SHELTER_B_CAPACITY" in shelter_action.assumption_ids


def test_resident_contact_provenance_uses_operator_number_when_configured() -> None:
    settings = Settings(
        demo_mode=True,
        demo_resident_zone_a_phone="+15066396110",
        twilio_allowlist="+15066396110",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
    )
    store = FireGuardStore(settings)
    store.seed_demo()
    residents = {resident["resident_id"]: resident for resident in store.list("resident_contacts")}

    assert residents["RES_A_001"]["phone"] == "+15066396110"
    assert residents["RES_A_001"]["synthetic"] is False
    assert residents["RES_A_001"]["data_origin"] == "operator_provided_twilio_test_recipient"
    assert residents["RES_B_001"]["synthetic"] is True


def test_public_bc_emergency_context_is_source_backed() -> None:
    store = seeded_store()
    context = store.incident_context()

    assert len(context["public_evacuation_orders"]) == 8
    assert len(context["public_ess_facilities"]) == 10
    assert all(order["synthetic"] is False for order in context["public_evacuation_orders"])
    assert all(facility["synthetic"] is False for facility in context["public_ess_facilities"])
    assert any(order["status"] == "Order" for order in context["public_evacuation_orders"])
    assert any(facility["status"] == "OPEN" for facility in context["public_ess_facilities"])
    assert any(
        item["scope"] == "public_bc_emergency_context" and item["synthetic"] is False
        for item in context["demo_disclosures"]
    )


def test_github_issue_backend_creates_real_demo_tasks(monkeypatch) -> None:
    settings = Settings(
        demo_mode=True,
        twilio_allowlist="+15555550123,+15555550124",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
        action_task_backend="github_issues",
        github_repo="youneslaaroussi/fireguard",
        github_token="test-token\n",
    )
    store = FireGuardStore(settings)
    store.seed_demo()
    assessment = run_assessment(store)
    by_type = {action.action_type: action for action in assessment.actions}
    context = store.incident_context()

    assert by_type["road_ops_task"].is_simulated_endpoint is False
    assert by_type["road_ops_task"].external_system == "github_issues_operational_task"
    assert any(
        item["scope"] == "shelter_road_ops_dispatch_actions" and item["label"] == "Real GitHub issue task backend"
        for item in context["demo_disclosures"]
    )

    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "html_url": "https://github.com/youneslaaroussi/fireguard/issues/123",
                "number": 123,
                "url": "https://api.github.com/repos/youneslaaroussi/fireguard/issues/123",
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.services.actions.urllib.request.urlopen", fake_urlopen)

    actions = [action.model_dump() for action in assessment.actions]
    approved_actions, _ = approve_actions(actions, assessment.approval.model_dump())
    road_task = [action for action in approved_actions if action["action_type"] == "road_ops_task"][0]
    executed = execute_action(road_task, settings, store.list("resident_contacts"))

    assert executed["status"] == "executed"
    assert executed["payload"]["delivery_mode"] == "github_issue"
    assert executed["payload"]["github_issue_url"].endswith("/issues/123")
    assert captured["url"] == "https://api.github.com/repos/youneslaaroussi/fireguard/issues"
    assert captured["authorization"] == "Bearer test-token"
    assert "[FireGuard DEMO] Road Ops Task" in captured["body"]["title"]


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


def test_google_adk_openapi_spec_declares_required_tools() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    spec_path = repo_root / "integrations" / "google_adk" / "fireguard_agent" / "tools.openapi.json"
    spec = json.loads(spec_path.read_text())
    operation_ids = {
        operation["operationId"]
        for methods in spec["paths"].values()
        for operation in methods.values()
    }

    assert {
        "get_incident_context",
        "search_operational_memory",
        "compute_zone_risk",
        "compute_routes",
        "draft_evacuation_plan",
        "create_action_bundle",
        "request_human_approval",
        "execute_approved_actions",
    }.issubset(operation_ids)


def test_eval_records_safety_and_grounding() -> None:
    store = seeded_store()
    assessment = run_assessment(store)
    result = evaluate_incident(store, assessment.incident_id)

    assert result["score"] >= 0.84
    assert result["checks"]["route_safety"] is True
    assert result["checks"]["approval_enforcement"] is True


def test_execute_endpoint_can_filter_action_types(monkeypatch) -> None:
    settings = Settings(
        demo_mode=True,
        twilio_allowlist="+15555550123,+15555550124",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
        action_task_backend="github_issues",
        github_repo="youneslaaroussi/fireguard",
        github_token="test-token",
    )
    store = FireGuardStore(settings)
    store.seed_demo()
    assessment = run_assessment(store)
    approved_actions, approval = approve_actions(
        [action.model_dump() for action in assessment.actions],
        assessment.approval.model_dump(),
    )
    for action in approved_actions:
        store.upsert("action_logs", action["action_id"], action)
    store.upsert("approval_requests", approval["approval_id"], approval)

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "html_url": "https://github.com/youneslaaroussi/fireguard/issues/456",
                "number": 456,
                "url": "https://api.github.com/repos/youneslaaroussi/fireguard/issues/456",
            }).encode("utf-8")

    monkeypatch.setattr("app.services.actions.urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())

    result = execute_bundle(
        assessment.bundle_id,
        action_types="shelter_notify,road_ops_task,dispatch_task",
        settings=settings,
        store=store,
    )

    assert len(result["executed"]) == 3
    assert len(result["skipped"]) == 3
    assert {action["action_type"] for action in result["skipped"]} == {"resident_sms"}
    assert all(action["payload"]["delivery_mode"] == "github_issue" for action in result["executed"])
