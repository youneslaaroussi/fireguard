from __future__ import annotations

import json
from typing import Any

from app.config import Settings
from app.models.schemas import ActionItem, EvacuationPlan

SYSTEM_INSTRUCTION = """You are FireGuard, an emergency evacuation coordination agent.
Synthesize wildfire, road, weather, shelter, and evacuation-zone data into safe,
staged action plans. Never claim certainty beyond the data. Always consider
whether evacuation is safer than sheltering in place. Do not execute
public-facing or dispatch actions without explicit human approval. Include
evidence, confidence, assumptions, data freshness, rejected alternatives, and
fallback actions."""

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


def agent_manifest(settings: Settings) -> dict:
    return {
        "name": "FireGuard Evacuation Coordinator",
        "model": settings.gemini_model,
        "google_cloud_project_required": not bool(settings.google_cloud_project),
        "system_instruction": SYSTEM_INSTRUCTION,
        "developer_instruction": DEVELOPER_INSTRUCTION,
        "tool_endpoints": TOOL_ENDPOINTS,
        "openapi_url": "/openapi.json",
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
            "requires": ["ELASTICSEARCH_URL", "ELASTICSEARCH_API_KEY"],
            "purpose": "Partner-track MCP integration for listing indices, inspecting mappings, and running search over FireGuard operational memory.",
        },
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
            "fires": context["fires"][:3],
            "road_events": context["road_events"][:5],
            "weather": context["weather"],
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
                    "status": shelter["status"],
                }
                for shelter in context["shelters"]
            ],
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
            "road_events": context["road_events"][:3],
            "fire_evidence_ids": [fire["external_id"] for fire in context["fires"][:3]],
        }

    def compute_zone_risk() -> dict[str, Any]:
        """Return deterministic zone risk scores and evidence IDs."""
        tool_calls.append("compute_zone_risk")
        return {"zone_risks": [risk.model_dump() for risk in plan.zone_risks]}

    def compute_routes() -> dict[str, Any]:
        """Return deterministic route options including rejected unsafe routes."""
        tool_calls.append("compute_routes")
        return {"routes": [route.model_dump() for route in plan.routes]}

    def draft_evacuation_plan() -> dict[str, Any]:
        """Return the deterministic staged evacuation plan."""
        tool_calls.append("draft_evacuation_plan")
        return plan.model_dump()

    def create_action_bundle() -> dict[str, Any]:
        """Return the pending action bundle that requires human approval."""
        tool_calls.append("create_action_bundle")
        return {
            "actions": [action.model_dump() for action in actions],
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
        parsed.setdefault("incident_summary", plan.summary)
        parsed.setdefault("recommended_strategy", plan.recommended_strategy)
        parsed.setdefault("route_rejection", plan.rejected_alternatives[0] if plan.rejected_alternatives else None)
        parsed.setdefault("approval_gate", "Human approval required before resident, shelter, road, or dispatch actions execute.")
        parsed.setdefault("confidence", plan.confidence)
        parsed.setdefault("fallback_plan", plan.fallback_plan)
        parsed.setdefault("risks_if_wrong", plan.risks_if_wrong)
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
