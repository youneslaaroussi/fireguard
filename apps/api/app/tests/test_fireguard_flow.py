import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.routers.actions import execute as execute_bundle
from app.routers.residents import (
    ResidentTestContactCheckIn,
    process_twilio_inbound_sms,
    resident_test_contact_check_in,
)
from app.routers.shelters import CapacityCheckIn, capacity_check_in
from app.services.actions import approve_actions, execute_action
from app.services.agent import run_assessment
from app.services.evals import evaluate_incident
from app.services.fivetran import fivetran_status, sync_fivetran_to_elastic
from app.services.ingest import _normalize_public_ess_facility, _normalize_public_evacuation_order
from app.services.risk import compute_all_zone_risks
from app.services.routes import best_safe_route, compute_routes
from app.services.shelter_capacity import (
    google_sheets_capacity_status,
    parse_capacity_sheet_values,
    sync_google_sheets_shelter_capacity,
)
from app.services.store import FireGuardStore


def seeded_store() -> FireGuardStore:
    settings = Settings(
        demo_mode=True,
        twilio_allowlist="+15555550123,+15555550124",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_api_key=None,
        fivetran_api_secret=None,
        fivetran_connection_id=None,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from_number=None,
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
    assert "official bc ess facility status is closed" in " ".join(obvious.risk_flags).lower()
    assert "ASSUMPTION_SHELTER_A_CAPACITY" not in obvious.assumption_ids
    assert "BC_ESS_10" in obvious.evidence_ids
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
    assert "Official BC ESS facility status is CLOSED" in rejected
    assert any(
        "BC_ESS_10" in item.get("evidence_ids", [])
        for item in assessment.plan.rejected_alternatives
    )
    assert not any(
        item["destination_id"] == "SHELTER_A"
        and "ASSUMPTION_SHELTER_A_CAPACITY" in item.get("assumption_ids", [])
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
    assert "dispatch task" in zone_c_step.message.lower()
    assert "ASSUMPTION_DISPATCH_BUS_01_DISPATCH_ASSET" not in zone_c_step.assumption_ids


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


def test_sms_execution_requires_operator_contact_provenance() -> None:
    store = seeded_store()
    assessment = run_assessment(store)
    actions = [action.model_dump() for action in assessment.actions]
    approval = assessment.approval.model_dump()
    approved_actions, _ = approve_actions(actions, approval)
    zone_b_sms = [action for action in approved_actions if action["action_type"] == "resident_sms" and action["target"] == "ZONE_B"][0]

    executed = execute_action(zone_b_sms, store.settings, store.resident_contacts_with_updates())

    assert executed["status"] == "failed"
    assert executed["payload"]["blocked_recipient_reasons"][0]["reason"] == "synthetic_placeholder_contact"


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
    assert shelters["SHELTER_A"]["synthetic"] is False
    assert shelters["SHELTER_A"]["source_record_id"] == "BC_ESS_10"
    assert shelters["SHELTER_A"]["data_origin"] == "bc_ess_facility_with_operator_capacity_assumption"
    assert shelters["SHELTER_A"]["status"] == "CLOSED"
    assert shelters["SHELTER_B"]["synthetic"] is False
    assert shelters["SHELTER_B"]["source_record_id"] == "BC_ESS_153"
    assert shelters["SHELTER_B"]["status"] == "OPEN"
    assert shelters["SHELTER_B"]["official_facility_status"] == "OPEN"
    assert shelters["SHELTER_C"]["synthetic"] is False
    assert shelters["SHELTER_C"]["source_record_id"] == "BC_ESS_85"
    assert shelters["SHELTER_C"]["status"] == "CLOSED"
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
    assert context["dispatch_assets"] == []
    assert not any(item["component"] == "dispatch_asset" for item in context["operational_assumptions"])


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
    dispatch_action = by_type["dispatch_task"]
    assert dispatch_action.payload["vehicle_availability_claimed"] is False
    assert dispatch_action.payload["requested_capabilities"] == ["accessible_transport", "responder_support"]
    assert "asset_type" not in dispatch_action.payload
    assert "DISPATCH_BUS_01" not in dispatch_action.evidence_ids
    assert "ASSUMPTION_DISPATCH_BUS_01_DISPATCH_ASSET" not in dispatch_action.assumption_ids


def test_resident_contact_provenance_uses_operator_number_when_configured() -> None:
    settings = Settings(
        demo_mode=True,
        demo_resident_zone_a_phone="+15066396110",
        twilio_allowlist="+15066396110",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from_number=None,
    )
    store = FireGuardStore(settings)
    store.seed_demo()
    residents = {resident["resident_id"]: resident for resident in store.list("resident_contacts")}

    assert residents["RES_A_001"]["phone"] == "+15066396110"
    assert residents["RES_A_001"]["synthetic"] is False
    assert residents["RES_A_001"]["data_origin"] == "operator_provided_twilio_test_recipient"
    assert residents["RES_B_001"]["synthetic"] is True


def test_operator_resident_contact_check_in_updates_context_and_sms_execution() -> None:
    settings = Settings(
        demo_mode=True,
        twilio_allowlist="+15066396110",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from_number=None,
    )
    store = FireGuardStore(settings)
    store.seed_demo()

    result = resident_test_contact_check_in(
        ResidentTestContactCheckIn(
            zone_id="ZONE_B",
            phone="+15066396110",
            updated_by="pio-demo-operator",
        ),
        settings,
        store,
    )
    context = store.incident_context()
    residents = {resident["zone_id"]: resident for resident in store.resident_contacts_with_updates()}

    assert "phone" not in result["contact_update"]
    assert result["contact_update"]["masked_phone"] == "+1***6110"
    assert residents["ZONE_B"]["synthetic"] is False
    assert residents["ZONE_B"]["allowlisted"] is True
    assert any(
        item["assumption_id"] == "INPUT_ZONE_B_CONTACT_OPERATOR_CONFIRMED"
        and item["status"] == "operator_confirmed_test_contact"
        for item in context["operational_assumptions"]
    )

    assessment = run_assessment(store)
    actions = [action.model_dump() for action in assessment.actions]
    approval = assessment.approval.model_dump()
    approved_actions, _ = approve_actions(actions, approval)
    zone_b_sms = [action for action in approved_actions if action["action_type"] == "resident_sms" and action["target"] == "ZONE_B"][0]
    executed = execute_action(zone_b_sms, settings, store.resident_contacts_with_updates())

    assert "INPUT_ZONE_B_CONTACT_OPERATOR_CONFIRMED" in zone_b_sms["assumption_ids"]
    assert executed["status"] == "executed"
    assert executed["payload"]["delivery_mode"] == "simulated_sms_no_twilio_credentials"
    assert executed["payload"]["recipients"] == ["+15066396110"]
    assert executed["payload"]["masked_recipients"] == ["+1***6110"]


def test_operator_resident_contact_check_in_rejects_non_allowlisted_phone() -> None:
    store = seeded_store()

    with pytest.raises(HTTPException) as excinfo:
        resident_test_contact_check_in(
            ResidentTestContactCheckIn(
                zone_id="ZONE_B",
                phone="+15066396110",
                updated_by="pio-demo-operator",
            ),
            store.settings,
            store,
        )

    assert excinfo.value.status_code == 400
    assert "TWILIO_ALLOWLIST" in str(excinfo.value.detail)


def test_twilio_inbound_opt_in_updates_context_and_sms_execution() -> None:
    settings = Settings(
        demo_mode=True,
        twilio_allowlist="+15066396110",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from_number=None,
    )
    store = FireGuardStore(settings)
    store.seed_demo()

    result = process_twilio_inbound_sms(
        {"From": "+15066396110", "Body": "JOIN ZONE_B", "MessageSid": "SM_INBOUND_TEST"},
        settings,
        store,
    )
    context = store.incident_context()
    residents = {resident["zone_id"]: resident for resident in store.resident_contacts_with_updates()}

    assert result["status"] == "opted_in"
    assert result["allowlisted"] is True
    assert "phone" not in result["contact_update"]
    assert result["contact_update"]["source_type"] == "twilio_inbound_opt_in"
    assert residents["ZONE_B"]["synthetic"] is False
    assert residents["ZONE_B"]["data_origin"] == "twilio_inbound_resident_opt_in"
    assert residents["ZONE_B"]["contact_source_type"] == "twilio_inbound_opt_in"
    assert any(
        item["assumption_id"] == "INPUT_ZONE_B_CONTACT_TWILIO_OPT_IN"
        and item["status"] == "twilio_opted_in_allowlisted"
        for item in context["operational_assumptions"]
    )

    assessment = run_assessment(store)
    actions = [action.model_dump() for action in assessment.actions]
    approved_actions, _ = approve_actions(actions, assessment.approval.model_dump())
    zone_b_sms = [
        action
        for action in approved_actions
        if action["action_type"] == "resident_sms" and action["target"] == "ZONE_B"
    ][0]
    executed = execute_action(zone_b_sms, settings, store.resident_contacts_with_updates())

    assert "INPUT_ZONE_B_CONTACT_TWILIO_OPT_IN" in zone_b_sms["assumption_ids"]
    assert executed["status"] == "executed"
    assert executed["payload"]["delivery_mode"] == "simulated_sms_no_twilio_credentials"
    assert executed["payload"]["recipients"] == ["+15066396110"]


def test_twilio_inbound_opt_out_blocks_sms_execution() -> None:
    settings = Settings(
        demo_mode=True,
        twilio_allowlist="+15066396110",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from_number=None,
    )
    store = FireGuardStore(settings)
    store.seed_demo()

    process_twilio_inbound_sms(
        {"From": "+15066396110", "Body": "JOIN ZONE_B", "MessageSid": "SM_JOIN_TEST"},
        settings,
        store,
    )
    result = process_twilio_inbound_sms(
        {"From": "+15066396110", "Body": "STOP ZONE_B", "MessageSid": "SM_STOP_TEST"},
        settings,
        store,
    )
    context = store.incident_context()
    residents = {resident["zone_id"]: resident for resident in store.resident_contacts_with_updates()}

    assert result["status"] == "opted_out"
    assert residents["ZONE_B"]["contact_source_type"] == "twilio_inbound_opt_out"
    assert residents["ZONE_B"]["allowlisted"] is False
    assert any(
        item["assumption_id"] == "INPUT_ZONE_B_CONTACT_TWILIO_OPT_OUT"
        and item["blocks_execution"] is True
        for item in context["operational_assumptions"]
    )

    assessment = run_assessment(store)
    actions = [action.model_dump() for action in assessment.actions]
    approved_actions, _ = approve_actions(actions, assessment.approval.model_dump())
    zone_b_sms = [
        action
        for action in approved_actions
        if action["action_type"] == "resident_sms" and action["target"] == "ZONE_B"
    ][0]
    executed = execute_action(zone_b_sms, settings, store.resident_contacts_with_updates())

    assert executed["status"] == "failed"
    assert executed["payload"]["blocked_recipient_reasons"][0]["reason"] == "contact_record_not_marked_allowlisted"


def test_contact_updates_overlay_seeded_resident_contacts() -> None:
    store = seeded_store()
    updated = FireGuardStore._apply_contact_updates(
        store.list("resident_contacts"),
        [{
            "update_id": "CONTACT_ZONE_C_TEST",
            "resident_id": "RES_ZONE_C_OPERATOR",
            "zone_id": "ZONE_C",
            "phone": "+15066396110",
            "masked_phone": "+1***6110",
            "allowlisted": True,
            "updated_by": "pio-operator",
            "updated_at": "2026-05-06T22:45:00Z",
            "consent_label": "test consent",
        }],
    )
    zone_c = {resident["zone_id"]: resident for resident in updated}["ZONE_C"]

    assert zone_c["resident_id"] == "RES_ZONE_C_OPERATOR"
    assert zone_c["synthetic"] is False
    assert zone_c["data_origin"] == "operator_provided_twilio_test_recipient"
    assert zone_c["contact_update_id"] == "CONTACT_ZONE_C_TEST"


def test_operator_capacity_check_in_updates_shelter_and_assumptions() -> None:
    store = seeded_store()
    result = capacity_check_in(
        "SHELTER_B",
        CapacityCheckIn(capacity_available=3000, capacity_total=3500, updated_by="ess-demo-operator"),
        store,
    )
    context = store.incident_context()
    shelter = {item["shelter_id"]: item for item in context["shelters"]}["SHELTER_B"]

    assert result["capacity_update"]["source_type"] == "operator_capacity_check_in"
    assert shelter["capacity_available"] == 3000
    assert shelter["capacity_is_operator_assumption"] is False
    assert shelter["capacity_operator_confirmed"] is True
    assert shelter["capacity_confirmed_by"] == "ess-demo-operator"
    assert any(
        item["assumption_id"] == "INPUT_SHELTER_B_CAPACITY_OPERATOR_CONFIRMED"
        and item["status"] == "operator_confirmed_not_official_feed"
        for item in context["operational_assumptions"]
    )
    assert store.list("capacity_updates")
    assessment = run_assessment(store)
    shelter_action = [action for action in assessment.actions if action.action_type == "shelter_notify"][0]
    assert "INPUT_SHELTER_B_CAPACITY_OPERATOR_CONFIRMED" in shelter_action.assumption_ids
    assert shelter_action.payload["capacity_operator_confirmed"] is True


def test_capacity_updates_overlay_seeded_shelters() -> None:
    store = seeded_store()
    shelters = store.list("shelters")
    updated = FireGuardStore._apply_capacity_updates(
        shelters,
        [{
            "update_id": "CAPACITY_SHELTER_B_TEST",
            "shelter_id": "SHELTER_B",
            "capacity_total": 3500,
            "capacity_available": 2999,
            "updated_by": "ess-operator",
            "updated_at": "2026-05-06T22:30:00Z",
            "note": "test",
        }],
    )
    shelter_b = {shelter["shelter_id"]: shelter for shelter in updated}["SHELTER_B"]

    assert shelter_b["capacity_available"] == 2999
    assert shelter_b["capacity_is_operator_assumption"] is False
    assert shelter_b["capacity_operator_confirmed"] is True
    assert shelter_b["capacity_update_id"] == "CAPACITY_SHELTER_B_TEST"


def test_google_sheets_capacity_feed_updates_shelter_and_assumptions(monkeypatch) -> None:
    settings = Settings(
        demo_mode=True,
        google_sheets_capacity_spreadsheet_id="sheet-123",
        google_sheets_capacity_range="shelter_capacity!A:F",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        fivetran_bigquery_project=None,
        google_application_credentials=None,
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from_number=None,
    )
    store = FireGuardStore(settings)
    store.seed_demo()

    def fake_read(_settings: Settings) -> list[list[str]]:
        return [
            ["shelter_id", "capacity_total", "capacity_available", "updated_by", "note", "updated_at"],
            ["SHELTER_B", "3500", "3100", "railyard-operator", "sheet test", "2026-05-07T14:00:00Z"],
        ]

    monkeypatch.setattr("app.services.shelter_capacity._read_sheets_values", fake_read)
    result = sync_google_sheets_shelter_capacity(store)
    context = store.incident_context()
    shelter = {item["shelter_id"]: item for item in context["shelters"]}["SHELTER_B"]

    assert result["status"] == "synced"
    assert result["updated_shelter_ids"] == ["SHELTER_B"]
    assert shelter["capacity_available"] == 3100
    assert shelter["capacity_source_type"] == "google_sheets_capacity_feed"
    assert shelter["capacity_operator_confirmed"] is True
    assert any(
        item["assumption_id"] == "INPUT_SHELTER_B_CAPACITY_OPERATOR_CONFIRMED"
        and item["status"] == "operator_confirmed_not_official_feed"
        for item in context["operational_assumptions"]
    )
    status = google_sheets_capacity_status(store)
    assert status["configured"] is True
    assert status["latest_update_count"] == 1


def test_google_sheets_capacity_parser_rejects_bad_rows() -> None:
    store = seeded_store()
    parsed = parse_capacity_sheet_values(
        [
            ["shelter_id", "capacity_total", "capacity_available"],
            ["SHELTER_B", "100", "101"],
            ["NOPE", "100", "10"],
        ],
        store,
    )

    assert parsed["updates"] == []
    assert len(parsed["errors"]) == 2
    assert "cannot exceed" in parsed["errors"][0]["reason"]
    assert parsed["errors"][1]["reason"] == "Shelter not found."


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


def test_public_bc_live_normalizers_preserve_source_status_and_dates() -> None:
    captured_at = "2026-05-07T04:50:00Z"
    order = _normalize_public_evacuation_order(
        {
            "id": 7,
            "geometry": {"type": "Polygon", "coordinates": [[[-122.0, 52.0], [-121.0, 52.0], [-121.0, 53.0], [-122.0, 52.0]]]},
            "properties": {
                "EMRG_OAA_SYSID": 7,
                "EVENT_NAME": "Live source test",
                "EVENT_TYPE": "Wildfire",
                "ORDER_ALERT_NAME": "Live Area",
                "ORDER_ALERT_STATUS": "Order",
                "ISSUING_AGENCY": "Test Agency",
                "MULTI_SOURCED_POPULATION": 42,
                "MULTI_SOURCED_HOMES": 12,
                "EVENT_START_DATE": 1620907200000,
                "DATE_MODIFIED": 1697016000000,
            },
        },
        captured_at=captured_at,
        source_url="https://example.invalid/orders/query",
        source_query="where=1=1",
    )
    facility = _normalize_public_ess_facility(
        {
            "id": 153,
            "geometry": {"type": "Point", "coordinates": [-120.788059, 50.108033]},
            "properties": {
                "ESS_FACILITY_ID": 153,
                "FACILITY_NAME": "Railyard Mall",
                "FACILITY_TYPE_CODE": "RC",
                "ADDRESS": "source address",
                "COMMUNITY": "City of Merritt",
                "MUNICIPALITY": "City of Merritt",
                "STATUS": "OPEN",
                "STATUS_DATE": 1643587200000,
            },
        },
        captured_at=captured_at,
        source_url="https://example.invalid/ess/query",
        source_query="where=STATUS='OPEN'",
    )

    assert order is not None
    assert order["order_alert_id"] == "BC_OAA_7"
    assert order["status"] == "Order"
    assert order["population"] == 42
    assert order["updated_at"] == "2023-10-11T09:20:00Z"
    assert order["data_origin"] == "bc_emergencymapbc_public_live"
    assert facility is not None
    assert facility["facility_id"] == "BC_ESS_153"
    assert facility["status"] == "OPEN"
    assert facility["location"] == {"lat": 50.108033, "lon": -120.788059}
    assert facility["updated_at"] == "2022-01-31T00:00:00Z"
    assert facility["data_origin"] == "bc_emergencymapbc_public_live"


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
    assert status["managed_api"]["status"] == "skipped"
    assert status["latest_run"]["status"] == "synced"
    assert status["fallback_active"] is True
    assert status["warnings"]
    assert "fire_hotspots" in status["streams"]


def test_fivetran_status_uses_managed_api_without_exposing_credentials(monkeypatch) -> None:
    settings = Settings(
        demo_mode=True,
        fivetran_api_key="test-key",
        fivetran_api_secret="test-secret",
        fivetran_connection_id="end_unfunded",
        fivetran_bigquery_project="verdant-upgrade-493301-q1",
        fivetran_bigquery_dataset="fireguard_ingestion",
        phoenix_tracing_enabled=False,
        gemini_assessment_enabled=False,
        google_application_credentials=None,
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from_number=None,
    )
    store = FireGuardStore(settings)

    def fake_get(_: Settings, endpoint: str) -> dict:
        if endpoint == "connections/end_unfunded":
            return {
                "data": {
                    "id": "end_unfunded",
                    "service": "connector_sdk",
                    "schema": "fireguard_ingestion",
                    "group_id": "observatory_impartially",
                    "paused": False,
                    "status": {
                        "setup_state": "connected",
                        "schema_status": "ready",
                        "sync_state": "scheduled",
                        "update_state": "on_schedule",
                        "is_historical_sync": False,
                        "tasks": [],
                        "warnings": [],
                    },
                    "created_at": "2026-05-06T11:57:16.922234Z",
                    "succeeded_at": "2026-05-07T06:08:57.915000Z",
                    "sync_frequency": 360,
                }
            }
        if endpoint == "destinations/observatory_impartially":
            return {
                "data": {
                    "id": "observatory_impartially",
                    "service": "big_query",
                    "region": "GCP_US_EAST4",
                    "setup_status": "connected",
                    "config": {
                        "project_id": "verdant-upgrade-493301-q1",
                        "secret_key": "should-not-leak",
                        "location": "US",
                        "data_set_location": "US",
                    },
                }
            }
        if endpoint == "groups/observatory_impartially":
            return {"data": {"id": "observatory_impartially", "name": "fireguard_bigquery"}}
        raise AssertionError(endpoint)

    monkeypatch.setattr("app.services.fivetran._fivetran_get", fake_get)
    status = fivetran_status(store)

    assert status["managed_api"]["status"] == "ok"
    assert status["managed_api"]["connection"]["service"] == "connector_sdk"
    assert status["managed_api"]["connection"]["setup_state"] == "connected"
    assert status["managed_api"]["connection"]["succeeded_at"] == "2026-05-07T06:08:57.915000Z"
    assert status["managed_api"]["destination"]["service"] == "big_query"
    assert "test-secret" not in json.dumps(status)
    assert "should-not-leak" not in json.dumps(status)


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


def test_phoenix_cloud_space_name_builds_space_specific_endpoint() -> None:
    from app.services.phoenix import _application_url, _collector_endpoint

    settings = Settings(
        phoenix_collector_endpoint="https://app.phoenix.arize.com",
        phoenix_cloud_space_name="deep-shot",
        phoenix_api_key="test-key",
        phoenix_tracing_enabled=True,
    )

    endpoint = _collector_endpoint(settings)

    assert endpoint == "https://app.phoenix.arize.com/s/deep-shot/v1/traces"
    assert _application_url(endpoint) == "https://app.phoenix.arize.com/s/deep-shot"


def test_arize_ax_status_checks_otlp_without_exposing_credentials(monkeypatch) -> None:
    from app.services.phoenix import arize_ax_status

    settings = Settings(
        arize_space_id="test-space-id",
        arize_api_key="test-arize-secret",
        arize_collector_endpoint="https://otlp.arize.com/v1/traces",
        phoenix_tracing_enabled=False,
    )

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b""

    def fake_urlopen(request, timeout):
        headers = dict(request.header_items())
        assert headers["Space_id"] == "test-space-id"
        assert headers["Api_key"] == "test-arize-secret"
        assert timeout == settings.phoenix_status_timeout_seconds
        return FakeResponse()

    monkeypatch.setattr("app.services.phoenix.urllib.request.urlopen", fake_urlopen)
    status = arize_ax_status(settings)

    assert status["connection_check"]["status"] == "ok"
    assert status["connection_check"]["http_status"] == 200
    assert "test-arize-secret" not in json.dumps(status)
    assert "test-space-id" not in json.dumps(status)


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
