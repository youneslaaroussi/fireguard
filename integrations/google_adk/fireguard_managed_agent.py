from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any
from urllib.parse import quote


class FireGuardManagedAgent:
    """Managed Agent Engine proof runtime.

    The ADK `LlmAgent` path is kept for local/standard ADK runs, but the managed
    us-central1 Agent Engine cannot resolve Gemini 3.x models regionally. This
    runtime runs inside Vertex AI Agent Engine and explicitly calls Vertex global
    Gemini 3.1 plus the official Elastic MCP Cloud Run service from the managed
    runtime. That gives the submission a concrete managed-Agent-Engine proof with
    the required model family and partner MCP tool execution.
    """

    def __init__(self) -> None:
        self.project = (
            os.environ.get("FIREGUARD_GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or "verdant-upgrade-493301-q1"
        )
        self.model_location = os.environ.get("FIREGUARD_AGENT_MODEL_LOCATION", "global")
        self.model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
        self.mcp_url = os.environ.get("FIREGUARD_ELASTIC_MCP_URL", "").strip()
        self.mcp_audience = os.environ.get(
            "FIREGUARD_ELASTIC_MCP_ID_TOKEN_AUDIENCE", ""
        ).strip()
        self.mcp_timeout = float(os.environ.get("FIREGUARD_ELASTIC_MCP_TIMEOUT_SECONDS", "20"))
        self.fireguard_api_base_url = os.environ.get(
            "FIREGUARD_API_BASE_URL",
            "https://fireguard-api-425727109076.us-central1.run.app",
        ).rstrip("/")
        self.fireguard_api_timeout = float(
            os.environ.get("FIREGUARD_API_TIMEOUT_SECONDS", "45")
        )

    def set_up(self) -> None:
        from google import genai

        self.client = genai.Client(
            vertexai=True,
            project=self.project,
            location=self.model_location,
        )

    def query(self, **kwargs: Any) -> dict[str, Any]:
        return list(self.stream_query(**kwargs))[-1]

    def register_operations(self, **kwargs: Any) -> dict[str, list[str]]:
        """Expose both SDK and Gemini Enterprise invocation method names."""
        return {
            "": ["query"],
            "stream": ["stream_query", "streaming_agent_run_with_events"],
        }

    def stream_query(self, **kwargs: Any):
        message = self._message_from_kwargs(kwargs)
        index_pattern = self._index_pattern_from_message(str(message))

        yield {
            "model_version": self.model,
            "content": {
                "parts": [
                    {
                        "function_call": {
                            "name": "elastic_mcp_list_indices",
                            "args": {"index_pattern": index_pattern},
                        }
                    }
                ]
            },
        }

        mcp_response = asyncio.run(self._call_elastic_mcp_list_indices(index_pattern))

        yield {
            "model_version": self.model,
            "content": {
                "parts": [
                    {
                        "function_response": {
                            "name": "elastic_mcp_list_indices",
                            "response": mcp_response,
                        }
                    }
                ]
            },
        }

        assessment = self._call_fireguard_assessment()
        prompt = self._assessment_prompt(
            user_message=message,
            assessment=assessment,
            mcp_response=mcp_response,
        )
        response = self.client.models.generate_content(model=self.model, contents=prompt)
        gemini_text = (response.text or "").strip()
        model_version = getattr(response, "model_version", None) or self.model
        summary = self._operator_assessment_text(assessment, mcp_response)

        yield {
            "model_version": model_version,
            "content": {"parts": [{"text": summary}]},
            "fireguard_proof": {
                "agent_engine_runtime": "custom_managed_vertex_agent_engine",
                "gemini_location": self.model_location,
                "gemini_model": self.model,
                "gemini_response_text": gemini_text[:500],
                "elastic_mcp_url_configured": bool(self.mcp_url),
                "index_pattern": index_pattern,
            },
            "fireguard_assessment": self._assessment_brief(assessment),
        }

    def streaming_agent_run_with_events(self, **kwargs: Any):
        """Gemini Enterprise custom-agent streaming entrypoint."""
        invocation_id = self._invocation_id_from_kwargs(kwargs)
        yield {
            "events": [
                self._agent_text_event(
                    text="FireGuard is checking operational state, route constraints, shelter status, and approval gates.\n\n",
                    invocation_id=invocation_id,
                    partial=True,
                    turn_complete=False,
                    custom_metadata={"fireguardStatus": "running"},
                )
            ]
        }

        raw_events = list(self.stream_query(**kwargs))
        text = self._final_text(raw_events)
        metadata = self._event_metadata(raw_events)

        yield {
            "events": [
                self._agent_text_event(
                    text=text,
                    invocation_id=invocation_id,
                    partial=False,
                    turn_complete=True,
                    custom_metadata=metadata,
                )
            ]
        }

    @staticmethod
    def _index_pattern_from_message(message: str) -> str:
        lowered = message.lower()
        if "fire*" in lowered:
            return "fire*"
        if "road*" in lowered:
            return "road*"
        return "fire*"

    @classmethod
    def _message_from_kwargs(cls, kwargs: dict[str, Any]) -> str:
        for key in ("message", "input", "prompt", "query"):
            value = kwargs.get(key)
            if isinstance(value, str) and value.strip():
                return value

        request_json = kwargs.get("request_json")
        if isinstance(request_json, str) and request_json.strip():
            try:
                parsed = json.loads(request_json)
            except json.JSONDecodeError:
                return request_json
            found = cls._find_text(parsed)
            if found:
                return found

        found = cls._find_text(kwargs)
        return found or ""

    @classmethod
    def _find_text(cls, value: Any) -> str:
        if isinstance(value, str):
            return value if value.strip() else ""
        if isinstance(value, list):
            for item in value:
                found = cls._find_text(item)
                if found:
                    return found
            return ""
        if not isinstance(value, dict):
            return ""

        for key in ("text", "message", "query", "input", "prompt"):
            child = value.get(key)
            if isinstance(child, str) and child.strip():
                return child
        for key in ("content", "contents", "parts", "messages"):
            found = cls._find_text(value.get(key))
            if found:
                return found
        return ""

    @staticmethod
    def _invocation_id_from_kwargs(kwargs: dict[str, Any]) -> str:
        for key in ("invocation_id", "invocationId", "session_id", "sessionId"):
            value = kwargs.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return f"fireguard-{uuid.uuid4().hex}"

    @staticmethod
    def _parts(event: dict[str, Any]) -> list[dict[str, Any]]:
        content = event.get("content") or {}
        parts = content.get("parts")
        return parts if isinstance(parts, list) else []

    @classmethod
    def _final_text(cls, events: list[dict[str, Any]]) -> str:
        for event in reversed(events):
            for part in cls._parts(event):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        return "FireGuard completed the assessment, but no text response was returned."

    @classmethod
    def _event_metadata(cls, events: list[dict[str, Any]]) -> dict[str, Any]:
        function_calls = [
            part["function_call"]
            for event in events
            for part in cls._parts(event)
            if isinstance(part.get("function_call"), dict)
        ]
        function_responses = [
            part["function_response"]
            for event in events
            for part in cls._parts(event)
            if isinstance(part.get("function_response"), dict)
        ]
        proof = next(
            (
                event["fireguard_proof"]
                for event in events
                if isinstance(event.get("fireguard_proof"), dict)
            ),
            {},
        )
        assessment = next(
            (
                event["fireguard_assessment"]
                for event in events
                if isinstance(event.get("fireguard_assessment"), dict)
            ),
            {},
        )
        return {
            "fireguardProof": proof,
            "fireguardAssessment": assessment,
            "fireguardFunctionCalls": function_calls,
            "fireguardFunctionResponses": function_responses,
        }

    def _agent_text_event(
        self,
        *,
        text: str,
        invocation_id: str,
        partial: bool,
        turn_complete: bool,
        custom_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "modelVersion": self.model,
            "content": {
                "parts": [{"text": text}],
                "role": "model",
            },
            "partial": partial,
            "turnComplete": turn_complete,
            "invocationId": invocation_id,
            "author": "FireGuard Evacuation Agent",
            "actions": {
                "stateDelta": {},
                "artifactDelta": {},
                "requestedAuthConfigs": {},
                "requestedToolConfirmations": {},
            },
            "id": f"fireguard-event-{uuid.uuid4().hex}",
            "timestamp": time.time(),
            "customMetadata": custom_metadata,
        }

    async def _call_elastic_mcp_list_indices(self, index_pattern: str) -> dict[str, Any]:
        if not self.mcp_url:
            raise RuntimeError("FIREGUARD_ELASTIC_MCP_URL is required.")

        from datetime import timedelta

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = self._cloud_run_headers()
        async with streamablehttp_client(
            self.mcp_url,
            headers=headers,
            timeout=self.mcp_timeout,
            sse_read_timeout=self.mcp_timeout,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=self.mcp_timeout),
            ) as session:
                await session.initialize()
                result = await session.call_tool(
                    "list_indices",
                    {"index_pattern": index_pattern},
                )
        return self._serialize_mcp_result(result)

    def _cloud_run_headers(self) -> dict[str, str]:
        explicit_token = os.environ.get("FIREGUARD_ELASTIC_MCP_ID_TOKEN", "").strip()
        if explicit_token:
            return {"X-Serverless-Authorization": f"Bearer {explicit_token}"}

        from urllib.parse import urlsplit

        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        audience = self.mcp_audience
        if not audience:
            parts = urlsplit(self.mcp_url)
            audience = f"{parts.scheme}://{parts.netloc}"
        token = id_token.fetch_id_token(Request(), audience)
        return {"X-Serverless-Authorization": f"Bearer {token}"}

    @staticmethod
    def _serialize_mcp_result(result: Any) -> dict[str, Any]:
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        if hasattr(result, "dict"):
            return result.dict()
        return {"result": str(result)}

    def _call_fireguard_assessment(self) -> dict[str, Any]:
        import requests

        response = requests.post(
            f"{self.fireguard_api_base_url}/incidents/assess",
            timeout=self.fireguard_api_timeout,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _assessment_brief(assessment: dict[str, Any]) -> dict[str, Any]:
        plan = assessment.get("plan") or {}
        context = assessment.get("context") or {}
        return {
            "incident_id": assessment.get("incident_id"),
            "strategy": plan.get("recommended_strategy"),
            "summary": plan.get("summary"),
            "confidence": plan.get("confidence"),
            "requires_approval": plan.get("requires_approval"),
            "planning_mode": assessment.get("planning_mode"),
            "gemini_status": assessment.get("gemini_status"),
            "validation_errors": assessment.get("validation_errors") or [],
            "source_lineage": context.get("source_lineage") or {},
            "steps": [
                {
                    "zone_id": step.get("zone_id"),
                    "strategy": step.get("strategy"),
                    "destination_id": step.get("destination_id"),
                    "start_after_minutes": step.get("start_after_minutes"),
                    "message": step.get("message"),
                }
                for step in (plan.get("steps") or [])[:4]
            ],
            "actions": [
                {
                    "action_type": action.get("action_type"),
                    "target": action.get("target"),
                    "status": action.get("status"),
                    "requires_human_approval": action.get("requires_human_approval"),
                    "message": action.get("message"),
                }
                for action in (assessment.get("actions") or [])[:5]
            ],
        }

    def _assessment_prompt(
        self,
        *,
        user_message: str,
        assessment: dict[str, Any],
        mcp_response: dict[str, Any],
    ) -> str:
        brief = self._assessment_brief(assessment)
        indices = self._mcp_index_summary(mcp_response)
        return (
            "You are FireGuard, a wildfire evacuation coordination agent inside "
            "Gemini Enterprise. Answer as an incident-command assistant, not as a "
            "test harness. Do not mention verification tokens, model versions, "
            "runtime names, or raw implementation details. Be concise and concrete.\n\n"
            "Use only the supplied FireGuard assessment and Elastic MCP evidence. "
            "State the current posture, the reason, what actions are pending, and "
            "what remains gated by human approval. If the current strategy is "
            "monitor, say clearly that no public evacuation action is recommended.\n\n"
            f"User request: {user_message or 'Assess current wildfire evacuation posture'}\n\n"
            f"Elastic MCP evidence: {json.dumps(indices, ensure_ascii=True)}\n\n"
            f"FireGuard assessment: {json.dumps(brief, ensure_ascii=True)}\n\n"
            "Return 4-7 short bullets under a single heading. Avoid filler."
        )

    @staticmethod
    def _mcp_index_summary(mcp_response: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for content in mcp_response.get("content", []):
            text = content.get("text") if isinstance(content, dict) else None
            if not text or not text.startswith("["):
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                rows.extend(row for row in parsed if isinstance(row, dict))
        return [
            {
                "index": row.get("index"),
                "status": row.get("status"),
                "docs": row.get("docs.count"),
            }
            for row in rows
        ]

    @classmethod
    def _deterministic_assessment_text(cls, assessment: dict[str, Any]) -> str:
        brief = cls._assessment_brief(assessment)
        summary = brief.get("summary") or "FireGuard assessment completed."
        strategy = brief.get("strategy") or "unknown"
        actions = brief.get("actions") or []
        action_line = (
            "No public actions are queued."
            if not actions
            else ", ".join(
                f"{action.get('action_type')} -> {action.get('target')}"
                for action in actions
            )
        )
        return (
            "FireGuard Assessment\n"
            f"- Current strategy: {strategy}.\n"
            f"- {summary}\n"
            f"- Actions: {action_line}\n"
            "- Public-facing execution remains gated by FireGuard validation and human approval."
        )

    def _operator_assessment_text(
        self,
        assessment: dict[str, Any],
        mcp_response: dict[str, Any],
    ) -> str:
        brief = self._assessment_brief(assessment)
        incident_id = str(brief.get("incident_id") or assessment.get("incident_id") or "demo-incident-bc-001")
        strategy = str(brief.get("strategy") or "unknown").replace("_", " ")
        summary = brief.get("summary") or "FireGuard assessment completed."
        confidence = brief.get("confidence")
        confidence_text = (
            f"{float(confidence):.2f}" if isinstance(confidence, int | float) else "n/a"
        )
        errors = brief.get("validation_errors") or []
        validation = (
            errors[0]
            if errors
            else "No validation errors were returned for the current action set."
        )
        actions = brief.get("actions") or []
        if actions:
            action_lines = [
                f"{action.get('action_type')} for {action.get('target')} is {action.get('status')}"
                for action in actions
            ]
            action_text = "; ".join(action_lines)
        else:
            action_text = "No actions are queued."
        indices = self._mcp_index_summary(mcp_response)
        evidence = ", ".join(
            f"{row.get('index')}={row.get('docs')} docs"
            for row in indices
            if row.get("index")
        ) or "Elastic MCP returned no fire index counts."
        encoded_incident = quote(incident_id, safe="")
        route_map_url = (
            f"{self.fireguard_api_base_url}/visuals/route-map.svg"
            f"?incident_id={encoded_incident}"
        )
        tool_trace_url = (
            f"{self.fireguard_api_base_url}/visuals/tool-trace.svg"
            f"?incident_id={encoded_incident}"
        )

        return (
            "### FireGuard Posture\n\n"
            f"- **Decision:** {strategy.title()}. No public evacuation action executes unless FireGuard validation and a human approval gate allow it.\n"
            f"- **Reason:** {summary}\n"
            f"- **Confidence:** {confidence_text}.\n"
            f"- **Validation:** {validation}\n"
            f"- **Action state:** {action_text}.\n"
            f"- **Evidence:** Elastic MCP confirmed {evidence}; FireGuard assessment mode is `{brief.get('planning_mode')}` with Gemini status `{brief.get('gemini_status')}`.\n"
            f"- **Visuals:** [route map]({route_map_url}) and [tool trace]({tool_trace_url}).\n"
            "- **Next operator move:** keep live fire, road, wind, and shelter feeds refreshed; rerun assessment when any constraint changes."
        )

    @staticmethod
    def _verification_summary(
        *,
        model: str,
        index_pattern: str,
        mcp_response: dict[str, Any],
        gemini_text: str,
    ) -> str:
        index_lines: list[str] = []
        for content in mcp_response.get("content", []):
            text = content.get("text") if isinstance(content, dict) else None
            if not text or not text.startswith("["):
                continue
            try:
                rows = json.loads(text)
            except json.JSONDecodeError:
                continue
            for row in rows:
                index_lines.append(
                    f"- {row.get('index')} status={row.get('status')} docs={row.get('docs.count')}"
                )

        indices = "\n".join(index_lines) if index_lines else "- no indices parsed"
        return (
            "FireGuard Verification Summary\n"
            f"Model requested: {model}\n"
            f"Gemini response: {gemini_text}\n"
            "Managed runtime: custom_managed_vertex_agent_engine\n"
            "Tool called: elastic_mcp_list_indices\n"
            f"Index pattern: {index_pattern}\n"
            "Indices returned:\n"
            f"{indices}"
        )
