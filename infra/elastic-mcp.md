# Elastic MCP Verification

FireGuard keeps Elastic as the official partner-track integration. The MCP server config in `infra/elastic-mcp.json` points at the same Elasticsearch deployment used by the hosted API.

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

## Safety

The verification container was removed after the check. Do not expose the MCP HTTP server publicly with production Elasticsearch credentials.
