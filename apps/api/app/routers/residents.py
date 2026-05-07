from __future__ import annotations

from html import escape
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.routers.dependencies import store_dependency
from app.services.privacy import mask_phone
from app.services.store import FireGuardStore
from app.services.time import now_iso

router = APIRouter(prefix="/resident-contacts", tags=["resident-contacts"])

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
ZONE_ALIASES = {
    "A": "ZONE_A",
    "B": "ZONE_B",
    "C": "ZONE_C",
    "ZONEA": "ZONE_A",
    "ZONEB": "ZONE_B",
    "ZONEC": "ZONE_C",
    "ZONE_A": "ZONE_A",
    "ZONE_B": "ZONE_B",
    "ZONE_C": "ZONE_C",
}
JOIN_COMMANDS = {"JOIN", "START", "OPTIN", "OPT-IN"}
LEAVE_COMMANDS = {"LEAVE", "STOP", "UNSUBSCRIBE", "QUIT", "CANCEL", "END"}


class ResidentTestContactCheckIn(BaseModel):
    zone_id: str = Field(min_length=2, max_length=80)
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    updated_by: str = Field(min_length=2, max_length=120)
    consent_label: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=500)


def _public_contact(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "phone"}


def _twiml(message: str) -> Response:
    body = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(message)}</Message></Response>'
    return Response(content=body, media_type="application/xml")


def _clean_zone_token(token: str) -> str:
    return token.upper().replace("-", "_")


def _parse_twilio_command(body: str) -> tuple[str, str | None]:
    tokens = re.findall(r"[A-Za-z0-9_-]+", body.upper())
    if not tokens:
        return "help", None
    command = tokens[0]
    zone_token = _clean_zone_token(tokens[1]) if len(tokens) > 1 else ""
    if command in JOIN_COMMANDS and zone_token:
        return "join", ZONE_ALIASES.get(zone_token)
    if command in LEAVE_COMMANDS:
        return "leave", ZONE_ALIASES.get(zone_token) if zone_token else None
    if command in ZONE_ALIASES:
        return "join", ZONE_ALIASES[command]
    return "help", None


def _validate_twilio_signature(request: Request, form: dict[str, Any], settings: Settings) -> None:
    if not settings.twilio_validate_webhook_signature:
        return
    if not settings.twilio_auth_token:
        raise HTTPException(status_code=503, detail="Twilio webhook signature validation requires TWILIO_AUTH_TOKEN")
    signature = request.headers.get("X-Twilio-Signature")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing Twilio webhook signature")
    try:
        from twilio.request_validator import RequestValidator
    except Exception as exc:  # pragma: no cover - installed with Twilio dependency
        raise HTTPException(status_code=503, detail="Twilio signature validator is unavailable") from exc
    url = settings.twilio_inbound_webhook_public_url or str(request.url)
    validator = RequestValidator(settings.twilio_auth_token)
    if not validator.validate(url, {key: str(value) for key, value in form.items()}, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio webhook signature")


def _twilio_message_sid(form: dict[str, Any], timestamp: str) -> str:
    raw = str(form.get("MessageSid") or form.get("SmsMessageSid") or f"NO_SID_{timestamp}")
    return re.sub(r"[^A-Za-z0-9_:-]", "_", raw)[:120]


def process_twilio_inbound_sms(form: dict[str, Any], settings: Settings, store: FireGuardStore) -> dict[str, Any]:
    timestamp = now_iso()
    from_phone = str(form.get("From") or "").strip()
    body = str(form.get("Body") or "").strip()
    message_sid = _twilio_message_sid(form, timestamp)

    if not E164_RE.match(from_phone):
        return {
            "status": "ignored",
            "response_message": "FireGuard demo could not read your phone number. Text JOIN ZONE_A, JOIN ZONE_B, or JOIN ZONE_C from a valid SMS number.",
        }

    command, zone_id = _parse_twilio_command(body)
    if command == "help" or (command == "join" and not zone_id):
        return {
            "status": "help",
            "masked_phone": mask_phone(from_phone),
            "response_message": "FireGuard demo: text JOIN ZONE_A, JOIN ZONE_B, or JOIN ZONE_C. Text STOP ZONE_A to opt out.",
        }

    if command == "leave":
        zones = [zone_id] if zone_id else [
            resident["zone_id"]
            for resident in store.resident_contacts_with_updates()
            if resident.get("phone") == from_phone and resident.get("contact_source_type") == "twilio_inbound_opt_in"
        ]
        if not zones:
            return {
                "status": "not_found",
                "masked_phone": mask_phone(from_phone),
                "response_message": "FireGuard demo has no active Twilio opt-in for this number. Text JOIN ZONE_A to opt in.",
            }
        updates = []
        for opt_out_zone_id in sorted(set(zones)):
            update_id = f"TWILIO_OPT_OUT_{opt_out_zone_id}_{message_sid}"
            update = {
                "update_id": update_id,
                "resident_id": f"RES_{opt_out_zone_id}_TWILIO",
                "zone_id": opt_out_zone_id,
                "phone": from_phone,
                "masked_phone": mask_phone(from_phone),
                "allowlisted": False,
                "updated_by": "twilio_inbound_sms",
                "updated_at": timestamp,
                "consent_label": f"Inbound Twilio SMS opt-out command received at {timestamp}.",
                "note": "Resident/test recipient opted out through inbound Twilio SMS.",
                "source_type": "twilio_inbound_opt_out",
                "data_origin": "twilio_inbound_resident_opt_out",
                "source_label": "Resident/test recipient opted out by inbound Twilio SMS; not an official resident registry.",
                "official_resident_registry": False,
                "twilio_message_sid": message_sid,
                "opted_in": False,
                "opted_out": True,
            }
            updates.append(_public_contact(store.upsert("contact_updates", update_id, update)))
        return {
            "status": "opted_out",
            "zone_ids": sorted(set(zones)),
            "masked_phone": mask_phone(from_phone),
            "contact_updates": updates,
            "response_message": f"FireGuard demo opt-out recorded for {', '.join(sorted(set(zones)))}. You will not receive demo evacuation texts for that zone unless you opt in again.",
        }

    zone = store.get("evacuation_zones", zone_id)
    if not zone:
        return {
            "status": "unknown_zone",
            "masked_phone": mask_phone(from_phone),
            "response_message": "FireGuard demo does not recognize that zone. Text JOIN ZONE_A, JOIN ZONE_B, or JOIN ZONE_C.",
        }

    allowlisted = from_phone in settings.twilio_allowlist_numbers
    update_id = f"TWILIO_OPT_IN_{zone_id}_{message_sid}"
    update = {
        "update_id": update_id,
        "resident_id": f"RES_{zone_id}_TWILIO",
        "zone_id": zone_id,
        "phone": from_phone,
        "masked_phone": mask_phone(from_phone),
        "allowlisted": allowlisted,
        "updated_by": "twilio_inbound_sms",
        "updated_at": timestamp,
        "consent_label": f"Inbound Twilio SMS opt-in command '{body[:80]}' received at {timestamp}.",
        "note": "Resident/test recipient opted in through inbound Twilio SMS.",
        "source_type": "twilio_inbound_opt_in",
        "data_origin": "twilio_inbound_resident_opt_in",
        "source_label": "Resident/test recipient opted in by texting JOIN to FireGuard's Twilio number; not an official resident registry.",
        "official_resident_registry": False,
        "twilio_message_sid": message_sid,
        "opted_in": True,
        "opted_out": False,
    }
    store.upsert("contact_updates", update_id, update)
    resident = next(
        (contact for contact in store.resident_contacts_with_updates() if contact.get("zone_id") == zone_id),
        None,
    )
    suffix = (
        "This number is allowlisted for demo outbound SMS."
        if allowlisted
        else "This demo only sends outbound SMS to allowlisted test numbers; an operator must allowlist this number before alerts can be sent."
    )
    return {
        "status": "opted_in",
        "zone_id": zone_id,
        "masked_phone": mask_phone(from_phone),
        "allowlisted": allowlisted,
        "contact_update": _public_contact(update),
        "resident_contact": _public_contact(resident or {}),
        "response_message": f"FireGuard demo opt-in recorded for {zone_id}. {suffix} Text STOP {zone_id} to opt out.",
    }


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


@router.post("/twilio/inbound")
async def twilio_inbound_sms(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: FireGuardStore = Depends(store_dependency),
) -> Response:
    form_data = {key: value for key, value in (await request.form()).items()}
    _validate_twilio_signature(request, form_data, settings)
    result = process_twilio_inbound_sms(form_data, settings, store)
    return _twiml(result["response_message"])
