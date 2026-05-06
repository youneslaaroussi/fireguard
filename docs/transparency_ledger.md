# FireGuard Transparency Ledger

Last updated: 2026-05-06

This file is the source of truth for what is real, what is simulated, and what still needs to be made production-real. Do not remove or soften an item because it makes the demo look better. Update the status only after code and tests prove the claim.

## Current Truth Summary

FireGuard is a real hosted Cloud Run app with a real FastAPI backend, real Next.js frontend, real Elastic-backed operational memory, a real Fivetran Connector SDK path into BigQuery, real Vertex Gemini calls, real Twilio allowlisted SMS execution, and real Phoenix/OpenTelemetry span IDs.

FireGuard is not yet a fully real emergency orchestration system. The demo-critical evacuation scenario still uses replay and synthetic operational records, and some deterministic route logic remains.

## Real Components

| Component | Current status | Evidence |
|---|---|---|
| Hosted web app | Real | Cloud Run web service at `https://fireguard-web-dovhkdlznq-uc.a.run.app`. |
| Hosted API | Real | Cloud Run API service at `https://fireguard-api-dovhkdlznq-uc.a.run.app`. |
| Elastic | Real | API reports `store_backend=elastic-mirrored`; Elasticsearch runs on GCE and is reached through a private VPC connector in Cloud Run. |
| Fivetran | Real, with fallback behavior | Fivetran Connector SDK sync exists; BigQuery tables are read by `/sync/fivetran-to-elastic`. |
| BigQuery bridge | Real | Backend reads `fireguard_ingestion` tables and indexes records into Elastic. |
| Gemini | Real | Backend uses Vertex Gemini through `google-genai` and records `gemini_status=completed` in successful assessments. |
| Twilio | Real for allowlisted SMS | Zone A demo SMS has been sent through Twilio as `queued` after approval. |
| Phoenix/OpenTelemetry | Real span plumbing | Assessment traces include Phoenix trace IDs. |
| Human approval gate | Real backend enforcement | Public-facing action execution fails before approval and SMS is allowlist-filtered. |

## Known Shortcuts And Gaps

| ID | Shortcut / gap | Impact | Current status | Fix path |
|---|---|---|---|---|
| T-001 | Route computation now supports Google Routes for route geometry, duration, and distance when `GOOGLE_MAPS_API_KEY` is configured. Deterministic route fixtures remain as offline fallback. | The route geometry is provider-backed in configured environments, but the decisive closure and fire records can still be replay evidence under T-002/T-003. | Fixed in code, pending hosted redeploy | Keep test fallback deterministic. Verify hosted assessments show `route_source=google_routes` after deployment. |
| T-002 | The decisive road closure is a replay record: `DBC_REPLAY_CLOSURE_001`. | The strongest demo moment currently depends on replay road data, not a current live DriveBC closure. | Open | Replace or supplement the replay closure with a recorded real historical DriveBC/Open511 snapshot, including source timestamp and URL/lineage. If current live closure exists, prefer it automatically. |
| T-003 | Live FIRMS returned zero current hotspots for the configured BC bbox, so the demo uses labeled `NASA_FIRMS_REPLAY` hotspots. | The fire threat in the staged demo is replay, not current live fire. | Open | Store a real historical FIRMS CSV snapshot from a known BC incident window and expose it as replay source evidence. Also support selecting a live active-fire bbox when available. |
| T-004 | Evacuation zones, shelters, residents, dispatch assets, and policies are synthetic. | Population and shelter capacity constraints are not official municipal data. | Accepted for hackathon demo, but must stay labeled | Keep labels visible. If time permits, add public shelter/facility data or a clearly sourced emergency-reception-centre dataset. |
| T-005 | Shelter, road-ops, and dispatch action endpoints are simulated. | Only SMS is a real external action; other operational actions are logs/mock webhooks. | Accepted for safety | Keep as simulated unless integrating a real task system such as Linear/GitHub Issues/Firestore-backed work queue. |
| T-006 | Gemini is used through Vertex SDK, not a configured Google Agent Builder console agent. | The app satisfies Gemini tool orchestration technically, but the Agent Builder proof is weaker. | Open | Register the OpenAPI tool surface in Google Agent Builder or document ADK-compatible setup with deployable agent config. |
| T-007 | In-app eval is deterministic local code, not a hosted Arize evaluator. | Phoenix receives spans, but scoring is not an Arize-hosted evaluation pipeline. | Open | Export eval result spans with clear attributes, then add Phoenix eval documentation or hosted evaluator workflow. |
| T-008 | Fivetran connector has replay fallbacks on source timeout/failure. | Connector debug and demos remain stable, but a source outage may silently switch streams to replay unless the warning/run metadata is inspected. | Partially fixed | Preserve sync warnings in `ingestion_runs`, surface fallback stream warnings in the provider strip, and fail production mode if fallback is disallowed. |
| T-009 | The app runs with `DEMO_MODE=true` in Cloud Run. | Hosted app is intentionally a demo, not a live authority workflow. | Accepted, must stay visible | Keep UI safety labels and prevent unapproved/non-allowlisted public messaging. |

## Fix Order

1. T-002: Replace synthetic replay closure with a real historical DriveBC/Open511 snapshot.
2. T-003: Replace source-shaped FIRMS replay with stored real FIRMS CSV snapshot and optional live bbox selector.
3. T-008: Make fallback use impossible to miss in UI and ingestion-run records.
4. T-006: Add formal Google Agent Builder or ADK deployment proof.
5. T-007: Improve Phoenix evaluation proof.
6. T-004/T-005: Keep as clearly labeled synthetic/simulated unless better public data or a safe real task system is added.

## Rule For Future Changes

Every demo claim must be backed by one of:

- a live provider call;
- a stored real source snapshot with provenance;
- a synthetic/simulated label visible in code, API output, and UI.

If none of those is true, the claim does not belong in the demo script.
