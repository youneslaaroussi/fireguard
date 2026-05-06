# Architecture

FireGuard uses Fivetran for ingestion, Elastic for operational memory, deterministic services for safety-critical calculations, Gemini for orchestration, and Arize Phoenix for trace/eval proof.

## Boundary

The agent may propose and explain, but it does not directly decide whether an action is executable. The backend enforces:

- route safety checks;
- shelter capacity checks;
- data freshness penalties;
- approval requirements;
- SMS allowlist enforcement.

## Partner Proof

Elastic is the operational memory:

- geospatial records are indexed as `geo_point` and `geo_shape`;
- traces include the Elastic-style queries used for evidence retrieval;
- the Elastic MCP server can point at the same cluster for partner-track validation.

Fivetran is the production ingestion layer:

- Connector SDK streams wildfire, road, perimeter, weather, and ingestion-run tables;
- BigQuery is the preferred destination;
- `/sync/fivetran-to-elastic` moves normalized warehouse rows into Elastic.

Arize Phoenix is the observability layer:

- every agent tool call emits an OpenTelemetry span when Phoenix is enabled;
- eval results are stored in Elastic and exported as Phoenix spans;
- the UI shows Phoenix trace IDs beside the in-app audit events.

When provider credentials are absent, replay and memory fallbacks keep local tests deterministic, but judged runs should use the real provider path.
