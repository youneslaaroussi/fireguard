from __future__ import annotations

import uuid

from app.config import Settings
from app.models.schemas import EvacuationPlan, PlanStep, ZoneRisk
from app.services.actions import create_action, create_approval
from app.services.routes import best_safe_route, rejected_routes


def _by_id(items: list[dict], id_field: str) -> dict[str, dict]:
    return {item[id_field]: item for item in items}


def _zone_name(zones: dict[str, dict], zone_id: str) -> str:
    return zones.get(zone_id, {}).get("name", zone_id)


def _shelter_name(shelters: dict[str, dict], shelter_id: str | None) -> str:
    if not shelter_id:
        return "a verified reception centre"
    return shelters.get(shelter_id, {}).get("name", shelter_id)


def _route_assumption_ids(route) -> list[str]:
    return list(getattr(route, "assumption_ids", []) or [])


def _shelter_capacity_tracking_id(shelter_id: str, shelter: dict) -> str:
    if shelter.get("capacity_operator_confirmed"):
        return f"INPUT_{shelter_id}_CAPACITY_OPERATOR_CONFIRMED"
    return f"ASSUMPTION_{shelter_id}_CAPACITY"


def _resident_contact_tracking_ids(context: dict, zone_id: str) -> list[str]:
    return [
        str(assumption["assumption_id"])
        for assumption in context.get("operational_assumptions", [])
        if assumption.get("component") == "resident_contact" and assumption.get("target") == zone_id
    ]


def draft_plan(incident_id: str, context: dict, zone_risks: list[ZoneRisk], routes: list) -> EvacuationPlan:
    risk_by_zone = {risk.zone_id: risk for risk in zone_risks}
    zones_by_id = _by_id(context.get("zones", []), "zone_id")
    shelters_by_id = _by_id(context.get("shelters", []), "shelter_id")
    steps: list[PlanStep] = []

    route_a = best_safe_route(routes, "ZONE_A")
    route_b = best_safe_route(routes, "ZONE_B")
    route_c = best_safe_route(routes, "ZONE_C")
    zone_a_name = _zone_name(zones_by_id, "ZONE_A")
    zone_b_name = _zone_name(zones_by_id, "ZONE_B")
    zone_c_name = _zone_name(zones_by_id, "ZONE_C")
    zone_a_destination_name = _shelter_name(shelters_by_id, route_a.destination_id if route_a else None)
    zone_b_destination_name = _shelter_name(shelters_by_id, route_b.destination_id if route_b else None)
    zone_a_strategy = "evacuate_now" if route_a else "shelter_in_place_dispatch_assisted"
    zone_a_destination = route_a.destination_id if route_a else None
    zone_a_message = (
        f"[DEMO - FireGuard] Evacuate {zone_a_name} now toward {zone_a_destination_name}. Avoid Little Lake Quesnel River Road near the DriveBC closure."
        if route_a
        else f"[DEMO - FireGuard] {zone_a_name} should shelter in place temporarily. No safe self-evacuation route is currently verified."
    )
    zone_a_rationale = (
        ["Critical risk and a safe alternate route exists.", "The nearest shelter route is rejected because it intersects a closure and fire-risk buffer."]
        if route_a
        else ["Route checks did not find a safe self-evacuation path.", "Shelter-in-place and dispatch support are safer until road ops verifies an outbound corridor."]
    )
    zone_b_strategy = "staged_evacuation" if route_b else "hold_for_route_confirmation"
    zone_b_destination = route_b.destination_id if route_b else None
    zone_b_message = (
        f"[DEMO - FireGuard] Prepare to evacuate {zone_b_name} in 15 minutes toward {zone_b_destination_name}. Wait for traffic-control release."
        if route_b
        else f"[DEMO - FireGuard] {zone_b_name} should hold position and prepare. Do not self-evacuate until road ops confirms a safe release corridor."
    )
    zone_b_rationale = (
        ["High risk, but immediate simultaneous departure would overload the shared rural corridor.", f"{zone_b_destination_name} can absorb Zone B after Zone A is staged."]
        if route_b
        else ["Google Routes-backed route checks did not find a currently safe self-evacuation path.", "Holding avoids routing residents through a closure while road ops verifies release timing."]
    )

    steps.append(PlanStep(
        step_id="STEP_ZONE_A_EVAC_NOW",
        zone_id="ZONE_A",
        strategy=zone_a_strategy,
        destination_id=zone_a_destination,
        start_after_minutes=0,
        message=zone_a_message,
        rationale=zone_a_rationale,
        evidence_ids=risk_by_zone["ZONE_A"].evidence_ids + (route_a.evidence_ids if route_a else []),
        assumption_ids=_route_assumption_ids(route_a),
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
        assumption_ids=_route_assumption_ids(route_b),
    ))
    steps.append(PlanStep(
        step_id="STEP_ZONE_C_SHELTER_DISPATCH",
        zone_id="ZONE_C",
        strategy="shelter_in_place_dispatch_assisted",
        destination_id=route_c.destination_id if route_c else None,
        start_after_minutes=0,
        message=f"[DEMO - FireGuard] {zone_c_name} should shelter in place temporarily. A dispatch task is being created for vulnerable residents.",
        rationale=[
            "Self-evacuation routes cross the closure or fire-risk buffer.",
            "Vulnerable population and low vehicle access make unsupported evacuation unsafe.",
            "FireGuard requests dispatcher assignment but does not claim any specific vehicle is available.",
        ],
        evidence_ids=risk_by_zone["ZONE_C"].evidence_ids,
        assumption_ids=["ASSUMPTION_ZONE_C_VULNERABILITY", "ASSUMPTION_ZONE_C_VEHICLE_ACCESS"],
    ))

    plan_id = f"PLAN_{uuid.uuid4().hex[:8].upper()}"
    return EvacuationPlan(
        plan_id=plan_id,
        incident_id=incident_id,
        summary=f"Stage {zone_a_name} immediately to {zone_a_destination_name}, hold {zone_b_name} for 15 minutes to avoid corridor congestion, and shelter {zone_c_name} in place while a dispatch assignment task is created.",
        recommended_strategy="staged_evacuation",
        confidence=0.84,
        zone_risks=zone_risks,
        routes=routes,
        steps=steps,
        rejected_alternatives=rejected_routes(routes),
        operational_assumptions=[
            assumption
            for assumption in context.get("operational_assumptions", [])
            if assumption.get("affects_decision") or assumption.get("blocks_execution")
        ],
        data_freshness=context.get("data_freshness", []),
        risks_if_wrong=[
            f"If wind shifts north, {zone_b_name} may need immediate evacuation instead of staged release.",
            "Shelter capacity numbers are operator-entered demo assumptions; confirm with the ESS coordinator before treating them as authoritative.",
            "Dispatch resource availability is not asserted by FireGuard; the dispatch task requires operator assignment.",
            "If road closure data is stale, road ops must verify before releasing traffic.",
        ],
        fallback_plan="If alternate evacuation routes become unsafe, expand shelter-in-place, assign door-to-door checks, and request additional accessible transport for vulnerable residents.",
        requires_approval=True,
    )


def create_bundle(plan: EvacuationPlan, context: dict, settings: Settings | None = None) -> tuple[str, list, object]:
    bundle_id = f"BUNDLE_{uuid.uuid4().hex[:8].upper()}"
    actions = []
    zones_by_id = _by_id(context.get("zones", []), "zone_id")
    shelters_by_id = _by_id(context.get("shelters", []), "shelter_id")
    arrivals_by_shelter: dict[str, int] = {}
    for step in plan.steps:
        if step.destination_id:
            arrivals_by_shelter[step.destination_id] = (
                arrivals_by_shelter.get(step.destination_id, 0)
                + int(zones_by_id.get(step.zone_id, {}).get("population", 0))
            )
    primary_shelter_id = max(arrivals_by_shelter, key=arrivals_by_shelter.get, default="SHELTER_B")
    primary_shelter_name = _shelter_name(shelters_by_id, primary_shelter_id)
    primary_shelter = shelters_by_id.get(primary_shelter_id, {})
    primary_shelter_capacity_id = _shelter_capacity_tracking_id(primary_shelter_id, primary_shelter)
    expected_arrivals = arrivals_by_shelter.get(primary_shelter_id, 0)
    zone_c_name = _zone_name(zones_by_id, "ZONE_C")
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
            settings=settings,
            assumption_ids=step.assumption_ids + _resident_contact_tracking_ids(context, step.zone_id),
        ))

    actions.extend([
        create_action(
            bundle_id,
            "shelter_notify",
            primary_shelter_id,
            f"Prepare for staged arrivals from approved FireGuard evacuation steps within 75 minutes at {primary_shelter_name}.",
            {
                "shelter_id": primary_shelter_id,
                "expected_arrivals": expected_arrivals,
                "eta_minutes": 75,
                "needs": ["accessible_cots", "pet_area"],
                "source_plan_id": plan.plan_id,
                "capacity_available": primary_shelter.get("capacity_available"),
                "capacity_total": primary_shelter.get("capacity_total"),
                "capacity_is_operator_assumption": primary_shelter.get("capacity_is_operator_assumption", False),
                "capacity_operator_confirmed": primary_shelter.get("capacity_operator_confirmed", False),
                "capacity_source_label": primary_shelter.get("capacity_source_label"),
                "capacity_confirmed_at": primary_shelter.get("capacity_confirmed_at"),
                "capacity_confirmed_by": primary_shelter.get("capacity_confirmed_by"),
            },
            f"{primary_shelter_name} is selected using operator-provided capacity data that must be confirmed against an authoritative ESS feed before real-world use.",
            [primary_shelter_id],
            plan.confidence,
            settings=settings,
            assumption_ids=[primary_shelter_capacity_id],
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
            settings=settings,
        ),
        create_action(
            bundle_id,
            "dispatch_task",
            "ZONE_C",
            f"Create dispatch task requesting accessible transport and responder support to {zone_c_name}.",
            {
                "task_type": "assist_evacuation",
                "zone_id": "ZONE_C",
                "requested_capabilities": ["accessible_transport", "responder_support"],
                "vehicle_availability_claimed": False,
                "assignment_owner": "dispatch_coordinator",
                "priority": "critical",
                "source_plan_id": plan.plan_id,
            },
            "Zone C has high vulnerable count and unsafe self-evacuation routes; a human dispatcher must assign actual resources.",
            ["ZONE_C"],
            plan.confidence,
            settings=settings,
            assumption_ids=["ASSUMPTION_ZONE_C_VULNERABILITY", "ASSUMPTION_ZONE_C_VEHICLE_ACCESS"],
        ),
    ])
    approval = create_approval(bundle_id)
    return bundle_id, actions, approval
