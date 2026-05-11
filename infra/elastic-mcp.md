# Elastic MCP Verification

FireGuard keeps Elastic as the official partner-track integration. The MCP server config in `infra/elastic-mcp.json` points at the same Elasticsearch deployment used by the hosted API.

The Google ADK agent now loads Elastic MCP directly when MCP config is present:

- Streamable HTTP: set `FIREGUARD_ELASTIC_MCP_URL`.
- Local stdio: set `FIREGUARD_ELASTIC_MCP_ENABLED=true`, `ELASTICSEARCH_URL`, and `ELASTICSEARCH_API_KEY`.
- Verification fail-closed mode: set `FIREGUARD_ELASTIC_MCP_REQUIRED=true`.

The ADK MCP tools are prefixed as `elastic_mcp_*`, so judge-facing traces can distinguish partner MCP calls from the backend OpenAPI tool calls.

## ADK Verification

From the repository root:

```bash
cd integrations/google_adk
. .venv/bin/activate
FIREGUARD_ELASTIC_MCP_ENABLED=true \
ELASTICSEARCH_URL=http://127.0.0.1:9200 \
ELASTICSEARCH_API_KEY=... \
python verify_elastic_mcp.py
```

Expected shape:

```json
{
  "status": "ok",
  "transport": "stdio",
  "tool_count": 5,
  "tools": [
    "elastic_mcp_search",
    "elastic_mcp_list_indices",
    "elastic_mcp_get_shards",
    "elastic_mcp_get_mappings",
    "elastic_mcp_esql"
  ]
}
```

For managed Agent Engine, point the agent at a streamable HTTP MCP service:

```text
FIREGUARD_ELASTIC_MCP_URL=https://fireguard-elastic-mcp-...run.app/mcp
FIREGUARD_ELASTIC_MCP_AUTH=google_id_token
FIREGUARD_ELASTIC_MCP_ID_TOKEN_AUDIENCE=https://fireguard-elastic-mcp-...run.app
```

For Cloud Run IAM, the ADK connector sends the Google ID token through
`X-Serverless-Authorization`, not ordinary `Authorization`. The official Elastic
MCP server forwards ordinary `Authorization` headers to Elasticsearch for
per-request auth, which would override the configured Elasticsearch API key.

## Hosted Verification

Verified on 2026-05-07 UTC against the Elasticsearch VM `fireguard-elastic-2` in project `verdant-upgrade-493301-q1`.

The official Elastic MCP Docker image started successfully with:

- image: `docker.elastic.co/mcp/elasticsearch`
- mode: `http`
- endpoint: local-only on the Elasticsearch VM
- `ES_URL=http://127.0.0.1:9200`
- `ES_API_KEY` loaded from Secret Manager, not printed or committed

MCP proof:

- `/ping` returned `Ready`.
- `tools/list` returned Elastic tools: `get_mappings`, `get_shards`, `list_indices`, `esql`, and `search`.
- `tools/call` with `list_indices` and `index_pattern=fire*` returned:
  - `fire_hotspots`, open, `docs.count=48`
  - `fire_perimeters`, open, `docs.count=50`

This proves the partner MCP server can reach the same Elastic operational memory used by the API and dashboard.

Managed Cloud Run proof was added on 2026-05-10 UTC:

- Cloud Run service: `fireguard-elastic-mcp`
- image source: official `docker.elastic.co/mcp/elasticsearch`, imported into Artifact Registry as `us-central1-docker.pkg.dev/verdant-upgrade-493301-q1/fireguard/elastic-mcp:amd64`
- endpoint: private streamable HTTP MCP at `/mcp`
- ADK verification: `verify_elastic_mcp.py` listed five `elastic_mcp_*` tools and `elastic_mcp_list_indices` returned live `fire_hotspots` and `fire_perimeters` counts from Elasticsearch.

## Safety

The verification container was removed after the check. Do not expose the MCP HTTP server publicly with production Elasticsearch credentials.

If a streamable HTTP MCP service is deployed for Agent Engine, keep it IAM-protected and use a read-only Elasticsearch API key scoped to FireGuard indices.
