# Agent Builder And Elastic MCP Proof

FireGuard's judged track is Elastic. The agent proof has two layers:

1. **Google Agent Builder path**: a code-first Google ADK agent deployable to Vertex AI Agent Engine.
2. **Partner MCP path**: the official Elastic MCP server exposed to the ADK agent as an `McpToolset`.

## Current Agent Builder Path

Agent package:

```text
integrations/google_adk/fireguard_agent
```

Managed Agent Engine resource:

```text
projects/425727109076/locations/us-central1/reasoningEngines/9137720630806839296
```

The ADK agent uses:

- Vertex/Gemini model configuration;
- FireGuard OpenAPI toolset for safety-controlled backend operations;
- Elastic MCP toolset for direct partner MCP access to operational memory.

## Elastic MCP Integration

The ADK agent imports and loads:

```python
google.adk.tools.mcp_tool.McpToolset
```

When configured, MCP tools are prefixed:

```text
elastic_mcp_list_indices
elastic_mcp_get_mappings
elastic_mcp_search
elastic_mcp_get_shards
elastic_mcp_esql
```

The agent instruction explicitly tells Gemini to call an `elastic_mcp_*` tool before the backend `search_operational_memory` tool when MCP is available. This makes partner MCP usage visible in traces and remote invocations.

## Verification Commands

Local stdio:

```bash
cd integrations/google_adk
. .venv/bin/activate
FIREGUARD_ELASTIC_MCP_ENABLED=true \
ELASTICSEARCH_URL=http://127.0.0.1:9200 \
ELASTICSEARCH_API_KEY=... \
python verify_elastic_mcp.py
```

Managed streamable HTTP:

```bash
cd integrations/google_adk
. .venv/bin/activate
FIREGUARD_ELASTIC_MCP_URL=https://fireguard-elastic-mcp-...run.app/mcp \
FIREGUARD_ELASTIC_MCP_AUTH=google_id_token \
FIREGUARD_ELASTIC_MCP_REQUIRED=true \
FIREGUARD_ELASTIC_MCP_VERIFY_CALL=true \
python verify_elastic_mcp.py
```

For a private Cloud Run MCP service, FireGuard sends the Google ID token through
`X-Serverless-Authorization`, not `Authorization`. That matters because the
official Elastic MCP server forwards ordinary `Authorization` headers to
Elasticsearch for per-request auth.

Expected output shape:

```json
{
  "status": "ok",
  "transport": "streamable_http",
  "tool_count": 5,
  "tools": [
    "elastic_mcp_search",
    "elastic_mcp_list_indices",
    "elastic_mcp_get_shards",
    "elastic_mcp_get_mappings",
    "elastic_mcp_esql"
  ],
  "verification_call": {
    "tool": "elastic_mcp_list_indices",
    "index_pattern": "fire*",
    "result": {
      "isError": false
    }
  }
}
```

## Managed Agent Engine MCP Proof

The managed Agent Engine resource has been updated with `FIREGUARD_ELASTIC_MCP_URL`
and `FIREGUARD_ELASTIC_MCP_REQUIRED=true`.

Remote verification command:

```bash
cd integrations/google_adk
. .venv/bin/activate
python verify_agent_engine_mcp.py
```

Verified result:

- resource: `projects/425727109076/locations/us-central1/reasoningEngines/9137720630806839296`
- model: `gemini-2.5-flash`
- tool call: `elastic_mcp_list_indices` with `index_pattern=fire*`
- tool response: live `fire_hotspots` and `fire_perimeters` counts from Elasticsearch
- proof file: [docs/proofs/agent_engine_elastic_mcp_2026-05-11.json](proofs/agent_engine_elastic_mcp_2026-05-11.json)

That is the strongest answer to the Devpost requirement:

```text
Gemini / Google Agent Builder agent + Elastic partner MCP server + real tool execution.
```
