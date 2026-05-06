# Cloud Scheduler Jobs

Fivetran is the production ingestion scheduler. Use Cloud Scheduler only to pull the latest
Fivetran-loaded warehouse rows into Elastic after the Fivetran connection has synced.

```bash
gcloud scheduler jobs create http fireguard-sync-fivetran-to-elastic \
  --schedule "*/15 * * * *" \
  --uri "${API_URL}/sync/fivetran-to-elastic" \
  --http-method POST \
  --location "${GOOGLE_CLOUD_LOCATION}"
```
