# FireGuard Google ADK Agent

This directory is the code-first Google Agent Development Kit entrypoint and managed Vertex AI Agent Engine proof runtime for FireGuard.

The hosted FastAPI backend remains the safety and execution layer. The ADK agent uses the backend OpenAPI tool surface to observe context, compute deterministic risk/routes, draft a plan, request approval, and execute only approved actions.

`fireguard_managed_agent.py` is the managed Agent Engine proof runtime. It exists because the standard regional ADK `LlmAgent` resolver only exposes Gemini 2.x models in this project's `us-central1` Agent Engine region. The managed proof runtime still runs inside Vertex AI Agent Engine, but explicitly calls Vertex global Gemini 3.1 and Elastic MCP from there.

The agent also supports the official Elastic MCP server as a first-class ADK `McpToolset`. When configured, Elastic MCP tools are exposed with the `elastic_mcp_*` prefix and are called before the backend `search_operational_memory` tool so partner MCP access is visible in traces.

## Run Locally

```bash
cd integrations/google_adk
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp fireguard_agent/.env.example fireguard_agent/.env
```

Edit `fireguard_agent/.env` if needed, then run:

```bash
adk run fireguard_agent
```

For Elastic MCP verification, configure one transport:

```bash
# Local stdio MCP.
FIREGUARD_ELASTIC_MCP_ENABLED=true
ELASTICSEARCH_URL=http://127.0.0.1:9200
ELASTICSEARCH_API_KEY=...

# Or managed streamable HTTP MCP.
FIREGUARD_ELASTIC_MCP_URL=https://fireguard-elastic-mcp-...run.app/mcp
FIREGUARD_ELASTIC_MCP_AUTH=google_id_token
```

Then run:

```bash
python verify_elastic_mcp.py
```

For the ADK dev UI:

```bash
adk web --port 8081
```

## Hosted Tool Target

By default the agent points at:

```text
https://fireguard-api-dovhkdlznq-uc.a.run.app
```

Set `FIREGUARD_API_BASE_URL` in `fireguard_agent/.env` to use a local or alternate hosted API.

## Proof Boundary

- Real: ADK `root_agent` package, Gemini/Vertex model configuration, OpenAPI toolset, and FireGuard tool endpoints.
- Real: ADK `McpToolset` integration for the official Elastic MCP server, with `elastic_mcp_*` tool names when MCP config is present.
- Real: tool calls hit the same deployed FastAPI service used by the web app.
- Real: managed Vertex AI Agent Engine deployment at `projects/425727109076/locations/us-central1/reasoningEngines/9137720630806839296`.
- Real: the code-first ADK `root_agent` can call the backend OpenAPI toolset. An earlier managed ADK resource verification called `search_operational_memory` and returned DriveBC/Elastic evidence before the managed proof runtime was replaced to satisfy Gemini 3.1.
- Real: managed Agent Engine invocation used Vertex global `gemini-3.1-flash-lite-preview`, called `elastic_mcp_list_indices` through the official Elastic MCP server, and returned live `fire_hotspots` / `fire_perimeters` index counts from Elasticsearch.
- Guarded: public-facing actions still require backend approval state and Twilio allowlist enforcement.
- Transparent constraint: the standard ADK `LlmAgent` path still exists, but the managed proof runtime uses `deploy_managed_agent_engine.py` because the regional ADK model resolver only exposes Gemini 2.x models in this project. The managed runtime still runs inside Vertex AI Agent Engine and calls Vertex global Gemini 3.1 plus Elastic MCP from there.

## Deploy To Agent Engine

```bash
cd integrations/google_adk
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

GOOGLE_CLOUD_PROJECT=verdant-upgrade-493301-q1 \
GOOGLE_CLOUD_LOCATION=us-central1 \
FIREGUARD_AGENT_MODEL_LOCATION=global \
GEMINI_MODEL=gemini-3.1-flash-lite-preview \
FIREGUARD_ELASTIC_MCP_URL=https://fireguard-elastic-mcp-425727109076.us-central1.run.app/mcp \
FIREGUARD_ELASTIC_MCP_AUTH=google_id_token \
FIREGUARD_ELASTIC_MCP_ID_TOKEN_AUDIENCE=https://fireguard-elastic-mcp-425727109076.us-central1.run.app \
FIREGUARD_ELASTIC_MCP_REQUIRED=true \
AGENT_ENGINE_BUCKET=gs://verdant-upgrade-493301-q1-fireguard-agent-engine \
AGENT_ENGINE_SERVICE_ACCOUNT=425727109076-compute@developer.gserviceaccount.com \
python deploy_managed_agent_engine.py
```

To update the existing resource, add:

```bash
AGENT_ENGINE_RESOURCE=projects/425727109076/locations/us-central1/reasoningEngines/9137720630806839296
```

## Verify Managed Agent Engine MCP

```bash
cd integrations/google_adk
. .venv/bin/activate
python verify_agent_engine_mcp.py
```

Expected result includes `model_versions=["gemini-3.1-flash-lite-preview"]`,
one `elastic_mcp_list_indices` function call, and one successful function
response with `fire_hotspots` and `fire_perimeters` index counts. A recorded
proof is stored at
[docs/proofs/agent_engine_elastic_mcp_2026-05-11.json](../../docs/proofs/agent_engine_elastic_mcp_2026-05-11.json).
