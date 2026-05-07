# Google Sheets Shelter Capacity Feed

FireGuard can read shelter capacity from a Google Sheet and convert each row into an auditable `capacity_updates` record. This is a real operator-maintained data feed, but it is not an official ESS capacity feed unless the sheet is owned and maintained by an authorized shelter/operator team.

## Share The Sheet

Share the Google Sheet with the Cloud Run service account:

```text
fireguard-fivetran-bq@verdant-upgrade-493301-q1.iam.gserviceaccount.com
```

Give it Viewer access. Then set:

```text
GOOGLE_SHEETS_CAPACITY_SPREADSHEET_ID=<sheet id>
GOOGLE_SHEETS_CAPACITY_RANGE=shelter_capacity!A:F
```

## Required Columns

The first row must contain these headers:

```csv
shelter_id,capacity_total,capacity_available,updated_by,note,updated_at
```

Required:

- `shelter_id`
- `capacity_available`

Optional:

- `capacity_total`
- `updated_by`
- `note`
- `updated_at`

Valid shelter IDs in the BC demo are:

```text
SHELTER_A
SHELTER_B
SHELTER_C
```

## Sync

```bash
curl -X POST https://fireguard-api-dovhkdlznq-uc.a.run.app/sync/google-sheets-shelter-capacity
```

The sync rejects rows where the shelter ID is unknown, capacity is negative, or available capacity exceeds total capacity. Accepted rows update downstream route/action assumptions from capacity assumptions to operator-maintained Google Sheets inputs.

Capacity cells may be formatted with thousands separators, such as `3,500`; the sync normalizes them to integers before validation.

## Hosted Verification

On `2026-05-07`, the hosted API read the shared `FireGuard` Sheet, tab `shelter_capacity`, and synced this operator row:

```csv
SHELTER_B,3500,3100,railyard-operator,live operator sheet check,2026-05-07T14:00:00Z
```

The hosted sync returned `status=synced`, `updated_count=1`, and `updated_shelter_ids=["SHELTER_B"]`. The next hosted assessment carried `capacity_source_type=google_sheets_capacity_feed` and the generated `capacity_update_id` into the Shelter B notification action payload.
