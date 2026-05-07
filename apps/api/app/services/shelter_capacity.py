from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote

from app.config import Settings
from app.services.store import FireGuardStore
from app.services.time import now_iso


REQUIRED_HEADERS = {"shelter_id", "capacity_available"}
OPTIONAL_HEADERS = {"capacity_total", "updated_by", "note", "updated_at"}


def google_sheets_capacity_status(store: FireGuardStore) -> dict[str, Any]:
    settings = store.settings
    updates = [
        update
        for update in store.capacity_updates()
        if update.get("source_type") == "google_sheets_capacity_feed"
    ]
    latest = sorted(updates, key=lambda item: item.get("ingested_at") or item.get("updated_at") or "")[-1] if updates else None
    return {
        "provider": "google_sheets",
        "configured": bool(settings.google_sheets_capacity_spreadsheet_id),
        "spreadsheet_id_configured": bool(settings.google_sheets_capacity_spreadsheet_id),
        "range": settings.google_sheets_capacity_range,
        "latest_update_count": len(updates),
        "latest_update_at": latest.get("ingested_at") if latest else None,
    }


def sync_google_sheets_shelter_capacity(store: FireGuardStore) -> dict[str, Any]:
    settings = store.settings
    if not settings.google_sheets_capacity_spreadsheet_id:
        return {
            "provider": "google_sheets",
            "status": "skipped",
            "configured": False,
            "reason": "GOOGLE_SHEETS_CAPACITY_SPREADSHEET_ID is not configured.",
        }

    try:
        values = _read_sheets_values(settings)
    except Exception as exc:  # pragma: no cover - provider/network dependent
        return {
            "provider": "google_sheets",
            "status": "failed",
            "configured": True,
            "range": settings.google_sheets_capacity_range,
            "reason": _provider_error_reason(exc),
        }
    parsed = parse_capacity_sheet_values(values, store)
    for update in parsed["updates"]:
        store.upsert("capacity_updates", update["update_id"], update)
    return {
        "provider": "google_sheets",
        "status": "synced" if not parsed["errors"] else "partial",
        "configured": True,
        "range": settings.google_sheets_capacity_range,
        "updated_count": len(parsed["updates"]),
        "skipped_count": len(parsed["errors"]),
        "errors": parsed["errors"],
        "updated_shelter_ids": [update["shelter_id"] for update in parsed["updates"]],
        "ingested_at": parsed["ingested_at"],
    }


def parse_capacity_sheet_values(values: list[list[Any]], store: FireGuardStore) -> dict[str, Any]:
    ingested_at = now_iso()
    if not values:
        return {"updates": [], "errors": [{"row": 0, "reason": "Sheet range returned no rows."}], "ingested_at": ingested_at}

    headers = [_normalize_header(value) for value in values[0]]
    missing = sorted(REQUIRED_HEADERS - set(headers))
    if missing:
        return {
            "updates": [],
            "errors": [{"row": 1, "reason": f"Missing required headers: {', '.join(missing)}."}],
            "ingested_at": ingested_at,
        }

    updates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row_number, row in enumerate(values[1:], start=2):
        record = _row_to_record(headers, row)
        if not any(str(value).strip() for value in record.values()):
            continue
        shelter_id = str(record.get("shelter_id") or "").strip()
        shelter = store.get("shelters", shelter_id)
        if not shelter:
            errors.append({"row": row_number, "shelter_id": shelter_id, "reason": "Shelter not found."})
            continue
        try:
            capacity_available = _parse_non_negative_int(record.get("capacity_available"))
            capacity_total = (
                _parse_non_negative_int(record.get("capacity_total"))
                if str(record.get("capacity_total") or "").strip()
                else int(shelter.get("capacity_total", capacity_available))
            )
        except ValueError as exc:
            errors.append({"row": row_number, "shelter_id": shelter_id, "reason": str(exc)})
            continue
        if capacity_available > capacity_total:
            errors.append({
                "row": row_number,
                "shelter_id": shelter_id,
                "reason": "capacity_available cannot exceed capacity_total.",
            })
            continue

        updated_at = str(record.get("updated_at") or "").strip() or ingested_at
        updated_by = str(record.get("updated_by") or "").strip() or "google_sheets_capacity_feed"
        row_hash = hashlib.sha256(f"{shelter_id}:{updated_at}:{capacity_available}:{capacity_total}".encode()).hexdigest()[:12]
        update_id = f"SHEETS_CAPACITY_{shelter_id}_{row_hash}"
        source_label = (
            f"Google Sheets shelter capacity feed row by {updated_by} at {updated_at}; "
            "not an official public ESS capacity feed unless the sheet owner is an authorized operator."
        )
        updates.append({
            "update_id": update_id,
            "shelter_id": shelter_id,
            "capacity_total": capacity_total,
            "capacity_available": capacity_available,
            "updated_by": updated_by,
            "updated_at": updated_at,
            "ingested_at": ingested_at,
            "note": str(record.get("note") or "").strip() or None,
            "source_type": "google_sheets_capacity_feed",
            "source_label": source_label,
            "official_capacity_feed": False,
            "spreadsheet_range": store.settings.google_sheets_capacity_range,
        })
    return {"updates": updates, "errors": errors, "ingested_at": ingested_at}


def _read_sheets_values(settings: Settings) -> list[list[Any]]:
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _project = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    session = AuthorizedSession(credentials)
    spreadsheet_id = quote(settings.google_sheets_capacity_spreadsheet_id or "", safe="")
    range_name = quote(settings.google_sheets_capacity_range, safe="")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_name}?valueRenderOption=UNFORMATTED_VALUE"
    response = session.get(url, timeout=20)
    response.raise_for_status()
    payload = response.json()
    return payload.get("values", [])


def _normalize_header(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")


def _row_to_record(headers: list[str], row: list[Any]) -> dict[str, Any]:
    return {header: row[index] if index < len(row) else "" for index, header in enumerate(headers) if header in REQUIRED_HEADERS | OPTIONAL_HEADERS}


def _parse_non_negative_int(value: Any) -> int:
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError("Required capacity value is blank.")
    parsed = int(float(text))
    if parsed < 0:
        raise ValueError("Capacity values must be non-negative.")
    return parsed


def _provider_error_reason(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 404:
        return "Spreadsheet or range was not found, or the Cloud Run service account does not have access."
    if status_code == 403:
        return "Sheets API denied access for the Cloud Run service account."
    if status_code:
        return f"Sheets API request failed with HTTP {status_code}."
    return str(exc)[:300]
