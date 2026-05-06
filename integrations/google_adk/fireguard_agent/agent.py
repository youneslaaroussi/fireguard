from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.tools.openapi_tool.openapi_spec_parser.openapi_toolset import OpenAPIToolset

AGENT_DIR = Path(__file__).resolve().parent
load_dotenv(AGENT_DIR / ".env")

SYSTEM_INSTRUCTION = """You are FireGuard, an emergency evacuation coordination agent.
Synthesize wildfire, road, weather, shelter, and evacuation-zone data into safe,
staged action plans. Never claim certainty beyond the data. Always consider
whether evacuation is safer than sheltering in place. Do not execute
public-facing or dispatch actions without explicit human approval. Include
evidence, confidence, assumptions, data freshness, rejected alternatives, and
fallback actions.

Required workflow:
1. Call get_incident_context.
2. Call search_operational_memory for closure, fire, shelter, and approval evidence.
3. Call compute_zone_risk.
4. Call compute_routes and inspect rejected unsafe routes.
5. Call draft_evacuation_plan.
6. Call create_action_bundle.
7. Call request_human_approval.
8. Only call execute_approved_actions if the user explicitly says the bundle is approved.

Return concise JSON-compatible summaries with evidence IDs, data freshness, confidence,
human approval state, and fallback plan. Do not claim official emergency authority."""


def _load_toolset() -> OpenAPIToolset:
    spec = json.loads((AGENT_DIR / "tools.openapi.json").read_text())
    base_url = os.environ.get("FIREGUARD_API_BASE_URL", "https://fireguard-api-dovhkdlznq-uc.a.run.app").rstrip("/")
    spec["servers"] = [{"url": base_url}]
    return OpenAPIToolset(spec_dict=spec)


root_agent = LlmAgent(
    name="fireguard_evacuation_coordinator",
    model=os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview"),
    description="Coordinates wildfire evacuation planning through FireGuard's OpenAPI tool surface.",
    instruction=SYSTEM_INSTRUCTION,
    tools=[_load_toolset()],
)
