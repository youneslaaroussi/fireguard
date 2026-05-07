from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.routers.dependencies import store_dependency
from app.services.privacy import mask_phone
from app.services.store import FireGuardStore
from app.services.time import now_iso

router = APIRouter(prefix="/resident-contacts", tags=["resident-contacts"])


class ResidentTestContactCheckIn(BaseModel):
    zone_id: str = Field(min_length=2, max_length=80)
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    updated_by: str = Field(min_length=2, max_length=120)
    consent_label: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=500)


def _public_contact(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "phone"}


@router.post("/test-check-in")
def resident_test_contact_check_in(
    payload: ResidentTestContactCheckIn,
    settings: Settings = Depends(get_settings),
    store: FireGuardStore = Depends(store_dependency),
) -> dict:
    zone = store.get("evacuation_zones", payload.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Evacuation zone not found")
    if payload.phone not in settings.twilio_allowlist_numbers:
        raise HTTPException(status_code=400, detail="phone must be present in TWILIO_ALLOWLIST before it can be registered")

    timestamp = now_iso()
    update_id = f"CONTACT_{payload.zone_id}_{timestamp}"
    update = {
        "update_id": update_id,
        "resident_id": f"RES_{payload.zone_id}_OPERATOR",
        "zone_id": payload.zone_id,
        "phone": payload.phone,
        "masked_phone": mask_phone(payload.phone),
        "allowlisted": True,
        "updated_by": payload.updated_by,
        "updated_at": timestamp,
        "consent_label": payload.consent_label or "Operator confirmed this is an opt-in, Twilio-verified test recipient.",
        "note": payload.note,
        "source_type": "operator_test_contact_check_in",
        "official_resident_registry": False,
    }
    store.upsert("contact_updates", update_id, update)
    resident = next(
        (contact for contact in store.resident_contacts_with_updates() if contact.get("zone_id") == payload.zone_id),
        None,
    )
    return {
        "contact_update": _public_contact(update),
        "resident_contact": _public_contact(resident or {}),
    }
