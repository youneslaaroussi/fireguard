from __future__ import annotations

from typing import Any

from app.services.phoenix import trace_tool_span
from app.services.store import FireGuardStore
from app.services.time import now_iso


def evaluate_incident(store: FireGuardStore, incident_id: str) -> dict[str, Any]:
    plans = [plan for plan in store.list("plans") if plan["incident_id"] == incident_id]
    traces = [trace for trace in store.list("traces") if trace["incident_id"] == incident_id]
    actions = store.list("action_logs")
    if not plans:
        return {"status": "not_found", "incident_id": incident_id}

    plan = plans[-1]
    latest_trace = traces[-1] if traces else {"events": []}
    trace_events = latest_trace.get("events", [])
    rejected_text = " ".join(str(item.get("reason", "")) for item in plan.get("rejected_alternatives", []))
    freshness = plan.get("data_freshness", [])

    checks = {
        "grounding": all(step.get("evidence_ids") for step in plan.get("steps", [])),
        "route_safety": "closure" in rejected_text.lower() and "fire-risk" in rejected_text.lower(),
        "freshness_handling": bool(freshness) and all("status" in item for item in freshness),
        "approval_enforcement": bool(actions) and all(action.get("requires_human_approval", True) for action in actions),
        "tool_trace_complete": {"get_incident_context", "compute_zone_risk", "compute_routes", "draft_evacuation_plan"}.issubset({event.get("tool") for event in trace_events}),
        "clarity": len(plan.get("summary", "")) > 80 and bool(plan.get("fallback_plan")),
    }
    score = round(sum(1 for passed in checks.values() if passed) / len(checks), 2)
    eval_id = f"EVAL_{incident_id}_{now_iso()}"
    result = {
        "eval_id": eval_id,
        "incident_id": incident_id,
        "score": score,
        "checks": checks,
        "status": "pass" if score >= 0.84 else "needs_review",
        "created_at": now_iso(),
    }
    phoenix_trace_id = trace_tool_span(
        store.settings,
        incident_id,
        eval_id,
        "evaluate",
        "arize_phoenix_eval",
        {"incident_id": incident_id},
        result,
        [],
    )
    if phoenix_trace_id:
        result["phoenix_trace_id"] = phoenix_trace_id
    store.upsert("evals", eval_id, result)
    return result
