from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.services.phoenix import trace_arize_ax_span, trace_tool_span
from app.services.time import now_iso


class TraceRecorder:
    def __init__(self, incident_id: str, settings: Settings | None = None):
        self.incident_id = incident_id
        self.settings = settings or get_settings()
        self.events: list[dict[str, Any]] = []
        self.phoenix_trace_ids: list[str] = []
        self.arize_ax_trace_ids: list[str] = []

    def add(
        self,
        step: str,
        tool: str,
        inputs: dict[str, Any],
        output: Any,
        evidence_ids: list[str] | None = None,
        assumption_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        event_id = f"trace-{len(self.events) + 1:03d}"
        evidence = evidence_ids or []
        assumptions = assumption_ids or []
        phoenix_trace_id = trace_tool_span(
            self.settings,
            self.incident_id,
            event_id,
            step,
            tool,
            inputs,
            output,
            evidence,
            assumptions,
        )
        if phoenix_trace_id:
            self.phoenix_trace_ids.append(phoenix_trace_id)
        arize_ax_trace_id = trace_arize_ax_span(
            self.settings,
            self.incident_id,
            event_id,
            step,
            tool,
            inputs,
            output,
            evidence,
            assumptions,
        )
        if arize_ax_trace_id:
            self.arize_ax_trace_ids.append(arize_ax_trace_id)
        event = {
            "event_id": event_id,
            "incident_id": self.incident_id,
            "step": step,
            "tool": tool,
            "inputs": inputs,
            "output": output,
            "evidence_ids": evidence,
            "assumption_ids": assumptions,
            "phoenix_trace_id": phoenix_trace_id,
            "arize_ax_trace_id": arize_ax_trace_id,
            "created_at": now_iso(),
        }
        self.events.append(event)
        return event
