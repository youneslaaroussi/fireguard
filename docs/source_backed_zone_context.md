# Source-Backed Zone Context

FireGuard can replace derived demo vulnerable/access values with public source-backed context through:

```text
POST /sync/source-backed-zone-context
```

This sync reads:

- Statistics Canada 2021 Census Profile API for population age structure.
- Government of British Columbia Digital Road Atlas WFS for nearby road-network access.

## What Becomes Real

For each demo zone, the sync writes a `zone_updates` record with:

- `vulnerable_count`: zone population multiplied by the matched Census Profile `65 years and over` ratio.
- `vehicle_access_score`: a computed evacuation-access score from sampled BC Digital Road Atlas road segments around the zone centroid.
- `source_type`: `official_statscan_dra_zone_context`.
- source URLs, Census DGUID/ref-area, road sample counts, class counts, rough/paved/highway kilometres, and nearby closure IDs.

This removes invented vulnerable/access numbers from the decision path.

## What It Does Not Claim

This is not an official vulnerable-person registry, household vehicle-ownership feed, or dispatch availability feed.

The vulnerability number is a real Census-derived proxy. It is suitable for a transparent hackathon decision-support demo, but a production emergency workflow would need authorized aggregate registries or responder-confirmed field intelligence where legally available.

The access score is FireGuard analysis over official public road-network data. It is not a BC government published evacuation-access score.

## Current Zone Profile Mapping

| Zone | Demographic source |
|---|---|
| `ZONE_A` | Statistics Canada 2021 Census Profile, Cariboo census division, `2021A00035941` |
| `ZONE_B` | Statistics Canada 2021 Census Profile, Williams Lake census subdivision, `2021A00055941009` |
| `ZONE_C` | Statistics Canada 2021 Census Profile, Cariboo census division, `2021A00035941` |

## Verification

Run:

```bash
curl -X POST "$API_URL/sync/source-backed-zone-context"
curl "$API_URL/incidents/current"
```

Expected context changes:

- affected zones have `vulnerable_count_estimated=false`;
- affected zones have `vehicle_access_score_estimated=false`;
- `zone_operations_source_type=official_statscan_dra_zone_context`;
- operational assumptions use `INPUT_ZONE_*_SOURCE_BACKED_ZONE_CONTEXT`, not `ASSUMPTION_ZONE_*_VULNERABILITY` or `ASSUMPTION_ZONE_*_VEHICLE_ACCESS`.
