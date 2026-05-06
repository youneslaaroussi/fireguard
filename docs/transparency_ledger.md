# FireGuard Transparency Ledger

Last updated: 2026-05-06

This file is the source of truth for what is real, what is simulated, and what still needs to be made production-real. Do not remove or soften an item because it makes the demo look better. Update the status only after code and tests prove the claim.

## Current Truth Summary

FireGuard is a real hosted Cloud Run app with a real FastAPI backend, real Next.js frontend, real Elastic-backed operational memory, a real Fivetran Connector SDK path into BigQuery, real Vertex Gemini calls, real Twilio allowlisted SMS execution, and OpenTelemetry span IDs. Hosted Phoenix export still needs verification because Cloud Run logs have shown Arize collector `401` responses.

FireGuard is not yet a fully real emergency orchestration system. The demo-critical evacuation scenario still uses replay and synthetic operational records, but the fire and road replay evidence is now stored from real source snapshots rather than invented rows.

## Real Components

| Component | Current status | Evidence |
|---|---|---|
| Hosted web app | Real | Cloud Run web service at `https://fireguard-web-dovhkdlznq-uc.a.run.app`. |
| Hosted API | Real | Cloud Run API service at `https://fireguard-api-dovhkdlznq-uc.a.run.app`. |
| Elastic | Real | API reports `store_backend=elastic-mirrored`; Elasticsearch runs on GCE and is reached through a private VPC connector in Cloud Run. |
| Fivetran | Real, with fallback behavior | Fivetran Connector SDK sync exists; BigQuery tables are read by `/sync/fivetran-to-elastic`. |
| BigQuery bridge | Real | Backend reads `fireguard_ingestion` tables and indexes records into Elastic. |
| Gemini | Real | Backend uses Vertex Gemini through `google-genai`; hosted assessment verified `gemini_status=completed` with `gemini-3.1-flash-lite-preview`, `GOOGLE_CLOUD_LOCATION=global`, and five tool calls. |
| Twilio | Real for allowlisted SMS | Zone A demo SMS has been sent through Twilio as `queued` after approval. |
| Phoenix/OpenTelemetry | Real local span plumbing, hosted export unverified | Assessment traces include OpenTelemetry trace/span IDs; Cloud Run logs have shown hosted Arize collector `401`, so Phoenix hosted receipt is not yet proven. |
| Human approval gate | Real backend enforcement | Public-facing action execution fails before approval and SMS is allowlist-filtered. |

## Known Shortcuts And Gaps

| ID | Shortcut / gap | Impact | Current status | Fix path |
|---|---|---|---|---|
| T-001 | Route computation now supports Google Routes for route geometry, duration, and distance when `GOOGLE_MAPS_API_KEY` is configured. Deterministic route fixtures remain as offline fallback. | The route geometry is provider-backed in configured environments, but the decisive closure and fire records can still be replay evidence under T-002/T-003. | Fixed and hosted-verified | Hosted assessment returned `route_sources=["google_routes"]`; keep test fallback deterministic. |
| T-002 | The decisive road closure now uses real DriveBC/Open511 event `drivebc.ca/DBC-90684` as a source snapshot. | The route-rejection evidence is source-backed, but the surrounding demo zones/shelters/fire placement are still synthetic/replay under T-003/T-004. | Fixed and hosted-verified | Hosted assessment on `2026-05-06` returned `route_sources=["google_routes"]`; Zone A to Shelter A was unsafe with evidence `drivebc.ca/DBC-90684`, while Zone A to Shelter B was safe. |
| T-003 | Live FIRMS returned zero current hotspots for the configured BC bbox, so replay mode now uses stored real NASA FIRMS Area API CSV rows from `VIIRS_NOAA20_SP`, bbox `-122.2,52.0,-121.3,52.9`, day range `5`, start date `2024-07-10`. | The fire threat is still historical replay, not current live fire. | Fixed in code, pending hosted redeploy | Hosted assessment must show `NASA_FIRMS_HISTORICAL_SNAPSHOT` fire evidence from `data/replay/bc_demo/firms_snapshot.csv` and route rejection caused by a real FIRMS point plus `drivebc.ca/DBC-90684`. |
| T-004 | Evacuation zones, shelters, residents, dispatch assets, and policies are synthetic. | Population and shelter capacity constraints are not official municipal data. | Accepted for hackathon demo, but must stay labeled | Keep labels visible. If time permits, add public shelter/facility data or a clearly sourced emergency-reception-centre dataset. |
| T-005 | Shelter, road-ops, and dispatch action endpoints are simulated. | Only SMS is a real external action; other operational actions are logs/mock webhooks. | Accepted for safety | Keep as simulated unless integrating a real task system such as Linear/GitHub Issues/Firestore-backed work queue. |
| T-006 | Gemini is used through Vertex SDK, not a configured Google Agent Builder console agent. | The app satisfies Gemini tool orchestration technically, but the Agent Builder proof is weaker. | Open | Register the OpenAPI tool surface in Google Agent Builder or document ADK-compatible setup with deployable agent config. |
| T-010 | Hosted assessments briefly failed with Vertex `429 RESOURCE_EXHAUSTED` on `gemini-2.5-flash`; the first `gemini-3.1-flash-lite-preview` deploy used `us-central1` and the SDK returned `404 NOT_FOUND`; the next run hit oversized tool payloads. | The deterministic plan still generated, but Gemini tool orchestration did not complete in those runs. | Fixed and hosted-verified | Hosted assessment now returns `gemini_status=completed` with `gemini-3.1-flash-lite-preview`, `GOOGLE_CLOUD_LOCATION=global`, and trimmed LLM tool payloads. |
| T-007 | In-app eval is deterministic local code, not a hosted Arize evaluator. | Phoenix receives spans, but scoring is not an Arize-hosted evaluation pipeline. | Open | Export eval result spans with clear attributes, then add Phoenix eval documentation or hosted evaluator workflow. |
| T-008 | Fivetran connector has replay fallbacks on source timeout/failure. | Connector debug and demos remain stable, but a source outage may silently switch streams to replay unless the warning/run metadata is inspected. | Partially fixed | Preserve sync warnings in `ingestion_runs`, surface fallback stream warnings in the provider strip, and fail production mode if fallback is disallowed. |
| T-009 | The app runs with `DEMO_MODE=true` in Cloud Run. | Hosted app is intentionally a demo, not a live authority workflow. | Accepted, must stay visible | Keep UI safety labels and prevent unapproved/non-allowlisted public messaging. |
| T-011 | Hosted Arize/Phoenix export is not yet proven. | The UI shows span IDs generated by OpenTelemetry, but Arize hosted receipt may be failing because Cloud Run logs showed collector `401` responses. | Open | Fix Phoenix hosted auth/project configuration, verify spans appear in Arize/Phoenix, then expose a trace URL or receipt proof in the API/UI. |

## Fix Order

1. T-003: Redeploy and hosted-verify the real NASA FIRMS historical snapshot path.
2. T-011/T-007: Fix hosted Phoenix export and improve evaluation proof.
3. T-008: Make fallback use impossible to miss in UI and ingestion-run records.
4. T-006: Add formal Google Agent Builder or ADK deployment proof.
5. T-005: Keep simulated operational actions clearly labeled unless a safe real task system is added.
6. T-004: Keep synthetic municipal data clearly labeled unless better public data is added.

## Rule For Future Changes

Every demo claim must be backed by one of:

- a live provider call;
- a stored real source snapshot with provenance;
- a synthetic/simulated label visible in code, API output, and UI.

If none of those is true, the claim does not belong in the demo script.
