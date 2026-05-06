# FireGuard Transparency Ledger

Last updated: 2026-05-06

This file is the source of truth for what is real, what is simulated, and what still needs to be made production-real. Do not remove or soften an item because it makes the demo look better. Update the status only after code and tests prove the claim.

## Current Truth Summary

FireGuard is a real hosted Cloud Run app with a real FastAPI backend, real Next.js frontend, real Elastic-backed operational memory, a real Fivetran Connector SDK path into BigQuery, real Vertex Gemini calls, real Twilio allowlisted SMS execution, and real OpenTelemetry span export to a self-hosted Arize Phoenix service on Cloud Run. The provided Arize Cloud API key still returns `401` against Phoenix Cloud REST, so Arize Cloud hosted export remains blocked pending a valid Phoenix Cloud key/space. The current self-hosted Phoenix deployment uses container-local SQLite storage unless PostgreSQL is configured, so traces are demo-visible but not yet production-durable across service replacement.

FireGuard is not yet a fully real emergency orchestration system. The demo-critical evacuation scenario still uses replay and synthetic operational records, but the fire and road replay evidence is now stored from real source snapshots rather than invented rows.

## Real Components

| Component | Current status | Evidence |
|---|---|---|
| Hosted web app | Real | Cloud Run web service at `https://fireguard-web-dovhkdlznq-uc.a.run.app`. |
| Hosted API | Real | Cloud Run API service at `https://fireguard-api-dovhkdlznq-uc.a.run.app`. |
| Elastic | Real | API reports `store_backend=elastic-mirrored`; Elasticsearch runs on GCE and is reached through a private VPC connector in Cloud Run. |
| Fivetran | Real, with visible fallback behavior | Fivetran Connector SDK sync exists; BigQuery tables are read by `/sync/fivetran-to-elastic`. Hosted sync on `2026-05-06` read BigQuery rows for `fire_perimeters` (44), `road_events` (50), and `weather_observations` (1), then emitted a visible `fire_hotspots` fallback warning because the live FIRMS stream was empty for the configured BC bbox. |
| BigQuery bridge | Real | Backend reads `fireguard_ingestion` tables and indexes records into Elastic. |
| Gemini / Google ADK | Real Vertex Gemini calls; ADK package added and locally verified | Backend uses Vertex Gemini through `google-genai`; hosted assessment verified `gemini_status=completed` with `gemini-3.1-flash-lite-preview`, `GOOGLE_CLOUD_LOCATION=global`, and five tool calls. The repo now includes a code-first ADK `root_agent` at `integrations/google_adk/fireguard_agent` with an OpenAPI toolset for all eight FireGuard tool endpoints; local import verification instantiated `fireguard_evacuation_coordinator` with one OpenAPI toolset. |
| Twilio | Real for allowlisted SMS | Zone A demo SMS has been sent through Twilio as `queued` after approval. |
| Phoenix/OpenTelemetry | Real self-hosted Phoenix export; Arize Cloud auth blocked; persistence not production-grade yet | Phoenix runs at `https://fireguard-phoenix-dovhkdlznq-uc.a.run.app`; Cloud Run revision `fireguard-phoenix-00002-zzw` has `minScale=1`; hosted assessment exported 8 trace spans and eval exported Phoenix trace `8b61da5b3907143984a626d14da35417:f9e47d7ea730bfc9`. Phoenix REST lists the `fireguard` project after assessment/eval. The provided Arize Cloud key returns `401` against `https://app.phoenix.arize.com/v1/projects`. Phoenix logs show default `sqlite:////root/.phoenix/phoenix.db` storage, so PostgreSQL is still needed for durable production trace storage. |
| Human approval gate | Real backend enforcement | Public-facing action execution fails before approval and SMS is allowlist-filtered. |

## Known Shortcuts And Gaps

| ID | Shortcut / gap | Impact | Current status | Fix path |
|---|---|---|---|---|
| T-001 | Route computation now supports Google Routes for route geometry, duration, and distance when `GOOGLE_MAPS_API_KEY` is configured. Deterministic route fixtures remain as offline fallback. | The route geometry is provider-backed in configured environments, but the decisive closure and fire records can still be replay evidence under T-002/T-003. | Fixed and hosted-verified | Hosted assessment returned `route_sources=["google_routes"]`; keep test fallback deterministic. |
| T-002 | The decisive road closure now uses real DriveBC/Open511 event `drivebc.ca/DBC-90684` as a source snapshot. | The route-rejection evidence is source-backed, but the surrounding demo zones/shelters/fire placement are still synthetic/replay under T-003/T-004. | Fixed and hosted-verified | Hosted assessment on `2026-05-06` returned `route_sources=["google_routes"]`; Zone A to Shelter A was unsafe with evidence `drivebc.ca/DBC-90684`, while Zone A to Shelter B was safe. |
| T-003 | Live FIRMS returned zero current hotspots for the configured BC bbox, so replay mode now uses stored real NASA FIRMS Area API CSV rows from `VIIRS_NOAA20_SP`, bbox `-122.2,52.0,-121.3,52.9`, day range `5`, start date `2024-07-10`. | The fire threat is still historical replay, not current live fire; the API correctly marks fire freshness as stale. | Fixed and hosted-verified | Hosted assessment on `2026-05-06` returned 45 `NASA_FIRMS_HISTORICAL_SNAPSHOT` records, redacted `[MAP_KEY]` source URL, `route_sources=["google_routes"]`, Shelter A unsafe with FIRMS + `drivebc.ca/DBC-90684` evidence, and Shelter B safe. |
| T-004 | Evacuation zones, shelters, residents, dispatch assets, and policies are synthetic. | Population and shelter capacity constraints are not official municipal data. | Accepted for hackathon demo, but must stay labeled | Keep labels visible. If time permits, add public shelter/facility data or a clearly sourced emergency-reception-centre dataset. |
| T-005 | Shelter, road-ops, and dispatch action endpoints are simulated. | Only SMS is a real external action; other operational actions are logs/mock webhooks. | Accepted for safety | Keep as simulated unless integrating a real task system such as Linear/GitHub Issues/Firestore-backed work queue. |
| T-006 | Gemini was originally used only through backend Vertex SDK calls, without a reusable Google agent package. | The app already had real Gemini tool orchestration, but the Agent Builder/ADK proof was weaker than it should be for judging. | Fixed as code-first ADK proof; console registration still optional | Added `integrations/google_adk/fireguard_agent` with ADK `root_agent`, `tools.openapi.json`, `.env.example`, and run docs. Local verification installed `google-adk` and imported `root_agent`; tests assert all eight required tool operations are present. Hosted `/agent/manifest` exposes the ADK path/spec after API redeploy. A configured low-code Agent Builder console agent is still not claimed. |
| T-010 | Hosted assessments briefly failed with Vertex `429 RESOURCE_EXHAUSTED` on `gemini-2.5-flash`; the first `gemini-3.1-flash-lite-preview` deploy used `us-central1` and the SDK returned `404 NOT_FOUND`; the next run hit oversized tool payloads. | The deterministic plan still generated, but Gemini tool orchestration did not complete in those runs. | Fixed and hosted-verified | Hosted assessment now returns `gemini_status=completed` with `gemini-3.1-flash-lite-preview`, `GOOGLE_CLOUD_LOCATION=global`, and trimmed LLM tool payloads. |
| T-007 | In-app eval is deterministic local code, not a hosted Arize evaluator. | The scoring rubric is still local deterministic code, but eval output is exported to Phoenix as an OpenTelemetry span. | Partially fixed and hosted-verified | Hosted `/evals/demo-incident-bc-001` returned score `1.0` and `eval_phoenix_trace_id`; add a Phoenix-hosted evaluator workflow only if required by judging. |
| T-008 | Fivetran connector and backend sync can use replay/snapshot fallbacks on source timeout, missing config, or empty live FIRMS rows. | Demo stability is preserved, and fallback use is now visible in API status and the web provider strip. It is still not a pure-live wildfire feed when FIRMS is quiet. | Fixed and hosted-verified | Connector `ingestion_runs` now includes `fallback_warnings_json`; backend sync/seed runs include `fallback_active` and `warnings`; `/integrations/status` exposes `fivetran.fallback_active`; the web provider strip shows `fallback active` with an attention badge. Hosted `/sync/fivetran-to-elastic` returned `mode=bigquery_with_replay_fallback`, `fallback_active=true`, and a `fire_hotspots` warning for 45 historical FIRMS rows. |
| T-009 | The app runs with `DEMO_MODE=true` in Cloud Run. | Hosted app is intentionally a demo, not a live authority workflow. | Accepted, must stay visible | Keep UI safety labels and prevent unapproved/non-allowlisted public messaging. |
| T-011 | The provided Arize Cloud API key does not authenticate against Phoenix Cloud REST, so Arize Cloud export is not proven. | We can prove self-hosted Phoenix export on Cloud Run, but not Arize Cloud hosted receipt with the current key. | Blocked on valid Arize Cloud key/space | Hosted self-hosted Phoenix is fixed: `/integrations/arize/status` returns `deployment=self_hosted`, `connection_check.status=ok`, and project `fireguard`. API Phoenix REST checks now use `PHOENIX_STATUS_TIMEOUT_SECONDS=10` instead of a brittle 2 second timeout. To switch to Arize Cloud, provide the exact Phoenix Cloud space URL and a key that returns 200 for `/v1/projects`. |
| T-012 | Self-hosted Phoenix currently uses container-local SQLite storage. | Trace export is real and demo-visible, but traces can disappear after Cloud Run replacement/restart. | Open, demo-mitigated | Cloud Run Phoenix now has `minScale=1`, which keeps the demo service warm but is not persistence. Configure Phoenix with `PHOENIX_SQL_DATABASE_URL` backed by Cloud SQL PostgreSQL, or switch to working Arize Cloud credentials before claiming durable hosted trace retention. |

## Fix Order

1. T-011: Switch from self-hosted Phoenix to Arize Cloud only after receiving a valid Phoenix Cloud key/space.
2. T-012: Add persistent PostgreSQL storage for self-hosted Phoenix if Arize Cloud remains blocked.
3. T-005: Keep simulated operational actions clearly labeled unless a safe real task system is added.
4. T-004: Keep synthetic municipal data clearly labeled unless better public data is added.

## Rule For Future Changes

Every demo claim must be backed by one of:

- a live provider call;
- a stored real source snapshot with provenance;
- a synthetic/simulated label visible in code, API output, and UI.

If none of those is true, the claim does not belong in the demo script.
