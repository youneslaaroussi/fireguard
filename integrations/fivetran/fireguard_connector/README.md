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

The default NASA FIRMS config uses the full BC bbox `-139.2,48.2,-114.0,60.1` and `nasa_firms_day_range=2`. This still comes from the live FIRMS Area API; the 2-day lookback avoids falling into stored replay only because the current UTC day has no BC detections yet. Because FIRMS area queries are rectangular, the connector filters hotspot rows through the official Province of BC boundary WFS before emitting them.

If `nasa_firms_map_key` is empty, fails, or returns zero rows for the configured bbox/lookback, the connector emits the stored NASA FIRMS historical snapshot when that file is available and logs the fallback. The `ingestion_runs.fallback_warnings_json` column records stream-level fallback warnings so the backend and UI can show when replay/snapshot data was used.

## Deploy

```bash
fivetran deploy \
  --api-key "$(printf '%s:%s' "$FIVETRAN_API_KEY" "$FIVETRAN_API_SECRET" | base64 | tr -d '\n')" \
  --destination "$FIVETRAN_DESTINATION_NAME" \
  --connection "$FIVETRAN_CONNECTION_NAME" \
  --configuration configuration.json \
  --python 3.14 \
  --force
```

Use the Fivetran dashboard or REST API to verify sync status, then call FireGuard:

```bash
curl -X POST "$FIREGUARD_API_BASE_URL/sync/fivetran-to-elastic"
```
