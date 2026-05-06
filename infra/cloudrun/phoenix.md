# Self-Hosted Phoenix On Cloud Run

FireGuard uses a self-hosted Arize Phoenix service when Phoenix Cloud credentials are not valid.

Current hosted demo:

- Cloud Run service: `fireguard-phoenix`
- Phoenix URL: `https://fireguard-phoenix-dovhkdlznq-uc.a.run.app`
- Storage: Cloud SQL PostgreSQL
- Cloud SQL instance: `verdant-upgrade-493301-q1:us-central1:fireguard-phoenix-pg`
- Database/user: `phoenix`
- Secret Manager secret: `phoenix-sql-database-url`

The Phoenix container receives `PHOENIX_SQL_DATABASE_URL` from Secret Manager and connects through the Cloud Run Cloud SQL Unix socket. Do not commit the database URL or password.

Verification commands:

```bash
gcloud run services describe fireguard-phoenix \
  --region us-central1 \
  --project verdant-upgrade-493301-q1 \
  --format='value(status.latestReadyRevisionName,status.conditions[0].status)'

gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="fireguard-phoenix"' \
  --project verdant-upgrade-493301-q1 \
  --limit=50 \
  --format='value(timestamp,textPayload)' | rg 'Storage: postgresql|Migrations completed'

curl -sS https://fireguard-phoenix-dovhkdlznq-uc.a.run.app/v1/projects
```

The API should report:

```json
{
  "deployment": "self_hosted",
  "storage_backend": "cloud_sql_postgresql",
  "connection_check": {
    "status": "ok"
  }
}
```
