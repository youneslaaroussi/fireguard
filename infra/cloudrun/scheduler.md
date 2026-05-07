# FireGuard Cloud Scheduler

FireGuard uses Cloud Scheduler to keep hosted demo data fresh without manual curl commands.

## Jobs

| Job | Schedule | Target | Purpose |
|---|---:|---|---|
| `fireguard-sync-fivetran-elastic` | `*/15 * * * *` UTC | `POST https://fireguard-api-dovhkdlznq-uc.a.run.app/sync/fivetran-to-elastic` | Reads Fivetran-loaded BigQuery rows and indexes normalized wildfire, road, and weather records into Elastic. |
| `fireguard-ingest-public-bc-context` | `*/15 * * * *` UTC | `POST https://fireguard-api-dovhkdlznq-uc.a.run.app/ingest/public-bc-context` | Refreshes live BC EmergencyMapBC evacuation orders/alerts and BC ESS facility context into Elastic. |

## Verification

Hosted verification on 2026-05-07 UTC:

- `fireguard-sync-fivetran-elastic` manual run recorded `lastAttemptTime=2026-05-07T12:21:52.805328Z`.
- `/integrations/fivetran/status` returned latest run `mode=bigquery`, `status=synced`, no warnings, and streams `fire_hotspots=1`, `fire_perimeters=48`, `road_events=72`, `weather_observations=5`.
- `fireguard-ingest-public-bc-context` manual run recorded `lastAttemptTime=2026-05-07T12:22:19.324124Z`.
- `/incidents/current` returned 8 live public evacuation order/alert rows, 10 live public ESS facility rows, and `data_origin=bc_emergencymapbc_public_live`.

## Useful Commands

```bash
gcloud scheduler jobs list \
  --project verdant-upgrade-493301-q1 \
  --location us-central1 \
  --filter='name:fireguard-'

gcloud scheduler jobs run fireguard-sync-fivetran-elastic \
  --project verdant-upgrade-493301-q1 \
  --location us-central1

gcloud scheduler jobs run fireguard-ingest-public-bc-context \
  --project verdant-upgrade-493301-q1 \
  --location us-central1
```
