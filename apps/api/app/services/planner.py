from __future__ import annotations

import uuid

from app.models.schemas import EvacuationPlan, PlanStep, ZoneRisk
from app.services.actions import create_action, create_approval
from app.services.routes import best_safe_route, rejected_routes


def draft_plan(incident_id: str, context: dict, zone_risks: list[ZoneRisk], routes: list) -> EvacuationPlan:
    risk_by_zone = {risk.zone_id: risk for risk in zone_risks}
    steps: list[PlanStep] = []

    route_a = best_safe_route(routes, "ZONE_A")
    route_b = best_safe_route(routes, "ZONE_B")
    route_c = best_safe_route(routes, "ZONE_C")
    zone_b_strategy = "staged_evacuation" if route_b else "hold_for_route_confirmation"
    zone_b_destination = route_b.destination_id if route_b else None
    zone_b_message = (
        "[DEMO - FireGuard] Prepare to evacuate Likely East Bench in 15 minutes toward Williams Lake ESS Reception Centre. Wait for traffic-control release."
        if route_b
        else "[DEMO - FireGuard] Likely East Bench should hold position and prepare. Do not self-evacuate until road ops confirms a safe release corridor."
    )
    zone_b_rationale = (
        ["High risk, but immediate simultaneous departure would overload the shared rural corridor.", "Williams Lake ESS can absorb Zone B after Zone A is staged."]
        if route_b
        else ["Google Routes-backed route checks did not find a currently safe self-evacuation path.", "Holding avoids routing residents through a closure while road ops verifies release timing."]
    )

    steps.append(PlanStep(
        step_id="STEP_ZONE_A_EVAC_NOW",
        zone_id="ZONE_A",
        strategy="evacuate_now",
        destination_id=route_a.destination_id if route_a else "SHELTER_B",
        start_after_minutes=0,
        message="[DEMO - FireGuard] Evacuate Quesnel River West now toward Williams Lake ESS Reception Centre. Avoid Little Lake Quesnel River Road near the DriveBC closure.",
        rationale=["Critical risk and a safe alternate route exists.", "The nearest shelter route is rejected because it intersects a closure and fire-risk buffer."],
        evidence_ids=risk_by_zone["ZONE_A"].evidence_ids + (route_a.evidence_ids if route_a else []),
    ))
    steps.append(PlanStep(
        step_id="STEP_ZONE_B_STAGE",
        zone_id="ZONE_B",
        strategy=zone_b_strategy,
        destination_id=zone_b_destination,
        start_after_minutes=15,
        message=zone_b_message,
        rationale=zone_b_rationale,
        evidence_ids=risk_by_zone["ZONE_B"].evidence_ids + (route_b.evidence_ids if route_b else []),
    ))
    steps.append(PlanStep(
        step_id="STEP_ZONE_C_SHELTER_DISPATCH",
        zone_id="ZONE_C",
        strategy="shelter_in_place_dispatch_assisted",
        destination_id=route_c.destination_id if route_c else None,
        start_after_minutes=0,
        message="[DEMO - FireGuard] Little Lake Clinic District should shelter in place temporarily. Dispatch-assisted evacuation is being assigned for vulnerable residents.",
        rationale=["Self-evacuation routes cross the closure or fire-risk buffer.", "Vulnerable population and low vehicle access make unsupported evacuation unsafe."],
        evidence_ids=risk_by_zone["ZONE_C"].evidence_ids,
    ))

    plan_id = f"PLAN_{uuid.uuid4().hex[:8].upper()}"
    return EvacuationPlan(
        plan_id=plan_id,
        incident_id=incident_id,
        summary="Stage Quesnel River West immediately to Williams Lake ESS, hold Likely East Bench for 15 minutes to avoid corridor congestion, and shelter Little Lake Clinic District in place while dispatch-assisted evacuation is assigned.",
        recommended_strategy="staged_evacuation",
        confidence=0.84,
        zone_risks=zone_risks,
        routes=routes,
        steps=steps,
        rejected_alternatives=rejected_routes(routes),
        data_freshness=context.get("data_freshness", []),
        risks_if_wrong=[
            "If wind shifts north, Likely East Bench may need immediate evacuation instead of staged release.",
            "If Williams Lake ESS capacity changes, evacuees may need splitting between Williams Lake and Quesnel reception centres.",
            "If road closure data is stale, road ops must verify before releasing traffic.",
        ],
        fallback_plan="If alternate evacuation routes become unsafe, expand shelter-in-place, assign door-to-door checks, and request additional accessible transport for vulnerable residents.",
        requires_approval=True,
    )


def create_bundle(plan: EvacuationPlan, context: dict) -> tuple[str, list, object]:
    bundle_id = f"BUNDLE_{uuid.uuid4().hex[:8].upper()}"
    actions = []
    for step in plan.steps:
        actions.append(create_action(
            bundle_id=bundle_id,
            action_type="resident_sms",
            target=step.zone_id,
            message=step.message,
            payload={"zone_id": step.zone_id, "plan_id": plan.plan_id, "start_after_minutes": step.start_after_minutes},
            reason="Resident instruction from approved staged evacuation plan.",
            evidence_ids=step.evidence_ids,
            confidence=plan.confidence,
        ))

    actions.extend([
        create_action(
            bundle_id,
            "shelter_notify",
            "SHELTER_B",
            "Prepare for staged arrivals from Quesnel River West and Likely East Bench within 75 minutes.",
            {"shelter_id": "SHELTER_B", "expected_arrivals": 1030, "eta_minutes": 75, "needs": ["accessible_cots", "pet_area"], "source_plan_id": plan.plan_id},
            "Williams Lake ESS is the selected safe reception centre with enough available capacity.",
            ["SHELTER_B"],
            plan.confidence,
        ),
        create_action(
            bundle_id,
            "road_ops_task",
            "Little Lake Quesnel River Road",
            "Create traffic-control task to keep residents away from the DriveBC closure and release staged outbound flow.",
            {"task_type": "close_or_control_road", "road_segment": "Little Lake Quesnel River Road near Likely Road Turnoff", "priority": "high", "source_plan_id": plan.plan_id},
            "The nearest route approaches a real DriveBC road closure and fire-risk buffer.",
            ["drivebc.ca/DBC-90684"],
            plan.confidence,
        ),
        create_action(
            bundle_id,
            "dispatch_task",
            "ZONE_C",
            "Assign accessible bus and responder support to Little Lake Clinic District.",
            {"task_type": "assist_evacuation", "zone_id": "ZONE_C", "asset_type": "accessible_bus", "priority": "critical", "source_plan_id": plan.plan_id},
            "Zone C has high vulnerable count and unsafe self-evacuation routes.",
            ["ZONE_C", "DISPATCH_BUS_01"],
            plan.confidence,
        ),
    ])
    approval = create_approval(bundle_id)
    return bundle_id, actions, approval
