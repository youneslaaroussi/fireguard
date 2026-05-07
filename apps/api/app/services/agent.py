from __future__ import annotations

from typing import Any

from app.models.schemas import AssessmentResult
from app.services import demo_data
from app.services.evals import evaluate_incident
from app.services.gemini import run_gemini_tool_assessment
from app.services.planner import create_bundle, draft_plan
from app.services.risk import compute_all_zone_risks
from app.services.routes import compute_routes
from app.services.store import FireGuardStore
from app.services.trace import TraceRecorder
from app.services.time import now_iso


def run_assessment(store: FireGuardStore, incident_id: str = demo_data.INCIDENT_ID) -> AssessmentResult:
    context = store.incident_context(incident_id)
    trace = TraceRecorder(incident_id, store.settings)
    trace.add(
        "observe",
        "get_incident_context",
        {"incident_id": incident_id},
        {
            "fires": len(context["fires"]),
            "perimeters": len(context["perimeters"]),
            "road_events": len(context["road_events"]),
            "zones": len(context["zones"]),
            "shelters": len(context["shelters"]),
        },
        [doc["external_id"] for doc in context["fires"][:2]],
    )

    memory_hits = store.search_text(["policies", "road_events", "fire_hotspots"], "unsafe route closure shelter in place approval")
    trace.add(
        "retrieve",
        "search_operational_memory",
        {"query": "unsafe route closure shelter in place approval"},
        {"hits": [{"index": hit["_index"], "id": hit["_id"], "score": hit["_score"]} for hit in memory_hits[:6]]},
        [hit["_id"] for hit in memory_hits[:6]],
    )

    zone_risks = compute_all_zone_risks(context)
    trace.add(
        "assess",
        "compute_zone_risk",
        {"zones": [zone["zone_id"] for zone in context["zones"]]},
        [risk.model_dump() for risk in zone_risks],
        [evidence_id for risk in zone_risks for evidence_id in risk.evidence_ids],
    )

    routes = compute_routes(context, google_maps_api_key=store.settings.google_maps_api_key)
    route_assumption_ids = sorted({assumption_id for route in routes for assumption_id in route.assumption_ids})
    trace.add(
        "route",
        "compute_routes",
        {"origins": [zone["zone_id"] for zone in context["zones"]], "destinations": [shelter["shelter_id"] for shelter in context["shelters"]]},
        [route.model_dump() for route in routes],
        [evidence_id for route in routes for evidence_id in route.evidence_ids],
        route_assumption_ids,
    )

    plan = draft_plan(incident_id, context, zone_risks, routes)
    trace.add(
        "plan",
        "draft_evacuation_plan",
        {"incident_id": incident_id},
        plan.model_dump(),
        [],
        [item["assumption_id"] for item in plan.operational_assumptions],
    )

    bundle_id, actions, approval = create_bundle(plan, context, store.settings)
    action_assumption_ids = sorted({assumption_id for action in actions for assumption_id in action.assumption_ids})
    trace.add(
        "act",
        "create_action_bundle",
        {"plan_id": plan.plan_id},
        {"bundle_id": bundle_id, "actions": [action.model_dump() for action in actions]},
        [evidence_id for action in actions for evidence_id in action.evidence_ids],
        action_assumption_ids,
    )
    trace.add("approval", "request_human_approval", {"bundle_id": bundle_id}, approval.model_dump(), [])

    agent_review = run_gemini_tool_assessment(store.settings, incident_id, context, plan, actions)
    trace.add(
        "reason",
        "gemini_tool_orchestration",
        {"incident_id": incident_id, "model": store.settings.gemini_model},
        agent_review,
        [call for call in agent_review.get("tool_calls", [])],
    )

    store.upsert("plans", plan.plan_id, plan.model_dump())
    for action in actions:
        store.upsert("action_logs", action.action_id, action.model_dump())
    store.upsert("approval_requests", approval.approval_id, approval.model_dump())
    trace_id = f"TRACE_{incident_id}_{now_iso()}"
    store.upsert("traces", trace_id, {
        "trace_id": trace_id,
        "incident_id": incident_id,
        "events": trace.events,
        "phoenix_trace_ids": trace.phoenix_trace_ids,
        "arize_ax_trace_ids": trace.arize_ax_trace_ids,
        "created_at": now_iso(),
    })
    evaluate_incident(store, incident_id)

    return AssessmentResult(
        incident_id=incident_id,
        context=context,
        plan=plan,
        bundle_id=bundle_id,
        approval=approval,
        actions=actions,
        trace=trace.events,
        agent_review=agent_review,
        gemini_status=agent_review.get("status"),
        gemini_tool_calls=agent_review.get("tool_calls", []),
        phoenix_trace_ids=trace.phoenix_trace_ids,
    )


def tool_response(name: str, payload: dict[str, Any], store: FireGuardStore) -> dict[str, Any]:
    context = store.incident_context(payload.get("incident_id", demo_data.INCIDENT_ID))
    if name == "get_incident_context":
        return context
    if name == "search_operational_memory":
        hits = store.search_text(["policies", "road_events", "fire_hotspots", "shelters", "evacuation_zones"], payload.get("query", ""))
        return {"hits": hits[:10], "evidence_refs": [hit["_id"] for hit in hits[:10]]}
    if name == "compute_zone_risk":
        zone_id = payload.get("zone_id")
        zone_context = {**context, "zones": [zone for zone in context["zones"] if not zone_id or zone["zone_id"] == zone_id]}
        return {"risks": [risk.model_dump() for risk in compute_all_zone_risks(zone_context)]}
    if name == "compute_routes":
        return {"routes": [route.model_dump() for route in compute_routes(context, google_maps_api_key=store.settings.google_maps_api_key)]}
    if name == "draft_evacuation_plan":
        risks = compute_all_zone_risks(context)
        routes = compute_routes(context, google_maps_api_key=store.settings.google_maps_api_key)
        return draft_plan(context["incident_id"], context, risks, routes).model_dump()
    if name == "create_action_bundle":
        assessment = run_assessment(store, context["incident_id"])
        return {"bundle_id": assessment.bundle_id, "actions": [action.model_dump() for action in assessment.actions]}
    if name == "request_human_approval":
        bundle_id = payload.get("bundle_id")
        approvals = [approval for approval in store.list("approval_requests") if approval["bundle_id"] == bundle_id]
        return approvals[-1] if approvals else {"status": "not_found", "bundle_id": bundle_id}
    if name == "execute_approved_actions":
        return {"status": "use POST /actions/{bundle_id}/execute after approval", "payload": payload}
    return {"error": f"Unknown tool {name}"}
