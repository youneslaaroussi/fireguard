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

    steps.append(PlanStep(
        step_id="STEP_ZONE_A_EVAC_NOW",
        zone_id="ZONE_A",
        strategy="evacuate_now",
        destination_id=route_a.destination_id if route_a else "SHELTER_B",
        start_after_minutes=0,
        message="[DEMO - FireGuard] Evacuate Canyon Ridge now via the westbound alternate route to Lillooet Secondary Reception Centre. Avoid Highway 1 eastbound near Kwoiek Creek.",
        rationale=["Critical risk and a safe alternate route exists.", "The nearest shelter route is rejected because it intersects a closure and fire-risk buffer."],
        evidence_ids=risk_by_zone["ZONE_A"].evidence_ids + (route_a.evidence_ids if route_a else []),
    ))
    steps.append(PlanStep(
        step_id="STEP_ZONE_B_STAGE",
        zone_id="ZONE_B",
        strategy="staged_evacuation",
        destination_id=route_b.destination_id if route_b else "SHELTER_B",
        start_after_minutes=15,
        message="[DEMO - FireGuard] Prepare to evacuate River Flats in 15 minutes via the westbound alternate route to Lillooet Secondary. Wait for traffic-control release.",
        rationale=["High risk, but immediate simultaneous departure would overload the shared corridor.", "Shelter B can absorb Zone B after Zone A is staged."],
        evidence_ids=risk_by_zone["ZONE_B"].evidence_ids,
    ))
    steps.append(PlanStep(
        step_id="STEP_ZONE_C_SHELTER_DISPATCH",
        zone_id="ZONE_C",
        strategy="shelter_in_place_dispatch_assisted",
        destination_id=route_c.destination_id if route_c else None,
        start_after_minutes=0,
        message="[DEMO - FireGuard] Pine Clinic District should shelter in place temporarily. Dispatch-assisted evacuation is being assigned for vulnerable residents.",
        rationale=["Self-evacuation routes cross the closure or fire-risk buffer.", "Vulnerable population and low vehicle access make unsupported evacuation unsafe."],
        evidence_ids=risk_by_zone["ZONE_C"].evidence_ids,
    ))

    plan_id = f"PLAN_{uuid.uuid4().hex[:8].upper()}"
    return EvacuationPlan(
        plan_id=plan_id,
        incident_id=incident_id,
        summary="Stage Canyon Ridge immediately to Shelter B, hold River Flats for 15 minutes to avoid corridor congestion, and shelter Pine Clinic District in place while dispatch-assisted evacuation is assigned.",
        recommended_strategy="staged_evacuation",
        confidence=0.84,
        zone_risks=zone_risks,
        routes=routes,
        steps=steps,
        rejected_alternatives=rejected_routes(routes),
        data_freshness=context.get("data_freshness", []),
        risks_if_wrong=[
            "If wind shifts north, River Flats may need immediate evacuation instead of staged release.",
            "If Shelter B capacity changes, evacuees may need splitting between Shelter B and Shelter C.",
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
            "Prepare for staged arrivals from Canyon Ridge and River Flats within 45 minutes.",
            {"shelter_id": "SHELTER_B", "expected_arrivals": 1030, "eta_minutes": 45, "needs": ["accessible_cots", "pet_area"], "source_plan_id": plan.plan_id},
            "Shelter B is the selected safe reception centre with enough available capacity.",
            ["SHELTER_B"],
            plan.confidence,
        ),
        create_action(
            bundle_id,
            "road_ops_task",
            "Highway 1 eastbound ramp",
            "Create traffic-control task to block the unsafe eastbound route and release staged westbound flow.",
            {"task_type": "close_or_control_road", "road_segment": "Highway 1 eastbound near Kwoiek Creek", "priority": "high", "source_plan_id": plan.plan_id},
            "The obvious route intersects a closure and fire-risk buffer.",
            ["DBC_REPLAY_CLOSURE_001"],
            plan.confidence,
        ),
        create_action(
            bundle_id,
            "dispatch_task",
            "ZONE_C",
            "Assign accessible bus and responder support to Pine Clinic District.",
            {"task_type": "assist_evacuation", "zone_id": "ZONE_C", "asset_type": "accessible_bus", "priority": "critical", "source_plan_id": plan.plan_id},
            "Zone C has high vulnerable count and unsafe self-evacuation routes.",
            ["ZONE_C", "DISPATCH_BUS_01"],
            plan.confidence,
        ),
    ])
    approval = create_approval(bundle_id)
    return bundle_id, actions, approval
