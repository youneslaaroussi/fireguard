# Data Sources

## Live/Open Sources Through Fivetran

- NASA FIRMS area CSV API for active hotspots. Replay mode stores a real historical `VIIRS_NOAA20_SP` CSV snapshot in `data/replay/bc_demo/firms_snapshot.csv` with the MAP_KEY redacted from provenance.
- BC Wildfire current fire perimeters from ArcGIS REST GeoJSON.
- DriveBC/Open511 road events.
- Open-Meteo wind forecasts.
- Google Routes API for route duration and polylines.
- BC Historical Orders and Alerts fire evacuation polygons. The core demo zones are stored in `data/public/bc/historical_fire_evacuation_zones_snapshot.json` with official population/home source fields and simplified geometries.
- BC public evacuation, wildfire, and emergency-alert guidance. Policy snippets are stored in `data/public/bc/official_policy_snippets.json` as paraphrased source-backed retrieval records.
- BC Emergency Social Services Facilities for reception-centre identity, location, type, and public status. The public layer does not expose shelter capacity.

The Fivetran Connector SDK project in `integrations/fivetran/fireguard_connector` emits normalized tables for environmental and road data. FireGuard then syncs those tables into Elastic for geospatial retrieval.

## Synthetic Or Derived Sources

- shelter capacities;
- resident-contact placeholders, except configured or operator-checked-in opt-in Twilio test recipients;
- dispatch asset availability is not claimed; FireGuard creates an operator task request for dispatch assignment;
- municipal webhook endpoints;
- vulnerability counts and vehicle-access scores derived for the demo from source-backed zones.

Synthetic action endpoints are clearly labeled in the UI and logs. Fire, road, and weather records used in the judged reasoning path must cite a source record or stored replay source snapshot.
Every non-authoritative operational input is also emitted as an `operational_assumptions` record with a fix path, then attached to affected route, plan, action, trace, and Phoenix span records through `assumption_ids`.

Shelter capacity can be updated by a named operator through `POST /shelters/{shelter_id}/capacity-check-in` or the UI `Confirm Capacity` action. That creates an auditable `capacity_updates` record and changes downstream tracking to an operator-confirmed input. It remains distinct from an official ESS capacity feed.

Resident test contacts can be updated by a named operator through `POST /resident-contacts/test-check-in` or the UI `Add Test Contact` action. The phone must already be present in `TWILIO_ALLOWLIST`; API responses expose masked numbers only. SMS execution also requires non-synthetic contact provenance, so seeded placeholders cannot send messages just because a number appears in the Twilio allowlist.

Dispatch actions do not use seeded demo vehicles anymore. `dispatch_task` payloads request capabilities such as accessible transport and responder support, set `vehicle_availability_claimed=false`, and require a human dispatcher to assign real resources. GitHub Issues can store the real task record, but FireGuard must not claim actual vehicle availability until an authorized dispatch/AVL feed is integrated.
