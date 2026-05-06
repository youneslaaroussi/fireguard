# FireGuard Fivetran Connector

This Connector SDK project makes Fivetran the production ingestion layer for FireGuard.

## Streams

- `fire_hotspots`
- `fire_perimeters`
- `road_events`
- `weather_observations`
- `ingestion_runs`

## Local Debug

```bash
cd integrations/fivetran/fireguard_connector
python3 -m venv .venv
. .venv/bin/activate
pip install "fivetran-connector-sdk==2.8.1" -r requirements.txt
cp configuration.json.example configuration.json
fivetran debug . --configuration configuration.json
```

If `nasa_firms_map_key` is empty, the connector emits replay-shaped FIRMS rows so the connector can still be debugged before secrets are available.

## Deploy

```bash
fivetran deploy \
  --api-key "$FIVETRAN_API_KEY:$FIVETRAN_API_SECRET" \
  --destination "$FIVETRAN_DESTINATION_NAME" \
  --connection "$FIVETRAN_CONNECTION_NAME" \
  --configuration configuration.json \
  --python 3.12
```

Use the Fivetran dashboard or REST API to verify sync status, then call FireGuard:

```bash
curl -X POST "$FIREGUARD_API_BASE_URL/sync/fivetran-to-elastic"
```
