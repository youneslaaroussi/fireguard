# FireGuard

FireGuard is an AI evacuation coordinator that turns live wildfire, road, weather, and shelter data into staged, human-approved evacuation actions.

This is a Google Cloud Rapid Agent Hackathon project targeting the Elastic track, with Fivetran ingestion and Arize Phoenix observability as visible supporting integrations. The core demo is not a fire map: it is a tool-using agent loop that retrieves operational context from Elastic, evaluates wildfire evacuation constraints, proposes a staged action bundle, waits for human approval, executes test actions, and records Phoenix-compatible traces.

## Hosted Demo

- Web app: https://fireguard-web-dovhkdlznq-uc.a.run.app
- API docs: https://fireguard-api-dovhkdlznq-uc.a.run.app/docs
- Public repository: https://github.com/youneslaaroussi/fireguard

## Safety Notice

FireGuard is a hackathon prototype. It does not issue official emergency alerts and must not be used for real emergency response. Public-facing actions are blocked until approval and, in demo mode, SMS delivery is restricted to allowlisted test contacts.

For an explicit list of what is real, replayed, synthetic, or still unfinished, see [docs/transparency_ledger.md](docs/transparency_ledger.md).

## Architecture

```text
NASA FIRMS + BC Wildfire + DriveBC/Open511 + Open-Meteo
        |
        v
Fivetran Connector SDK -> BigQuery destination
        |
        v
FastAPI Fivetran-to-Elastic sync + deterministic safety services
        |
        v
Elastic operational memory + Elastic MCP server
        |
        v
Gemini / Google ADK tool orchestration
        |
        v
Next.js incident command dashboard
        |
        v
Approval queue -> Twilio allowlisted SMS + GitHub Issues task backend for shelter/road/dispatch
        |
        v
Arize Phoenix / OpenTelemetry spans + eval trace annotations
```

## Local Setup

```bash
cd /Users/mac/dev/fireguard
cp .env.example .env

cd apps/api
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[bigquery,dev]"

cd ../web
npm install

cd /Users/mac/dev/fireguard
npm run dev:api
npm run dev:web
```

Open:

- API: http://localhost:8000/docs
- Web: http://localhost:3000

The app runs in replay mode without secrets. Add real keys to `.env` to enable Fivetran, Elastic Cloud, Gemini, Google Routes, Twilio, and hosted/local Phoenix paths.

## Required Environment Variables

See `.env.example`. The keys needed for a full submission are:

- `ELASTICSEARCH_URL` and `ELASTICSEARCH_API_KEY`
- `FIVETRAN_API_KEY`, `FIVETRAN_API_SECRET`, `FIVETRAN_DESTINATION_NAME`
- `FIVETRAN_BIGQUERY_PROJECT`, `FIVETRAN_BIGQUERY_DATASET`
- `NASA_FIRMS_MAP_KEY`
- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_MAPS_API_KEY`
- Optional `GOOGLE_SHEETS_CAPACITY_SPREADSHEET_ID`, `GOOGLE_SHEETS_CAPACITY_RANGE`
- `PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_PROJECT_NAME`, optional `PHOENIX_API_KEY`, optional `PHOENIX_CLOUD_SPACE_NAME`
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `TWILIO_ALLOWLIST`
- `TWILIO_VALIDATE_WEBHOOK_SIGNATURE`, optional `TWILIO_INBOUND_WEBHOOK_PUBLIC_URL` for inbound SMS opt-in validation

## Google ADK Agent

The code-first ADK agent lives in `integrations/google_adk/fireguard_agent`. It loads `tools.openapi.json` with ADK's OpenAPI toolset and points at the same hosted FastAPI tool endpoints used by the web demo.

```bash
cd integrations/google_adk
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp fireguard_agent/.env.example fireguard_agent/.env
adk run fireguard_agent
```

This is stronger than a prompt-only Gemini call: the agent has a runnable `root_agent`, eight OpenAPI tools, and the backend still owns route safety, approval gates, and action enforcement.

## Fivetran Connector

The production ingestion contract lives in `integrations/fivetran/fireguard_connector`.
Use `fireguard_ingestion` as the Fivetran connection name so the BigQuery
dataset matches `FIVETRAN_BIGQUERY_DATASET`.

```bash
cd integrations/fivetran/fireguard_connector
python3 -m venv .venv
. .venv/bin/activate
pip install "fivetran-connector-sdk==2.8.1" -r requirements.txt
cp configuration.json.example configuration.json
fivetran debug . --configuration configuration.json
```

After Fivetran syncs into BigQuery, call:

```bash
curl -X POST http://localhost:8000/sync/fivetran-to-elastic
```

The hosted deployment also has Cloud Scheduler jobs documented in `infra/cloudrun/scheduler.md` that refresh Fivetran-to-Elastic and public BC context every 15 minutes.

Direct `/ingest/*` API routes remain as replay/dev fallback only.

## Action Task Backend

Approved shelter, road-ops, and dispatch actions can create real GitHub issues in the configured demo repository:

```bash
ACTION_TASK_BACKEND=github_issues
GITHUB_REPO=youneslaaroussi/fireguard
GITHUB_TOKEN=...
```

This is a real task record for the hackathon demo, not an official emergency-system integration. The normal `POST /actions/{bundle_id}/execute` path executes the full approved bundle. For provider verification without resending SMS, the API also supports `?action_types=shelter_notify,road_ops_task,dispatch_task`.

## Arize Phoenix

For local Phoenix:

```bash
python3 -m pip install arize-phoenix
phoenix serve
```

The API exports spans to `PHOENIX_COLLECTOR_ENDPOINT`, defaulting to `http://localhost:6006/v1/traces`. The deployed demo uses a self-hosted Arize Phoenix service on Cloud Run for the in-app audit view and can also export duplicate OpenTelemetry spans to Arize AX when `ARIZE_SPACE_ID` and `ARIZE_API_KEY` are configured. Phoenix Cloud can be enabled separately by setting `PHOENIX_COLLECTOR_ENDPOINT=https://app.phoenix.arize.com`, `PHOENIX_CLOUD_SPACE_NAME=<space-name>`, `PHOENIX_API_KEY`, and `PHOENIX_AUTH_ENABLED=true` after a valid Phoenix Cloud key/space is available. You can also set `PHOENIX_COLLECTOR_ENDPOINT` directly to `https://app.phoenix.arize.com/s/<space-name>/v1/traces`.

The Cloud Run Phoenix service now uses Cloud SQL PostgreSQL through `PHOENIX_SQL_DATABASE_URL` stored in Secret Manager. The API reports the expected status through `PHOENIX_STORAGE_BACKEND=cloud_sql_postgresql` in deployed environments. Eval runs create a Phoenix span and then attach a native `fireguard_eval` trace annotation with the deterministic safety checks.

## Demo Flow

1. Load the dashboard.
2. Click `Reset Demo`.
3. Click `Sync Fivetran To Elastic`.
4. Click `Run Agent Assessment`.
5. Confirm that the nearest reception-centre option is rejected because official BC ESS status marks it closed, while other unsafe alternatives show road-closure and fire-risk blockers.
6. Approve the action bundle.
7. Execute actions.
8. Open the trace panel and inspect evidence, freshness, Phoenix span IDs, eval score, Phoenix eval annotation, approval, and execution results.

## Data Sources

Live/open sources ingested through Fivetran:

- NASA FIRMS active fire detections
- BC Wildfire current fire perimeters
- DriveBC/Open511 road events
- Open-Meteo wind forecast
- Google Routes API
- BC Historical Orders and Alerts fire evacuation polygons
- BC public evacuation, wildfire, and emergency-alert guidance snippets

Additional public BC emergency context:

- EmergencyMapBC Evacuation Orders and Alerts live ArcGIS query, with stored snapshot fallback
- BC Emergency Social Services Facilities live ArcGIS query, with stored snapshot fallback

Synthetic or operator-entered demo data:

- shelter capacity numbers
- resident-contact placeholders, except Zone A can use `DEMO_RESIDENT_ZONE_A_PHONE`, any zone can use `POST /resident-contacts/test-check-in` for an operator-provided Twilio test recipient, and any test recipient can text `JOIN ZONE_A`, `JOIN ZONE_B`, or `JOIN ZONE_C` through the Twilio inbound webhook for auditable SMS opt-in
- dispatch asset availability is not claimed; FireGuard creates an operator dispatch task request
- municipal action endpoints, unless the GitHub Issues task backend is configured
- vulnerability counts and vehicle-access scores derived from the source-backed evacuation zones

Replay mode uses stored real source snapshots where live data is quiet. The FIRMS replay file is an official NASA FIRMS Area API CSV snapshot with the MAP_KEY redacted from provenance. The core evacuation zones use official BC Historical Orders and Alerts polygons with source-backed population/home counts. Shelter A/B/C identity, location, and public open/closed status use official BC ESS facility records; closed facilities are rejected for evacuee intake. Capacity numbers remain operator-entered demo assumptions because the public ESS layer does not expose capacity. Operator-provided or Twilio inbound opt-in test recipients can be configured for any zone; untouched resident contacts remain synthetic and labeled. FireGuard no longer seeds fake dispatch vehicles or claims asset availability; dispatch actions are operator task requests that create GitHub Issues when configured, otherwise they remain simulated and labeled.

Remaining non-authoritative operational inputs are exposed as `operational_assumptions` in the API, displayed in the web UI, attached to route/action `assumption_ids`, and exported to Phoenix spans as `fireguard.assumption_ids`. Shelter capacity can be changed through `POST /shelters/{shelter_id}/capacity-check-in`, the UI `Confirm Capacity` button, or `POST /sync/google-sheets-shelter-capacity` when an operator-maintained Google Sheet is configured. These paths update the decision trace from a capacity assumption to an operator-confirmed input. Resident test contacts can be changed through `POST /resident-contacts/test-check-in` or the UI `Add Test Contact` button, or by texting `JOIN ZONE_A`/`JOIN ZONE_B`/`JOIN ZONE_C` to the Twilio number once its incoming SMS webhook points at `/resident-contacts/twilio/inbound`. API responses expose masked numbers, Twilio inbound records store consent metadata and message SID, and SMS execution rejects synthetic placeholders plus non-allowlisted numbers. The demo should not describe any operator check-in, Google Sheet, or Twilio test opt-in as an official ESS capacity feed, official resident registry, or official dispatch availability unless an authorized agency supplies that source.

## Tests

```bash
cd apps/api
. .venv/bin/activate
pytest
```

The test suite covers route rejection, shelter overflow, unsafe evacuation, stale data, SMS allowlist enforcement, Fivetran sync/status, and eval scoring.

## Cloud Run Deployment

The deployed API uses Cloud Run, Secret Manager, and a Serverless VPC connector to reach the Elasticsearch VM on its private address. The web image is built with `NEXT_PUBLIC_API_BASE_URL` pointing at the deployed API.

```bash
gcloud builds submit . \
  --config infra/cloudrun/cloudbuild-api.yaml \
  --substitutions _IMAGE=us-central1-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/fireguard/fireguard-api:latest

gcloud builds submit . \
  --config infra/cloudrun/cloudbuild-web.yaml \
  --substitutions _IMAGE=us-central1-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/fireguard/fireguard-web:latest,_API_URL=https://YOUR_API_URL
```
