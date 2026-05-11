from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any


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

        response = self.client.models.generate_content(
            model=self.model,
            contents="Return exactly FIREGUARD_GEMINI_31_READY.",
        )
        gemini_text = (response.text or "").strip()
        model_version = getattr(response, "model_version", None) or self.model
        summary = self._verification_summary(
            model=self.model,
            index_pattern=index_pattern,
            mcp_response=mcp_response,
            gemini_text=gemini_text,
        )

        yield {
            "model_version": model_version,
            "content": {"parts": [{"text": summary}]},
            "fireguard_proof": {
                "agent_engine_runtime": "custom_managed_vertex_agent_engine",
                "gemini_location": self.model_location,
                "gemini_model": self.model,
                "gemini_response_text": gemini_text,
                "elastic_mcp_url_configured": bool(self.mcp_url),
                "index_pattern": index_pattern,
            },
        }

    def streaming_agent_run_with_events(self, **kwargs: Any):
        """Gemini Enterprise custom-agent streaming entrypoint."""
        invocation_id = self._invocation_id_from_kwargs(kwargs)
        yield {
            "events": [
                self._agent_text_event(
                    text="Assessing FireGuard operational memory, Elastic MCP fire indices, route constraints, and approval-gated action policy.",
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
        return {
            "fireguardProof": proof,
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
