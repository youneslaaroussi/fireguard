# Google Sheets Zone Operations Feed

FireGuard can read evacuation-zone vulnerable-population and transportation-access inputs from a Google Sheet. This converts previously derived demo estimates into auditable operator-maintained inputs. It is not an official vulnerable-population registry or transport database unless the sheet is owned and maintained by an authorized operator.

## Share The Sheet

The existing `FireGuard` Google Sheet can be reused because it is already shared with:

```text
fireguard-fivetran-bq@verdant-upgrade-493301-q1.iam.gserviceaccount.com
```

Add a new tab named:

```text
zone_operations
```

## Required Columns

The first row must contain these headers:

```csv
zone_id,vulnerable_count,vehicle_access_score,updated_by,note,updated_at
```

Required:

- `zone_id`
- at least one of `vulnerable_count` or `vehicle_access_score`

Optional:

- `updated_by`
- `note`
- `updated_at`

Valid zone IDs in the BC demo are:

```text
ZONE_A
ZONE_B
ZONE_C
```

`vehicle_access_score` must be between `0` and `1`, where lower means fewer residents can self-evacuate or use private vehicles.

## Suggested Demo Rows

These rows are operator inputs for demo verification, not official registry data:

```csv
ZONE_A,180,0.62,access-branch,operator zone access check,2026-05-07T16:00:00Z
ZONE_B,120,0.68,access-branch,operator zone access check,2026-05-07T16:00:00Z
ZONE_C,275,0.35,access-branch,operator zone access check,2026-05-07T16:00:00Z
```

## Sync

```bash
curl -X POST https://fireguard-api-dovhkdlznq-uc.a.run.app/sync/google-sheets-zone-operations
```

Accepted rows update downstream risk scoring and operational-assumption tracking from `derived_estimate` to `operator_confirmed_not_official_registry`.

## Hosted Verification

On `2026-05-07`, the hosted API read the shared `FireGuard` Sheet, tab `zone_operations`, and synced all three suggested rows.

The hosted sync returned `status=synced`, `updated_count=3`, `skipped_count=0`, and `updated_zone_ids=["ZONE_A","ZONE_B","ZONE_C"]`. The next hosted assessment carried the Sheet-fed values into risk scoring:

- `ZONE_A`: `vulnerable_count=180`, `vehicle_access_score=0.62`
- `ZONE_B`: `vulnerable_count=120`, `vehicle_access_score=0.68`
- `ZONE_C`: `vulnerable_count=275`, `vehicle_access_score=0.35`

The context no longer marks those values as derived estimates.
