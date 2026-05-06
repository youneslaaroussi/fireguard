# Data Sources

## Live/Open Sources Through Fivetran

- NASA FIRMS area CSV API for active hotspots.
- BC Wildfire current fire perimeters from ArcGIS REST GeoJSON.
- DriveBC/Open511 road events.
- Open-Meteo wind forecasts.
- Google Routes API for route duration and polylines.

The Fivetran Connector SDK project in `integrations/fivetran/fireguard_connector` emits normalized tables for environmental and road data. FireGuard then syncs those tables into Elastic for geospatial retrieval.

## Synthetic Sources

- evacuation zones;
- shelters;
- residents;
- dispatch assets;
- municipal webhook endpoints;
- emergency policy snippets.

Synthetic action endpoints are clearly labeled in the UI and logs. Fire, road, and weather records used in the judged reasoning path must cite a source record or replay source snapshot.
