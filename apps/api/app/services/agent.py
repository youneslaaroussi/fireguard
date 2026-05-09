from __future__ import annotations

from typing import Any

from app.models.schemas import AssessmentResult, GeminiPlanDecision, PlanValidation
from app.services import demo_data
from app.services.evals import evaluate_incident
from app.services import gemini
from app.services.planner import create_bundle, draft_plan, plan_from_gemini_decision, validate_gemini_plan_decision
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

    operational_brief = gemini.build_operational_brief(incident_id, context, zone_risks, routes, memory_hits)
    candidate_facts_summary = gemini.candidate_facts_summary(operational_brief)
    trace.add(
        "brief",
        "operational_brief",
        {"incident_id": incident_id},
        candidate_facts_summary,
        operational_brief.get("available_evidence_ids", [])[:12],
    )

    gemini_result = gemini.run_gemini_plan_decision(store.settings, incident_id, operational_brief)
    gemini_tool_calls = list(gemini_result.get("tool_calls", []))
    trace.add(
        "reason",
        "gemini_plan_decision",
        {"incident_id": incident_id, "model": store.settings.gemini_model},
        gemini_result,
        gemini_tool_calls,
    )

    planning_mode = "deterministic_fallback"
    gemini_decision: dict[str, Any] | None = None
    plan_validation = _validation_for_unavailable_gemini(gemini_result)
    validation_errors = list(plan_validation.errors)
    repair_result: dict[str, Any] | None = None

    if gemini_result.get("status") == "completed" and gemini_result.get("decision"):
        decision = GeminiPlanDecision.model_validate(gemini_result["decision"])
        plan_validation = validate_gemini_plan_decision(decision, context, zone_risks, routes)
        validation_errors = list(plan_validation.errors)
        gemini_decision = decision.model_dump()
        trace.add(
            "validate",
            "plan_validation",
            {"incident_id": incident_id, "source": "gemini_initial"},
            plan_validation.model_dump(),
            [evidence_id for step in decision.steps for evidence_id in step.evidence_ids],
        )
        if not plan_validation.valid:
            repair_result = gemini.run_gemini_plan_decision(
                store.settings,
                incident_id,
                operational_brief,
                repair_errors=plan_validation.errors,
                previous_decision=gemini_decision,
            )
            gemini_tool_calls.extend(repair_result.get("tool_calls", []))
            trace.add(
                "repair",
                "gemini_repair",
                {"incident_id": incident_id, "model": store.settings.gemini_model},
                repair_result,
                repair_result.get("tool_calls", []),
            )
            if repair_result.get("status") == "completed" and repair_result.get("decision"):
                repaired_decision = GeminiPlanDecision.model_validate(repair_result["decision"])
                repaired_validation = validate_gemini_plan_decision(
                    repaired_decision,
                    context,
                    zone_risks,
                    routes,
                    repair_attempted=True,
                )
                trace.add(
                    "validate",
                    "plan_validation",
                    {"incident_id": incident_id, "source": "gemini_repair"},
                    repaired_validation.model_dump(),
                    [evidence_id for step in repaired_decision.steps for evidence_id in step.evidence_ids],
                )
                plan_validation = repaired_validation
                validation_errors = list(repaired_validation.errors)
                if repaired_validation.valid:
                    decision = repaired_decision
                    gemini_decision = repaired_decision.model_dump()
                    planning_mode = "gemini_repaired"
        if plan_validation.valid and planning_mode != "gemini_repaired":
            planning_mode = "gemini_selected"
    elif gemini_result.get("status") == "invalid":
        repair_result = gemini.run_gemini_plan_decision(
            store.settings,
            incident_id,
            operational_brief,
            repair_errors=gemini_result.get("validation_errors", ["Gemini returned malformed plan JSON."]),
            previous_decision=gemini_result.get("raw_decision"),
        )
        gemini_tool_calls.extend(repair_result.get("tool_calls", []))
        trace.add(
            "repair",
            "gemini_repair",
            {"incident_id": incident_id, "model": store.settings.gemini_model},
            repair_result,
            repair_result.get("tool_calls", []),
        )
        if repair_result.get("status") == "completed" and repair_result.get("decision"):
            repaired_decision = GeminiPlanDecision.model_validate(repair_result["decision"])
            plan_validation = validate_gemini_plan_decision(
                repaired_decision,
                context,
                zone_risks,
                routes,
                repair_attempted=True,
            )
            validation_errors = list(plan_validation.errors)
            gemini_decision = repaired_decision.model_dump()
            trace.add(
                "validate",
                "plan_validation",
                {"incident_id": incident_id, "source": "gemini_repair"},
                plan_validation.model_dump(),
                [evidence_id for step in repaired_decision.steps for evidence_id in step.evidence_ids],
            )
            if plan_validation.valid:
                planning_mode = "gemini_repaired"

    trace.add(
        "validate",
        "plan_validation",
        {"incident_id": incident_id, "source": "final", "planning_mode": planning_mode},
        plan_validation.model_dump(),
        [
            evidence_id
            for step in (gemini_decision or {}).get("steps", [])
            for evidence_id in step.get("evidence_ids", [])
        ],
    )

    if plan_validation.valid and gemini_decision:
        decision = GeminiPlanDecision.model_validate(gemini_decision)
        plan = plan_from_gemini_decision(incident_id, context, zone_risks, routes, decision)
    else:
        plan = draft_plan(incident_id, context, zone_risks, routes)
        if not validation_errors:
            validation_errors = ["Gemini did not return a valid plan decision; deterministic fallback was used."]

    trace.add(
        "plan",
        "draft_evacuation_plan",
        {"incident_id": incident_id, "planning_mode": planning_mode},
        {"planning_mode": planning_mode, "plan": plan.model_dump()},
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
    trace.add(
        "compile",
        "action_bundle_compile",
        {"bundle_id": bundle_id, "planning_mode": planning_mode},
        {
            "action_count": len(actions),
            "requested_action_count": len(plan.requested_actions),
            "approval_status": approval.status,
        },
        [evidence_id for action in actions for evidence_id in action.evidence_ids],
        action_assumption_ids,
    )

    agent_review = {
        "status": gemini_result.get("status"),
        "model": gemini_result.get("model"),
        "planning_mode": planning_mode,
        "tool_calls": gemini_tool_calls,
        "decision": gemini_decision,
        "repair": repair_result,
        "validation": plan_validation.model_dump(),
    }

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
        gemini_tool_calls=gemini_tool_calls,
        planning_mode=planning_mode,  # type: ignore[arg-type]
        gemini_decision=gemini_decision,
        plan_validation=plan_validation.model_dump(),
        validation_errors=validation_errors,
        candidate_facts_summary=candidate_facts_summary,
        phoenix_trace_ids=trace.phoenix_trace_ids,
        arize_ax_trace_ids=trace.arize_ax_trace_ids,
    )


def _validation_for_unavailable_gemini(gemini_result: dict[str, Any]) -> PlanValidation:
    status = gemini_result.get("status", "unknown")
    if status == "completed":
        return PlanValidation(valid=False, errors=["Gemini completed without a valid decision payload."])
    reason = gemini_result.get("reason") or gemini_result.get("error") or "; ".join(gemini_result.get("validation_errors", []))
    return PlanValidation(
        valid=False,
        errors=[f"Gemini planning unavailable: {status}{f' - {reason}' if reason else ''}"],
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
        assessment = run_assessment(store, context["incident_id"])
        return {
            "planning_mode": assessment.planning_mode,
            "plan_validation": assessment.plan_validation,
            **assessment.plan.model_dump(),
        }
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
