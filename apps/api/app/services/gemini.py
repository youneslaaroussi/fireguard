from __future__ import annotations

import json
from typing import Any

from app.config import Settings
from app.models.schemas import ActionItem, EvacuationPlan, GeminiPlanDecision, RouteOption, ZoneRisk

SYSTEM_INSTRUCTION = """You are FireGuard, an emergency evacuation reasoning agent.
Your job is to assess wildfire situations from raw data and make genuine operational
decisions — not to confirm pre-computed answers. Read the actual fire locations,
intensities, wind conditions, road states, and zone demographics. Reason about
whether evacuation is warranted, which zones are most at risk, what the safest
routes are given current conditions, and how to sequence movement to avoid
congestion and casualties. State your confidence honestly. Acknowledge what you
don't know. Every decision must be grounded in specific evidence from the data."""

DEVELOPER_INSTRUCTION = """When assessing an incident:
1. Retrieve operational context from Elastic.
2. Check data freshness for every source.
3. Identify threatened zones.
4. Evaluate route safety and shelter capacity.
5. Consider staged evacuation, shelter-in-place, and dispatch-assisted options.
6. Produce an action bundle.
7. Send the action bundle for human approval.
8. Execute only approved actions."""

TOOL_ENDPOINTS = [
    "/tools/get_incident_context",
    "/tools/search_operational_memory",
    "/tools/compute_zone_risk",
    "/tools/compute_routes",
    "/tools/draft_evacuation_plan",
    "/tools/create_action_bundle",
    "/tools/request_human_approval",
    "/tools/execute_approved_actions",
]

MANAGED_AGENT_ENGINE_RESOURCE = (
    "projects/425727109076/locations/us-central1/"
    "reasoningEngines/9137720630806839296"
)
MANAGED_AGENT_ENGINE_MODEL = "gemini-3.1-flash-lite-preview"
AGENT_BUILDER_ENGINE_RESOURCE = (
    "projects/425727109076/locations/global/collections/default_collection/"
    "engines/fireguard-command-center"
)
AGENT_BUILDER_ASSISTANT_RESOURCE = (
    f"{AGENT_BUILDER_ENGINE_RESOURCE}/assistants/default_assistant"
)
AGENT_BUILDER_AGENT_RESOURCE = (
    f"{AGENT_BUILDER_ASSISTANT_RESOURCE}/agents/7406279429546975436"
)
AGENT_BUILDER_DATA_STORE_RESOURCE = (
    "projects/425727109076/locations/global/collections/default_collection/"
    "dataStores/fireguard-operational-memory"
)


def agent_manifest(settings: Settings) -> dict:
    return {
        "name": "FireGuard Evacuation Coordinator",
        "model": settings.gemini_model,
        "google_cloud_project_required": not bool(settings.google_cloud_project),
        "system_instruction": SYSTEM_INSTRUCTION,
        "developer_instruction": DEVELOPER_INSTRUCTION,
        "tool_endpoints": TOOL_ENDPOINTS,
        "openapi_url": "/openapi.json",
        "google_adk": {
            "agent_path": "integrations/google_adk/fireguard_agent",
            "tool_spec": "integrations/google_adk/fireguard_agent/tools.openapi.json",
            "run_command": "cd integrations/google_adk && adk run fireguard_agent",
            "purpose": "Code-first Google ADK agent with FireGuard OpenAPI tools and Elastic MCP toolset support for local/dev and source-level Agent Builder review.",
        },
        "agent_builder": {
            "managed_agent_engine_resource": MANAGED_AGENT_ENGINE_RESOURCE,
            "managed_agent_engine_runtime": "custom_managed_vertex_agent_engine",
            "managed_agent_engine_model": MANAGED_AGENT_ENGINE_MODEL,
            "gemini_location": "global",
            "registry_engine_resource": AGENT_BUILDER_ENGINE_RESOURCE,
            "registry_assistant_resource": AGENT_BUILDER_ASSISTANT_RESOURCE,
            "registry_agent_resource": AGENT_BUILDER_AGENT_RESOURCE,
            "connected_data_store_resource": AGENT_BUILDER_DATA_STORE_RESOURCE,
            "connected_data_store_documents": 5,
            "registry_features": ["agent-gallery", "no-code-agent-builder", "model-selector"],
            "registry_agent_registration_status": "enabled",
            "verify_command": "cd integrations/google_adk && python verify_agent_engine_mcp.py",
            "proof_file": "docs/proofs/agent_engine_elastic_mcp_2026-05-11.json",
            "registry_proof_file": "docs/proofs/agent_builder_registry_2026-05-11.json",
            "claim": "Managed Vertex AI Agent Engine runtime calls Vertex global Gemini 3.1 and the official Elastic MCP service. A Google Agent Builder/Gemini Enterprise app has a connected FireGuard operational-memory data store and an enabled custom Agent Engine agent created by Discovery Engine API. The verifier fails unless the Gemini 3.1 model version and elastic_mcp_list_indices response are present.",
        },
        "supporting_integrations": {
            "fivetran": {
                "connector_path": "integrations/fivetran/fireguard_connector",
                "sync_endpoint": "/sync/fivetran-to-elastic",
                "purpose": "Production ingestion for FIRMS, BC perimeters, DriveBC/Open511, and Open-Meteo into BigQuery before Elastic indexing.",
            },
            "arize_phoenix": {
                "status_endpoint": "/integrations/arize/status",
                "purpose": "OpenTelemetry trace and eval proof for tool calls, rejected alternatives, approval gates, and action execution.",
            },
        },
        "elastic_mcp": {
            "server": "@elastic/mcp-server-elasticsearch",
            "adk_toolset": "google.adk.tools.mcp_tool.McpToolset",
            "tool_prefix": "elastic_mcp",
            "transports": ["streamable_http", "stdio"],
            "requires": ["ELASTICSEARCH_URL", "ELASTICSEARCH_API_KEY"],
            "purpose": "Partner-track MCP integration for listing indices, inspecting mappings, and running search over FireGuard operational memory. Managed Agent Engine verification called elastic_mcp_list_indices successfully.",
        },
    }


def gemini_status(settings: Settings) -> dict[str, Any]:
    return {
        "configured": bool(settings.google_cloud_project),
        "assessment_enabled": settings.gemini_assessment_enabled,
        "model": settings.gemini_model,
        "location": settings.google_cloud_location,
        "vertexai": settings.google_genai_use_vertexai,
        "role": "plan_selection_and_action_intent",
        "agent_builder": {
            "managed_agent_engine_resource": MANAGED_AGENT_ENGINE_RESOURCE,
            "managed_agent_engine_model": MANAGED_AGENT_ENGINE_MODEL,
            "managed_agent_engine_runtime": "custom_managed_vertex_agent_engine",
            "registry_engine_resource": AGENT_BUILDER_ENGINE_RESOURCE,
            "registry_assistant_resource": AGENT_BUILDER_ASSISTANT_RESOURCE,
            "registry_agent_resource": AGENT_BUILDER_AGENT_RESOURCE,
            "connected_data_store_resource": AGENT_BUILDER_DATA_STORE_RESOURCE,
            "connected_data_store_documents": 5,
            "registry_agent_registration_status": "enabled",
            "elastic_mcp_verified": True,
        },
    }


def build_operational_brief(
    incident_id: str,
    context: dict[str, Any],
    zone_risks: list[ZoneRisk],
    routes: list[RouteOption],
    memory_hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    risk_by_zone = {risk.zone_id: risk for risk in zone_risks}
    evidence_ids = sorted({
        *[str(fire.get("external_id")) for fire in context.get("fires", []) if fire.get("external_id")],
        *[str(event.get("external_id")) for event in context.get("road_events", []) if event.get("external_id")],
        *[str(shelter.get("source_record_id")) for shelter in context.get("shelters", []) if shelter.get("source_record_id")],
        *[evidence_id for risk in zone_risks for evidence_id in risk.evidence_ids],
        *[evidence_id for route in routes for evidence_id in route.evidence_ids],
    })
    return {
        "incident_id": incident_id,
        "mode": context.get("mode"),
        "store_backend": context.get("store_backend"),
        "zones": [
            {
                "zone_id": zone["zone_id"],
                "name": zone["name"],
                "population": zone.get("population"),
                "vulnerable_count": zone.get("vulnerable_count"),
                "vehicle_access_score": zone.get("vehicle_access_score"),
                "risk": risk_by_zone.get(zone["zone_id"]).model_dump() if risk_by_zone.get(zone["zone_id"]) else None,
            }
            for zone in context.get("zones", [])
        ],
        "shelters": [
            {
                "shelter_id": shelter["shelter_id"],
                "name": shelter["name"],
                "status": shelter.get("status"),
                "official_facility_status": shelter.get("official_facility_status"),
                "capacity_available": shelter.get("capacity_available"),
                "capacity_total": shelter.get("capacity_total"),
                "capacity_operator_confirmed": shelter.get("capacity_operator_confirmed", False),
                "capacity_source_label": shelter.get("capacity_source_label"),
                "source_record_id": shelter.get("source_record_id"),
            }
            for shelter in context.get("shelters", [])
        ],
        "fires": [_fire_for_llm(fire) for fire in context.get("fires", [])[:5]],
        "road_events": [_road_event_for_llm(event) for event in context.get("road_events", [])[:6]],
        "weather": _weather_for_llm(context.get("weather", {})),
        "route_options": [_route_for_llm(route) for route in routes],
        "operational_assumptions": context.get("operational_assumptions", [])[:10],
        "data_freshness": context.get("data_freshness", []),
        "available_evidence_ids": evidence_ids[:80],
        "memory_hits": [
            {
                "index": hit.get("_index"),
                "id": hit.get("_id"),
                "score": hit.get("_score"),
                "source": hit.get("_source", hit.get("source")),
            }
            for hit in (memory_hits or [])[:8]
        ],
    }


def candidate_facts_summary(brief: dict[str, Any]) -> dict[str, Any]:
    routes = brief.get("route_options", [])
    return {
        "zone_count": len(brief.get("zones", [])),
        "fire_count": len(brief.get("fires", [])),
        "route_count": len(routes),
        "flagged_route_count": sum(1 for r in routes if r.get("risk_flags")),
        "shelter_count": len(brief.get("shelters", [])),
        "evidence_count": len(brief.get("available_evidence_ids", [])),
        "zone_risk_levels": {
            z["zone_id"]: z["risk"]["risk_level"]
            for z in brief.get("zones", [])
            if z.get("risk")
        },
    }


def run_gemini_plan_decision(
    settings: Settings,
    incident_id: str,
    operational_brief: dict[str, Any],
    repair_errors: list[str] | None = None,
    previous_decision: dict[str, Any] | None = None,
    commander_context: str | None = None,
) -> dict[str, Any]:
    if not settings.gemini_assessment_enabled:
        return {"status": "skipped", "reason": "GEMINI_ASSESSMENT_ENABLED is false", "tool_calls": []}
    if not settings.google_cloud_project:
        return {"status": "skipped", "reason": "GOOGLE_CLOUD_PROJECT is not configured", "tool_calls": []}

    tool_calls: list[str] = []

    def get_operational_brief() -> dict[str, Any]:
        """Return the full FireGuard operational brief: risks, routes, sources, constraints, and allowed actions."""
        tool_calls.append("get_operational_brief")
        return operational_brief

    def inspect_route_options() -> dict[str, Any]:
        """Return all route options with risk flags for every zone-shelter pair."""
        tool_calls.append("inspect_route_options")
        return {"routes": operational_brief.get("route_options", [])}

    def search_operational_memory(query: str) -> dict[str, Any]:
        """Search the compact evidence bundle in operational memory."""
        tool_calls.append("search_operational_memory")
        terms = query.lower().split()
        text_hits = [
            hit
            for hit in operational_brief.get("memory_hits", [])
            if any(term in json.dumps(hit).lower() for term in terms)
        ]
        return {
            "query": query,
            "hits": text_hits[:6],
            "road_events": operational_brief.get("road_events", [])[:4],
            "available_evidence_ids": operational_brief.get("available_evidence_ids", [])[:30],
        }

    repair_clause = ""
    if repair_errors:
        repair_clause = f"""
This is a repair attempt. Your previous output failed backend validation.
Validation errors:
{json.dumps(repair_errors, indent=2)}

Previous decision:
{json.dumps(previous_decision or {}, indent=2)[:4000]}

Return a corrected decision that satisfies every backend validator rule.
"""

    schema_hint = {
        "incident_summary": "2-sentence assessment of current situation and your recommended response",
        "selected_strategy": "monitor | evacuate_now | staged_evacuation | shelter_in_place | dispatch_assisted",
        "confidence": 0.0,
        "steps": [{
            "zone_id": "zone identifier from the brief",
            "strategy": "your chosen strategy for this zone",
            "destination_id": "shelter ID if evacuating, else null",
            "start_after_minutes": 0,
            "message": "concise resident or operator instruction",
            "rationale": ["specific data-backed reason for this decision"],
            "evidence_ids": ["IDs of sources that support this step"],
            "assumption_ids": [],
        }],
        "rejected_alternatives": [{
            "origin_id": "zone ID",
            "destination_id": "shelter ID or null",
            "reason": "specific reason this option was rejected",
            "evidence_ids": ["supporting source IDs"],
        }],
        "requested_actions": [{
            "action_type": "resident_sms | shelter_notify | road_ops_task | dispatch_task | incident_timeline_update",
            "target": "zone ID, shelter ID, or road segment",
            "message": "specific action instruction",
            "reason": "why this action is needed",
            "evidence_ids": ["supporting source IDs"],
            "assumption_ids": [],
            "payload": {},
        }],
        "data_gaps": ["specific missing or stale data that affects your confidence"],
        "risks_if_wrong": ["specific operational consequence if this assessment is incorrect"],
        "fallback_plan": "what to do if conditions change or this plan becomes unsafe",
    }

    try:
        from google import genai
        from google.genai import types
        from google.oauth2 import service_account

        credentials = None
        if settings.google_application_credentials:
            credentials = service_account.Credentials.from_service_account_file(
                settings.google_application_credentials,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )

        client = genai.Client(
            vertexai=settings.google_genai_use_vertexai,
            credentials=credentials,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            http_options=types.HttpOptions(api_version="v1", timeout=30000),
        )
        commander_clause = ""
        if commander_context:
            commander_clause = f"""
Commander-issued context and overrides for this incident:
{commander_context}

Give this commander context priority when making decisions.
"""

        prompt = f"""
Assess wildfire incident {incident_id} from first principles.

Call get_operational_brief to retrieve fire, weather, route, shelter, and zone data.
Use search_operational_memory if you need policy or prior-incident context.

Then reason through the situation:
- How close and intense are the active fires relative to each zone? Consider FRP,
  confidence, and the wind direction and speed that drives spread.
- Do current conditions pose an imminent threat to residents, or is the risk still
  within a monitor threshold?
- If action is warranted: which zones need to move first and why? What is the safest
  routing given the road events and route risk flags?
- What sequencing and timing prevents corridor congestion?
- What actions are needed — resident notifications, shelter preparation, road ops,
  dispatch support? Justify each one with specific evidence.
- What are you uncertain about? What data is missing or stale?

Note: resident SMS actions must target zone IDs, not phone numbers. Do not claim
dispatch vehicles are assigned — only request assignment. All public actions require
human approval before execution; you are composing the request, not executing it.
{commander_clause}
Return compact valid JSON only, no markdown:
{json.dumps(schema_hint, indent=2)}

One step per affected zone. At most five rejected alternatives. At most eight requested
actions. One sentence per message, rationale item, risk, and fallback.
{repair_clause}
"""
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                systemInstruction=f"{SYSTEM_INSTRUCTION}\n\n{DEVELOPER_INSTRUCTION}",
                tools=[
                    get_operational_brief,
                    inspect_route_options,
                    search_operational_memory,
                ],
                temperature=0.45,
                maxOutputTokens=6000,
            ),
        )
        parsed = _parse_json_response(response.text or "{}")
        try:
            decision = GeminiPlanDecision.model_validate(parsed)
        except Exception as exc:
            return {
                "status": "invalid",
                "model": settings.gemini_model,
                "tool_calls": tool_calls,
                "validation_errors": [str(exc)],
                "raw_decision": parsed,
            }
        return {
            "status": "completed",
            "model": settings.gemini_model,
            "tool_calls": tool_calls,
            "decision": decision.model_dump(),
        }
    except Exception as exc:  # pragma: no cover - depends on Vertex model access
        return {
            "status": "failed",
            "model": settings.gemini_model,
            "tool_calls": tool_calls,
            "error": str(exc),
        }


def run_gemini_tool_assessment(
    settings: Settings,
    incident_id: str,
    context: dict[str, Any],
    plan: EvacuationPlan,
    actions: list[ActionItem],
) -> dict[str, Any]:
    if not settings.gemini_assessment_enabled:
        return {"status": "skipped", "reason": "GEMINI_ASSESSMENT_ENABLED is false"}
    if not settings.google_cloud_project:
        return {"status": "skipped", "reason": "GOOGLE_CLOUD_PROJECT is not configured"}

    tool_calls: list[str] = []

    def get_incident_context() -> dict[str, Any]:
        """Return the current FireGuard incident context from Elastic-backed memory."""
        tool_calls.append("get_incident_context")
        return {
            "incident_id": context["incident_id"],
            "fires": [_fire_for_llm(fire) for fire in context["fires"][:3]],
            "road_events": [_road_event_for_llm(event) for event in context["road_events"][:5]],
            "weather": _weather_for_llm(context["weather"]),
            "zones": [
                {
                    "zone_id": zone["zone_id"],
                    "name": zone["name"],
                    "population": zone["population"],
                    "vulnerable_count": zone["vulnerable_count"],
                }
                for zone in context["zones"]
            ],
            "shelters": [
                {
                    "shelter_id": shelter["shelter_id"],
                    "name": shelter["name"],
                    "capacity_available": shelter["capacity_available"],
                    "capacity_is_operator_assumption": shelter.get("capacity_is_operator_assumption"),
                    "capacity_source_label": shelter.get("capacity_source_label"),
                    "official_facility_status": shelter.get("official_facility_status"),
                    "source_record_id": shelter.get("source_record_id"),
                    "status": shelter["status"],
                }
                for shelter in context["shelters"]
            ],
            "operational_assumptions": context.get("operational_assumptions", [])[:8],
            "data_freshness": context["data_freshness"],
        }

    def search_operational_memory(query: str) -> dict[str, Any]:
        """Search operational memory for policy and incident evidence."""
        tool_calls.append("search_operational_memory")
        terms = query.lower().split()
        policies = [
            policy
            for policy in context.get("policies", [])
            if any(term in json.dumps(policy).lower() for term in terms)
        ]
        return {
            "query": query,
            "hits": policies[:4],
            "road_events": [_road_event_for_llm(event) for event in context["road_events"][:3]],
            "fire_evidence_ids": [fire["external_id"] for fire in context["fires"][:3]],
        }

    def compute_zone_risk() -> dict[str, Any]:
        """Return deterministic zone risk scores and evidence IDs."""
        tool_calls.append("compute_zone_risk")
        return {"zone_risks": [risk.model_dump() for risk in plan.zone_risks]}

    def compute_routes() -> dict[str, Any]:
        """Return route options including rejected unsafe routes without map polylines."""
        tool_calls.append("compute_routes")
        return {"routes": [_route_for_llm(route) for route in plan.routes]}

    def draft_evacuation_plan() -> dict[str, Any]:
        """Return the staged evacuation plan without map geometry payloads."""
        tool_calls.append("draft_evacuation_plan")
        return _plan_for_llm(plan)

    def create_action_bundle() -> dict[str, Any]:
        """Return the pending action bundle that requires human approval."""
        tool_calls.append("create_action_bundle")
        return {
            "actions": [_action_for_llm(action) for action in actions],
            "requires_approval": any(action.requires_human_approval for action in actions),
        }

    try:
        from google import genai
        from google.genai import types
        from google.oauth2 import service_account

        credentials = None
        if settings.google_application_credentials:
            credentials = service_account.Credentials.from_service_account_file(
                settings.google_application_credentials,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )

        client = genai.Client(
            vertexai=settings.google_genai_use_vertexai,
            credentials=credentials,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            http_options=types.HttpOptions(api_version="v1", timeout=30000),
        )
        prompt = f"""
Assess FireGuard incident {incident_id}. You must use the provided tools before
answering. First call get_incident_context. Then call search_operational_memory
with the query "unsafe route closure shelter in place approval". Then call the
risk, route, plan, and action-bundle tools. Return compact valid JSON only,
with no markdown fences, using these keys:
incident_summary, recommended_strategy, route_rejection, approval_gate,
confidence, rationale, fallback_plan, risks_if_wrong.

Your review must respect this policy: do not execute or imply execution of
resident, shelter, road, or dispatch actions without human approval.
"""
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                systemInstruction=f"{SYSTEM_INSTRUCTION}\n\n{DEVELOPER_INSTRUCTION}",
                tools=[
                    get_incident_context,
                    search_operational_memory,
                    compute_zone_risk,
                    compute_routes,
                    draft_evacuation_plan,
                    create_action_bundle,
                ],
                temperature=0.2,
                maxOutputTokens=1200,
            ),
        )
        parsed = _parse_json_response(response.text or "{}")
        return {
            "status": "completed",
            "model": settings.gemini_model,
            "tool_calls": tool_calls,
            **parsed,
        }
    except Exception as exc:  # pragma: no cover - depends on Vertex model access
        return {
            "status": "failed",
            "model": settings.gemini_model,
            "tool_calls": tool_calls,
            "error": str(exc),
        }


def _parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
                return parsed if isinstance(parsed, dict) else {"raw": parsed}
            except json.JSONDecodeError:
                pass
    return {"raw": text}


def _fire_for_llm(fire: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_id": fire.get("external_id"),
        "source": fire.get("source"),
        "location": fire.get("location"),
        "confidence": fire.get("confidence"),
        "frp": fire.get("frp"),
        "acquired_at": fire.get("acquired_at"),
        "ingested_at": fire.get("ingested_at"),
    }


def _road_event_for_llm(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_id": event.get("external_id"),
        "source": event.get("source"),
        "title": event.get("title"),
        "event_type": event.get("event_type"),
        "severity": event.get("severity"),
        "road_name": event.get("road_name"),
        "location": event.get("location"),
        "updated_at": event.get("updated_at"),
        "description": str(event.get("description") or "")[:280],
    }


def _weather_for_llm(weather: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": weather.get("source"),
        "weather_id": weather.get("weather_id"),
        "wind_speed_kph": weather.get("wind_speed_kph"),
        "wind_direction_degrees": weather.get("wind_direction_degrees"),
        "gust_kph": weather.get("gust_kph"),
        "updated_at": weather.get("updated_at"),
    }


def _route_for_llm(route: RouteOption) -> dict[str, Any]:
    return {
        "origin_id": route.origin_id,
        "destination_id": route.destination_id,
        "duration_minutes": route.duration_minutes,
        "distance_km": route.distance_km,
        "safe": route.safe,
        "risk_flags": route.risk_flags[:8],
        "evidence_ids": route.evidence_ids[:10],
        "assumption_ids": route.assumption_ids[:10],
        "route_source": route.route_source,
        "provider_error": route.provider_error,
        "polyline_point_count": len(route.polyline),
    }


def _plan_for_llm(plan: EvacuationPlan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "incident_id": plan.incident_id,
        "summary": plan.summary,
        "recommended_strategy": plan.recommended_strategy,
        "confidence": plan.confidence,
        "zone_risks": [risk.model_dump() for risk in plan.zone_risks],
        "routes": [_route_for_llm(route) for route in plan.routes],
        "steps": [step.model_dump() for step in plan.steps],
        "rejected_alternatives": plan.rejected_alternatives[:8],
        "operational_assumptions": plan.operational_assumptions[:8],
        "data_freshness": plan.data_freshness,
        "risks_if_wrong": plan.risks_if_wrong,
        "fallback_plan": plan.fallback_plan,
        "requires_approval": plan.requires_approval,
    }


def _action_for_llm(action: ActionItem) -> dict[str, Any]:
    return {
        "action_id": action.action_id,
        "action_type": action.action_type,
        "target": action.target,
        "status": action.status,
        "message": action.message,
        "reason": action.reason,
        "evidence_ids": action.evidence_ids[:10],
        "assumption_ids": action.assumption_ids[:10],
        "confidence": action.confidence,
        "external_system": action.external_system,
        "is_simulated_endpoint": action.is_simulated_endpoint,
        "requires_human_approval": action.requires_human_approval,
    }
