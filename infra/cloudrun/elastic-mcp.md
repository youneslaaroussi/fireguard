# Elastic MCP On Cloud Run

This is the managed-path deployment option for making Elastic MCP available to the Google ADK / Agent Engine runtime.

The local ADK path can use stdio (`npx` or Docker). Managed Agent Engine should use the official Elastic MCP streamable-HTTP server.

## Deploy

Use a read-only Elasticsearch API key whenever possible.

Cloud Run cannot deploy directly from `docker.elastic.co`, so first import the
official Elastic image into Artifact Registry for the project:

```bash
docker pull --platform linux/amd64 docker.elastic.co/mcp/elasticsearch:latest
docker tag docker.elastic.co/mcp/elasticsearch:latest \
  us-central1-docker.pkg.dev/verdant-upgrade-493301-q1/fireguard/elastic-mcp:amd64
docker push us-central1-docker.pkg.dev/verdant-upgrade-493301-q1/fireguard/elastic-mcp:amd64
```

```bash
gcloud run deploy fireguard-elastic-mcp \
  --project verdant-upgrade-493301-q1 \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/verdant-upgrade-493301-q1/fireguard/elastic-mcp:amd64 \
  --vpc-connector fireguard-connector \
  --vpc-egress private-ranges-only \
  --no-allow-unauthenticated \
  --set-env-vars ES_URL=http://10.128.0.5:9200,HTTP_ADDRESS=0.0.0.0:8080,CONTAINER_MODE=true,OTEL_LOG_LEVEL=none \
  --set-secrets ES_API_KEY=fireguard-elasticsearch-api-key:latest \
  --args http
```

## Configure ADK / Agent Engine

```bash
FIREGUARD_ELASTIC_MCP_URL=https://fireguard-elastic-mcp-dovhkdlznq-uc.a.run.app/mcp
FIREGUARD_ELASTIC_MCP_AUTH=google_id_token
FIREGUARD_ELASTIC_MCP_ID_TOKEN_AUDIENCE=https://fireguard-elastic-mcp-dovhkdlznq-uc.a.run.app
FIREGUARD_ELASTIC_MCP_REQUIRED=true
```

The ADK agent mints a Google ID token for the Cloud Run service when
`FIREGUARD_ELASTIC_MCP_AUTH=google_id_token` is set. It sends that token in
`X-Serverless-Authorization`, not `Authorization`, because the official Elastic
MCP server treats ordinary `Authorization` as Elasticsearch per-request auth.

## Verify

```bash
cd integrations/google_adk
. .venv/bin/activate
python verify_elastic_mcp.py
```

Expected result:

```json
{
  "status": "ok",
  "transport": "streamable_http",
  "tool_count": 5,
  "tools": ["elastic_mcp_search", "elastic_mcp_list_indices", "elastic_mcp_get_shards", "elastic_mcp_get_mappings", "elastic_mcp_esql"],
  "verification_call": {
    "tool": "elastic_mcp_list_indices",
    "index_pattern": "fire*",
    "result": {
      "isError": false
    }
  }
}
```

## Security

Do not expose this service publicly with a broad Elasticsearch API key. The MCP server can read Elasticsearch data through the tools it exposes.
