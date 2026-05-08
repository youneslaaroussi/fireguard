# Data Sources

## Live/Open Sources Through Fivetran

- NASA FIRMS area CSV API for active hotspots. The default BC query uses bbox `-139.2,48.2,-114.0,60.1` with a 2-day lookback so UTC-day quiet periods do not force replay when recent live FIRMS rows exist. Replay mode stores a real historical `VIIRS_NOAA20_SP` CSV snapshot in `data/replay/bc_demo/firms_snapshot.csv` with the MAP_KEY redacted from provenance.
- BC Wildfire current fire perimeters from ArcGIS REST GeoJSON.
- DriveBC/Open511 road events.
- Open-Meteo wind forecasts.
- Google Routes API for route duration and polylines.
- BC Historical Orders and Alerts fire evacuation polygons. The core demo zones are stored in `data/public/bc/historical_fire_evacuation_zones_snapshot.json` with official population/home source fields and simplified geometries.
- BC public evacuation, wildfire, and emergency-alert guidance. Policy snippets are stored in `data/public/bc/official_policy_snippets.json` as paraphrased source-backed retrieval records.
- BC EmergencyMapBC Evacuation Orders and Alerts live ArcGIS query, with stored snapshot fallback.
- BC Emergency Social Services Facilities live ArcGIS query for reception-centre identity, location, type, and public open/closed status. FireGuard blocks closed facilities for evacuee intake. The public layer does not expose shelter capacity.
- Statistics Canada 2021 Census Profile API for age-based vulnerable-population proxy context.
- BC Digital Road Atlas WFS for official public road-network context used in FireGuard's evacuation-access score.

The Fivetran Connector SDK project in `integrations/fivetran/fireguard_connector` emits normalized tables for environmental and road data. FireGuard then syncs those tables into Elastic for geospatial retrieval.
Supplemental BC public emergency context can also be refreshed directly with `POST /ingest/public-bc-context`; this is not a replacement for the Fivetran environmental/road ingestion path.

## Synthetic Or Derived Sources

- unconfirmed shelter capacities; public BC ESS facility data exposes status/location, not live capacity;
- resident-contact placeholders, except configured, operator-checked-in, or Twilio inbound opt-in test recipients;
- dispatch asset availability is not claimed; FireGuard creates an operator task request for dispatch assignment;
- municipal webhook endpoints;
- authorized vulnerable-person registries, household vehicle-ownership feeds, and official transport-access scores. FireGuard can now compute a public source-backed proxy from Statistics Canada and the BC Digital Road Atlas, but it does not claim protected registry data.

Synthetic action endpoints are clearly labeled in the UI and logs. Fire, road, and weather records used in the judged reasoning path must cite a source record or stored replay source snapshot.
Every non-authoritative operational input is also emitted as an `operational_assumptions` record with a fix path, then attached to affected route, plan, action, trace, and Phoenix span records through `assumption_ids`.

Shelter capacity can be updated by a named operator through `POST /shelters/{shelter_id}/capacity-check-in` or the UI `Confirm Capacity` action. It can also be synced from an operator-maintained Google Sheet through `POST /sync/google-sheets-shelter-capacity`. Both paths create auditable `capacity_updates` records and change downstream tracking to an operator-confirmed input. They remain distinct from an official ESS capacity feed unless the operator-maintained sheet is explicitly authorized as that feed. Unconfirmed capacity values are shown as confirmation gates and are not treated as official numeric evidence.

Zone vulnerable/access context can be updated through `POST /sync/source-backed-zone-context`. This creates auditable `zone_updates` records from Statistics Canada Census Profile age structure and BC Digital Road Atlas road-network samples. The output is source-backed and testable, but it remains a public proxy, not an official vulnerable-person registry or household vehicle-access feed.

Resident test contacts can be updated by a named operator through `POST /resident-contacts/test-check-in` or the UI `Add Test Contact` action. They can also be created through the Twilio inbound SMS webhook `POST /resident-contacts/twilio/inbound`: a test recipient texts `JOIN ZONE_A`, `JOIN ZONE_B`, or `JOIN ZONE_C` to the configured Twilio number, and FireGuard stores that inbound consent timestamp and Twilio message SID as `twilio_inbound_opt_in`. API responses expose masked numbers only. SMS execution still requires both non-synthetic contact provenance and a number present in `TWILIO_ALLOWLIST`; this keeps the hackathon demo from messaging arbitrary numbers while proving a real opt-in path.

Dispatch actions do not use seeded demo vehicles anymore. `dispatch_task` payloads request capabilities such as accessible transport and responder support, set `vehicle_availability_claimed=false`, and require a human dispatcher to assign real resources. GitHub Issues can store the real task record, but FireGuard must not claim actual vehicle availability until an authorized dispatch/AVL feed is integrated.
