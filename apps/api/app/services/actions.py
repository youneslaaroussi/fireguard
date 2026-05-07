from __future__ import annotations

import json
import re
import uuid
import urllib.error
import urllib.request
from typing import Any

from app.config import Settings
from app.models.schemas import ActionItem, Approval
from app.services.time import now_iso


MUNICIPAL_TASK_ACTIONS = {"shelter_notify", "road_ops_task", "dispatch_task"}


def github_issue_tasks_enabled(settings: Settings) -> bool:
    return (
        settings.action_task_backend == "github_issues"
        and bool(settings.github_repo)
        and bool(settings.github_token and settings.github_token.strip())
    )


def _action_metadata(action_type: str, settings: Settings | None = None) -> dict[str, Any]:
    if action_type == "resident_sms":
        return {
            "external_system": "twilio_allowlisted_sms",
            "is_simulated_endpoint": False,
            "simulation_label": "Real Twilio SMS when credentials and allowlist match; blocked for non-allowlisted recipients.",
        }
    if action_type in MUNICIPAL_TASK_ACTIONS and settings and github_issue_tasks_enabled(settings):
        return {
            "external_system": "github_issues_operational_task",
            "is_simulated_endpoint": False,
            "simulation_label": "Creates a real GitHub issue in the configured repo as a demo operational task; it is not sent to an official emergency agency.",
        }
    if action_type in MUNICIPAL_TASK_ACTIONS:
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


def create_action(
    bundle_id: str,
    action_type: str,
    target: str,
    message: str,
    payload: dict[str, Any],
    reason: str,
    evidence_ids: list[str],
    confidence: float,
    requires_approval: bool = True,
    settings: Settings | None = None,
    assumption_ids: list[str] | None = None,
) -> ActionItem:
    metadata = _action_metadata(action_type, settings)
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
        assumption_ids=assumption_ids or [],
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
    if action["status"] == "executed":
        return action
    if action["status"] != "approved" and action.get("requires_human_approval", True):
        action["status"] = "failed"
        action["payload"]["execution_error"] = "Action requires approval before execution."
        return action

    if action["action_type"] == "resident_sms":
        zone_residents = [resident for resident in residents if resident["zone_id"] == action["target"]]
        numbers = [resident["phone"] for resident in zone_residents]
        allowed = settings.twilio_allowlist_numbers
        deliverable = [
            resident["phone"]
            for resident in zone_residents
            if resident["phone"] in allowed and resident.get("allowlisted") is True and resident.get("synthetic") is False
        ]
        blocked = [number for number in numbers if number not in deliverable]
        action["payload"]["recipients"] = deliverable
        action["payload"]["blocked_recipients"] = blocked
        action["payload"]["recipient_count"] = len(deliverable)
        action["payload"]["masked_recipients"] = [_mask_phone(number) for number in deliverable]
        action["payload"]["blocked_recipient_reasons"] = [
            {
                "masked_phone": _mask_phone(resident["phone"]),
                "reason": _blocked_recipient_reason(resident, allowed),
            }
            for resident in zone_residents
            if resident["phone"] not in deliverable
        ]
        if blocked and not deliverable:
            action["status"] = "failed"
            action["payload"]["execution_error"] = "No recipients matched TWILIO_ALLOWLIST with operator-confirmed contact provenance."
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

    elif action["action_type"] in MUNICIPAL_TASK_ACTIONS:
        if github_issue_tasks_enabled(settings):
            action.update(_action_metadata(action["action_type"], settings))
            try:
                issue = _create_github_issue(action, settings)
                action["payload"]["delivery_mode"] = "github_issue"
                action["payload"]["github_issue_url"] = issue.get("html_url")
                action["payload"]["github_issue_number"] = issue.get("number")
                action["payload"]["github_issue_api_url"] = issue.get("url")
            except Exception as exc:  # pragma: no cover - live provider dependent
                action["status"] = "failed"
                action["payload"]["delivery_mode"] = "github_issue"
                action["payload"]["execution_error"] = _sanitize_provider_error(str(exc), settings)
                return action
        else:
            action["payload"]["delivery_mode"] = "simulated_webhook"
    else:
        action["payload"]["delivery_mode"] = "internal_log"

    action["status"] = "executed"
    action["executed_at"] = now_iso()
    return action


def _blocked_recipient_reason(resident: dict[str, Any], allowed: set[str]) -> str:
    if resident["phone"] not in allowed:
        return "not_in_twilio_allowlist"
    if resident.get("synthetic") is True:
        return "synthetic_placeholder_contact"
    if resident.get("allowlisted") is not True:
        return "contact_record_not_marked_allowlisted"
    return "not_deliverable"


def _mask_phone(phone: str) -> str:
    if len(phone) <= 5:
        return "***"
    return f"{phone[:2]}***{phone[-4:]}"


def _create_github_issue(action: dict[str, Any], settings: Settings) -> dict[str, Any]:
    if action["payload"].get("github_issue_url"):
        return {
            "html_url": action["payload"].get("github_issue_url"),
            "number": action["payload"].get("github_issue_number"),
            "url": action["payload"].get("github_issue_api_url"),
        }
    title = f"[FireGuard DEMO] {action['action_type'].replace('_', ' ').title()} for {action['target']}"
    body = "\n".join([
        "FireGuard approved action task.",
        "",
        "**Demo safety note:** this GitHub issue is a real task record, but it is not an official emergency-system integration.",
        "",
        f"- Action ID: `{action['action_id']}`",
        f"- Bundle ID: `{action['bundle_id']}`",
        f"- Action type: `{action['action_type']}`",
        f"- Target: `{action['target']}`",
        f"- Confidence: `{action['confidence']}`",
        f"- Reason: {action['reason']}",
        f"- Evidence IDs: `{', '.join(action.get('evidence_ids', []))}`",
        "",
        "Message:",
        "",
        action["message"],
        "",
        "Payload:",
        "",
        "```json",
        json.dumps(action.get("payload", {}), indent=2, sort_keys=True, default=str),
        "```",
    ])
    payload = {"title": title, "body": body}
    request = urllib.request.Request(
        f"{settings.github_api_url.rstrip('/')}/repos/{settings.github_repo}/issues",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.github_token.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "fireguard-demo",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"GitHub issue creation failed with HTTP {exc.code}: {body_text}") from exc


def _sanitize_provider_error(message: str, settings: Settings) -> str:
    sanitized = message
    if settings.github_token:
        token = settings.github_token.strip()
        if token:
            sanitized = sanitized.replace(token, "[REDACTED_GITHUB_TOKEN]")
    sanitized = re.sub(r"gh[opsur]_[A-Za-z0-9_]+", "[REDACTED_GITHUB_TOKEN]", sanitized)
    sanitized = re.sub(r"Bearer\\s+[^'\"\\s]+", "Bearer [REDACTED_GITHUB_TOKEN]", sanitized)
    return sanitized
