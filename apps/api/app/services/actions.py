from __future__ import annotations

import uuid
from typing import Any

from app.config import Settings
from app.models.schemas import ActionItem, Approval
from app.services.time import now_iso


def _action_metadata(action_type: str) -> dict[str, Any]:
    if action_type == "resident_sms":
        return {
            "external_system": "twilio_allowlisted_sms",
            "is_simulated_endpoint": False,
            "simulation_label": "Real Twilio SMS when credentials and allowlist match; blocked for non-allowlisted recipients.",
        }
    if action_type in {"shelter_notify", "road_ops_task", "dispatch_task"}:
        return {
            "external_system": "simulated_municipal_webhook",
            "is_simulated_endpoint": True,
            "simulation_label": "Simulated municipal endpoint for hackathon safety; payload is logged but not sent to an official agency.",
        }
    return {
        "external_system": "internal_fireguard_log",
        "is_simulated_endpoint": False,
        "simulation_label": None,
    }


def create_action(bundle_id: str, action_type: str, target: str, message: str, payload: dict[str, Any], reason: str, evidence_ids: list[str], confidence: float, requires_approval: bool = True) -> ActionItem:
    metadata = _action_metadata(action_type)
    return ActionItem(
        action_id=f"ACTION_{uuid.uuid4().hex[:10].upper()}",
        bundle_id=bundle_id,
        action_type=action_type,
        target=target,
        status="pending",
        message=message,
        payload=payload,
        reason=reason,
        evidence_ids=evidence_ids,
        confidence=confidence,
        external_system=metadata["external_system"],
        is_simulated_endpoint=metadata["is_simulated_endpoint"],
        simulation_label=metadata["simulation_label"],
        requires_human_approval=requires_approval,
        created_at=now_iso(),
    )


def create_approval(bundle_id: str, approver_role: str = "incident_commander") -> Approval:
    approval_id = f"APPROVAL_{uuid.uuid4().hex[:8].upper()}"
    return Approval(
        approval_id=approval_id,
        bundle_id=bundle_id,
        status="pending",
        approver_role=approver_role,
        approval_url=f"http://localhost:3000?approval={approval_id}",
        created_at=now_iso(),
    )


def approve_actions(actions: list[dict[str, Any]], approval: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timestamp = now_iso()
    approval["status"] = "approved"
    approval["decided_at"] = timestamp
    for action in actions:
        if action.get("requires_human_approval", True):
            action["status"] = "approved"
            action["approved_at"] = timestamp
    return actions, approval


def reject_actions(actions: list[dict[str, Any]], approval: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timestamp = now_iso()
    approval["status"] = "rejected"
    approval["decided_at"] = timestamp
    for action in actions:
        action["status"] = "rejected"
    return actions, approval


def execute_action(action: dict[str, Any], settings: Settings, residents: list[dict[str, Any]]) -> dict[str, Any]:
    if action["status"] != "approved" and action.get("requires_human_approval", True):
        action["status"] = "failed"
        action["payload"]["execution_error"] = "Action requires approval before execution."
        return action

    if action["action_type"] == "resident_sms":
        numbers = [resident["phone"] for resident in residents if resident["zone_id"] == action["target"]]
        allowed = settings.twilio_allowlist_numbers
        blocked = [number for number in numbers if number not in allowed]
        deliverable = [number for number in numbers if number in allowed]
        action["payload"]["recipients"] = deliverable
        action["payload"]["blocked_recipients"] = blocked
        if blocked and not deliverable:
            action["status"] = "failed"
            action["payload"]["execution_error"] = "No recipients matched TWILIO_ALLOWLIST."
            return action
        if settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number:
            try:
                from twilio.rest import Client

                client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
                sent_messages = []
                failed_messages = []
                for number in deliverable:
                    try:
                        message = client.messages.create(
                            body=action["message"],
                            from_=settings.twilio_from_number,
                            to=number,
                        )
                        sent_messages.append({"to": number, "sid": message.sid, "status": message.status})
                    except Exception as exc:  # pragma: no cover - depends on live Twilio account state
                        failed_messages.append({"to": number, "error": str(exc)})
                action["payload"]["delivery_mode"] = "twilio"
                action["payload"]["twilio_messages"] = sent_messages
                action["payload"]["twilio_failures"] = failed_messages
                if failed_messages and not sent_messages:
                    action["status"] = "failed"
                    action["payload"]["execution_error"] = "Twilio rejected every message attempt."
                    return action
            except Exception as exc:  # pragma: no cover - depends on live Twilio account state
                action["status"] = "failed"
                action["payload"]["delivery_mode"] = "twilio"
                action["payload"]["execution_error"] = str(exc)
                return action
        else:
            action["payload"]["delivery_mode"] = "simulated_sms_no_twilio_credentials"

    elif action["action_type"] in {"shelter_notify", "road_ops_task", "dispatch_task"}:
        action["payload"]["delivery_mode"] = "simulated_webhook"
    else:
        action["payload"]["delivery_mode"] = "internal_log"

    action["status"] = "executed"
    action["executed_at"] = now_iso()
    return action
