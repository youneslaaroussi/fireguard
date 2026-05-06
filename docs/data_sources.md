# Data Sources

## Live/Open Sources Through Fivetran

- NASA FIRMS area CSV API for active hotspots. Replay mode stores a real historical `VIIRS_NOAA20_SP` CSV snapshot in `data/replay/bc_demo/firms_snapshot.csv` with the MAP_KEY redacted from provenance.
- BC Wildfire current fire perimeters from ArcGIS REST GeoJSON.
- DriveBC/Open511 road events.
- Open-Meteo wind forecasts.
- Google Routes API for route duration and polylines.
- BC Historical Orders and Alerts fire evacuation polygons. The core demo zones are stored in `data/public/bc/historical_fire_evacuation_zones_snapshot.json` with official population/home source fields and simplified geometries.
- BC public evacuation, wildfire, and emergency-alert guidance. Policy snippets are stored in `data/public/bc/official_policy_snippets.json` as paraphrased source-backed retrieval records.

The Fivetran Connector SDK project in `integrations/fivetran/fireguard_connector` emits normalized tables for environmental and road data. FireGuard then syncs those tables into Elastic for geospatial retrieval.

## Synthetic Or Derived Sources

- shelter capacities;
- residents;
- dispatch assets;
- municipal webhook endpoints;
- vulnerability counts and vehicle-access scores derived for the demo from source-backed zones.

Synthetic action endpoints are clearly labeled in the UI and logs. Fire, road, and weather records used in the judged reasoning path must cite a source record or stored replay source snapshot.
