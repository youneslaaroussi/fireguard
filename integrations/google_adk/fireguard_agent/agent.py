from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import (
    McpToolset,
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from google.adk.tools.openapi_tool.openapi_spec_parser.openapi_toolset import OpenAPIToolset
from mcp import StdioServerParameters

AGENT_DIR = Path(__file__).resolve().parent
load_dotenv(AGENT_DIR / ".env")

model_location = os.environ.get("FIREGUARD_AGENT_MODEL_LOCATION")
if model_location:
    os.environ["GOOGLE_CLOUD_LOCATION"] = model_location

SYSTEM_INSTRUCTION = """You are FireGuard, an emergency evacuation coordination agent.
Synthesize wildfire, road, weather, shelter, and evacuation-zone data into safe,
staged action plans. Never claim certainty beyond the data. Always consider
whether evacuation is safer than sheltering in place. Do not execute
public-facing or dispatch actions without explicit human approval. Include
evidence, confidence, assumptions, data freshness, rejected alternatives, and
fallback actions.

For lightweight verification requests, call only the tool the user asks for and return a
concise response. For full incident assessments, use this workflow:
1. If Elastic MCP tools are available, call elastic_mcp_list_indices or elastic_mcp_search
   to prove partner MCP access to operational memory.
2. Call get_incident_context.
3. Call search_operational_memory for closure, fire, shelter, and approval evidence.
4. Call compute_zone_risk.
5. Call compute_routes and inspect rejected unsafe routes.
6. Call draft_evacuation_plan.
7. Call create_action_bundle.
8. Call request_human_approval.
9. Only call execute_approved_actions if the user explicitly says the bundle is approved.

Return concise JSON-compatible summaries with evidence IDs, data freshness, confidence,
human approval state, and fallback plan. Do not claim official emergency authority."""


def _load_toolset() -> OpenAPIToolset:
    spec = json.loads((AGENT_DIR / "tools.openapi.json").read_text())
    base_url = os.environ.get(
        "FIREGUARD_API_BASE_URL",
        "https://fireguard-api-dovhkdlznq-uc.a.run.app",
    ).rstrip("/")
    spec["servers"] = [{"url": base_url}]
    return OpenAPIToolset(spec_dict=spec)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _split_args(value: str) -> list[str]:
    return shlex.split(value) if value.strip() else []


def _build_google_id_token_header_provider(mcp_url: str):
    def header_provider(_readonly_context: Any) -> dict[str, str]:
        import os
        from urllib.parse import urlsplit

        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        explicit_token = os.environ.get("FIREGUARD_ELASTIC_MCP_ID_TOKEN", "").strip()
        if explicit_token:
            return {"X-Serverless-Authorization": f"Bearer {explicit_token}"}

        audience = os.environ.get("FIREGUARD_ELASTIC_MCP_ID_TOKEN_AUDIENCE", "").strip()
        if not audience:
            parts = urlsplit(mcp_url)
            audience = (
                f"{parts.scheme}://{parts.netloc}"
                if parts.scheme and parts.netloc
                else mcp_url
            )
        token = id_token.fetch_id_token(Request(), audience)
        # Elastic MCP forwards ordinary Authorization headers to Elasticsearch for
        # per-request auth. Cloud Run accepts X-Serverless-Authorization for IAM
        # while leaving Elasticsearch auth to the MCP server's configured API key.
        return {"X-Serverless-Authorization": f"Bearer {token}"}

    return header_provider


def _load_elastic_mcp_toolset() -> McpToolset | None:
    """Load Elastic MCP as an ADK toolset when configured.

    FireGuard supports two MCP transports:
    - Streamable HTTP, preferred for managed Agent Engine if an Elastic MCP Cloud Run
      service is deployed and `FIREGUARD_ELASTIC_MCP_URL` is set.
    - Local stdio via the official Elastic MCP package/container for local ADK runs.

    Missing MCP configuration is allowed by default so local ADK development still
    works without Elasticsearch credentials. Set `FIREGUARD_ELASTIC_MCP_REQUIRED=true`
    in verification/deployment environments to fail closed.
    """
    mcp_url = os.environ.get("FIREGUARD_ELASTIC_MCP_URL", "").strip()
    required = _env_truthy("FIREGUARD_ELASTIC_MCP_REQUIRED")
    enabled = _env_truthy("FIREGUARD_ELASTIC_MCP_ENABLED") or bool(mcp_url) or required
    if not enabled:
        return None

    tool_filter = _split_args(
        os.environ.get(
            "FIREGUARD_ELASTIC_MCP_TOOLS",
            "list_indices get_mappings search get_shards esql",
        )
    )

    if mcp_url:
        header_provider = None
        if (
            os.environ.get("FIREGUARD_ELASTIC_MCP_AUTH", "").strip().lower()
            == "google_id_token"
        ):
            header_provider = _build_google_id_token_header_provider(mcp_url)
        return McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=mcp_url,
                timeout=float(os.environ.get("FIREGUARD_ELASTIC_MCP_TIMEOUT_SECONDS", "10")),
                sse_read_timeout=float(
                    os.environ.get("FIREGUARD_ELASTIC_MCP_READ_TIMEOUT_SECONDS", "60")
                ),
            ),
            tool_filter=tool_filter,
            tool_name_prefix="elastic_mcp",
            header_provider=header_provider,
        )

    es_url = os.environ.get("ELASTICSEARCH_URL", "").strip()
    es_api_key = os.environ.get("ELASTICSEARCH_API_KEY", "").strip()
    if not (es_url and es_api_key):
        if required:
            raise RuntimeError(
                "Elastic MCP is required but ELASTICSEARCH_URL and "
                "ELASTICSEARCH_API_KEY are not configured."
            )
        return None

    command = os.environ.get("FIREGUARD_ELASTIC_MCP_COMMAND", "npx")
    default_args = "-y @elastic/mcp-server-elasticsearch"
    args = _split_args(os.environ.get("FIREGUARD_ELASTIC_MCP_ARGS", default_args))
    env = {
        "ES_URL": es_url,
        "ES_API_KEY": es_api_key,
        "OTEL_LOG_LEVEL": os.environ.get("OTEL_LOG_LEVEL", "none"),
    }
    if os.environ.get("ES_VERSION"):
        env["ES_VERSION"] = os.environ["ES_VERSION"]

    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=command,
                args=args,
                env=env,
            ),
            timeout=float(os.environ.get("FIREGUARD_ELASTIC_MCP_TIMEOUT_SECONDS", "15")),
        ),
        tool_filter=tool_filter,
        tool_name_prefix="elastic_mcp",
    )


def _load_agent_tools() -> list[object]:
    tools: list[object] = [_load_toolset()]
    elastic_mcp = _load_elastic_mcp_toolset()
    if elastic_mcp is not None:
        tools.append(elastic_mcp)
    return tools


root_agent = LlmAgent(
    name="fireguard_evacuation_coordinator",
    model=os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview"),
    description=(
        "Coordinates wildfire evacuation planning through FireGuard OpenAPI tools "
        "and Elastic MCP operational memory."
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=_load_agent_tools(),
)
