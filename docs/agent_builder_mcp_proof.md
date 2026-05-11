# Agent Builder And Elastic MCP Proof

FireGuard's judged track is Elastic. The agent proof has two layers:

1. **Google Agent Builder path**: a Gemini Enterprise app with a connected FireGuard data store, a custom Agent Engine agent, a code-first Google ADK agent, and a managed Vertex AI Agent Engine proof runtime.
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

Gemini Enterprise app and data store:

```text
projects/425727109076/locations/global/collections/default_collection/engines/fireguard-command-center
projects/425727109076/locations/global/collections/default_collection/dataStores/fireguard-operational-memory
```

Registered Gemini Enterprise custom agent:

```text
projects/425727109076/locations/global/collections/default_collection/engines/fireguard-command-center/assistants/default_assistant/agents/7406279429546975436
```

The data store imported five FireGuard operational-memory documents covering the safety policy, agent architecture, data lineage, Elastic MCP proof, and route-rejection scenario. The registered custom agent points at the managed Agent Engine resource above.

The managed runtime explicitly registers `streaming_agent_run_with_events`, the stream method Gemini Enterprise calls when a user chats with the custom agent in the Gemini Enterprise UI.

The ADK agent uses:

- Vertex/Gemini model configuration;
- FireGuard OpenAPI toolset for safety-controlled backend operations;
- Elastic MCP toolset for direct partner MCP access to operational memory.

The managed proof runtime lives in:

```text
integrations/google_adk/fireguard_managed_agent.py
```

It exists because the standard regional ADK `LlmAgent` model resolver does not
expose Gemini 3.1 in `us-central1` for this project. The managed proof runtime
still runs inside Vertex AI Agent Engine, but it explicitly calls Vertex global
Gemini 3.1 and the private Elastic MCP service.

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

The managed Agent Engine resource has been updated with a FireGuard managed
runtime that calls Vertex global Gemini 3.1 and the private Elastic MCP Cloud Run
service from inside Vertex AI Agent Engine.

Remote verification command:

```bash
cd integrations/google_adk
. .venv/bin/activate
python verify_agent_engine_mcp.py
```

Verified result:

- resource: `projects/425727109076/locations/us-central1/reasoningEngines/9137720630806839296`
- model: `gemini-3.1-flash-lite-preview`
- runtime: `custom_managed_vertex_agent_engine`
- tool call: `elastic_mcp_list_indices` with `index_pattern=fire*`
- tool response: live `fire_hotspots` and `fire_perimeters` counts from Elasticsearch
- proof file: [docs/proofs/agent_engine_elastic_mcp_2026-05-11.json](proofs/agent_engine_elastic_mcp_2026-05-11.json)

That is the strongest answer to the Devpost requirement:

```text
Gemini Enterprise app with connected data store + enabled Agent Engine agent + Elastic partner MCP server + real tool execution.
```

## Gemini Enterprise Actions Tab

Gemini Enterprise's console currently says actions are configured through data
connectors and are available with an Enterprise Plus license. FireGuard is on
Gemini Enterprise Standard. The Actions tab is therefore not claimed as
configured.

The real FireGuard action path is the Agent Engine-backed FireGuard tool API:
resident SMS, shelter notification, road-ops task, dispatch task, approval
state, execution logs, and trace export. Those actions are gated by backend
validators and human approval, not by the Gemini Enterprise Actions tab.
