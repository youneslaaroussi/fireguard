from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import google.auth
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import ORJSONResponse, StreamingResponse
from google.auth.transport.requests import Request as AuthRequest
from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.tool_models import ToolInvocation
from app.agent_runtime.tools import build_base_tool_registry


FIREGUARD_AGENT_ID = "fireguard_adk_agent"
DATA_CHECKS_NODE_ID = "data_checks"
WORKFLOW_ID = "fireguard_adk"
WORKFLOW_NODES = [
    {"node_id": "human_trigger", "label": "Trigger", "config": {"kind": "human_trigger"}},
    {"node_id": DATA_CHECKS_NODE_ID, "label": "Data Checks", "config": {"kind": "agent", "agent_id": DATA_CHECKS_NODE_ID}},
    {"node_id": FIREGUARD_AGENT_ID, "label": "ADK Agent", "config": {"kind": "agent", "agent_id": FIREGUARD_AGENT_ID}},
    {"node_id": "terminal", "label": "Response", "config": {"kind": "terminal"}},
]
WORKFLOW_EDGES = [
    {
        "edge_id": "edge_trigger_to_adk",
        "from_node_id": "human_trigger",
        "to_node_id": DATA_CHECKS_NODE_ID,
        "condition": "default",
    },
    {
        "edge_id": "edge_data_checks_to_adk",
        "from_node_id": DATA_CHECKS_NODE_ID,
        "to_node_id": FIREGUARD_AGENT_ID,
        "condition": "default",
    },
    {
        "edge_id": "edge_adk_to_terminal",
        "from_node_id": FIREGUARD_AGENT_ID,
        "to_node_id": "terminal",
        "condition": "default",
    },
]
TERMINAL_STATUSES = {"completed", "failed", "stopped", "rejected"}


def create_app() -> FastAPI:
    state = RuntimeState()
    app = FastAPI(default_response_class=ORJSONResponse, title="FireGuard ADK Intelligence")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # ── Tool proxy endpoints — ADK agent (running in GCP) calls back here ─────
    @app.post("/api/tools/fireguard_search_shelters")
    async def proxy_search_shelters(request: Request) -> dict:
        return await _run_tool_direct(_tool_registry(), "fireguard_search_shelters", await request.json())

    @app.post("/api/tools/fireguard_evaluate_route")
    async def proxy_evaluate_route(request: Request) -> dict:
        return await _run_tool_direct(_tool_registry(), "fireguard_evaluate_route", await request.json())

    @app.post("/api/tools/fireguard_map_annotation")
    async def proxy_map_annotation(request: Request) -> dict:
        return await _run_tool_direct(_tool_registry(), "fireguard_map_annotation", await request.json())

    @app.post("/api/tools/fireguard_actions")
    async def proxy_actions(request: Request) -> dict:
        return await _run_tool_direct(_tool_registry(), "fireguard_actions", await request.json())

    @app.get("/settings")
    async def settings() -> dict[str, object]:
        return {
            "provider": "google-adk-agent-runtime",
            "base_url": _agent_runtime_endpoint(),
            "light_model": _model_name(),
            "pro_model": _model_name(),
            "max_completion_tokens": 0,
            "max_agent_turns": 0,
            "google_project_configured": True,
            "google_cloud_location": os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
            "fireguard_data_configured": True,
            "fireguard_index_prefix": os.environ.get("ELASTICSEARCH_INDEX_PREFIX", "fireguard"),
            "fireguard_data_bootstrap_enabled": False,
        }

    @app.get("/sessions")
    async def list_sessions() -> list[dict[str, object]]:
        return [state.session_item(session_id) for session_id in state.session_order()]

    @app.post("/sessions")
    async def create_session(request: CreateSessionRequest) -> dict[str, object]:
        session = state.create_session(request.title, request.metadata)
        return session

    @app.get("/sessions/{session_id}/runs/latest")
    async def latest_run(session_id: str) -> dict[str, object] | None:
        state.require_session(session_id)
        run_id = state.latest_run_id(session_id)
        return None if run_id is None else state.run_json(session_id, run_id)

    @app.post("/sessions/{session_id}/workflows/runs")
    async def start_run(session_id: str, request: StartRunRequest) -> dict[str, object]:
        return await _start_adk_run(state, session_id, request)

    @app.post("/sessions/{session_id}/chat/runs")
    async def start_chat_run(session_id: str, request: StartRunRequest) -> dict[str, object]:
        return await _start_adk_run(state, session_id, request)

    @app.get("/sessions/{session_id}/runs/{run_id}")
    async def get_run(session_id: str, run_id: str) -> dict[str, object]:
        return state.run_json(session_id, run_id)

    @app.get("/sessions/{session_id}/runs/{run_id}/events")
    async def get_events(session_id: str, run_id: str, include_ancestors: bool = False) -> list[dict[str, object]]:
        del include_ancestors
        return state.events_json(session_id, run_id)

    @app.get("/sessions/{session_id}/runs/{run_id}/history")
    async def get_history(session_id: str, run_id: str, include_ancestors: bool = False) -> list[dict[str, object]]:
        del include_ancestors
        return state.history_json(session_id, run_id)

    @app.get("/sessions/{session_id}/runs/{run_id}/trace")
    async def get_trace(session_id: str, run_id: str, include_ancestors: bool = False) -> list[dict[str, object]]:
        del include_ancestors
        return state.events_json(session_id, run_id)

    @app.get("/sessions/{session_id}/runs/{run_id}/chat")
    async def get_chat(session_id: str, run_id: str, include_ancestors: bool = False) -> dict[str, object]:
        del include_ancestors
        run = state.require_run(session_id, run_id)
        return {
            "session_id": session_id,
            "run_id": run_id,
            "messages": state.chat_messages(run),
            "events": state.events_json(session_id, run_id),
        }

    @app.get("/sessions/{session_id}/runs/{run_id}/nodes/{node_id}")
    async def get_node_detail(
        session_id: str,
        run_id: str,
        node_id: str,
        include_ancestors: bool = False,
    ) -> dict[str, object]:
        del include_ancestors
        run = state.require_run(session_id, run_id)
        node = next((item for item in run.workflow["nodes"] if item["node_id"] == node_id), None)
        if node is None:
            raise HTTPException(status_code=404, detail=f"node {node_id} does not exist")
        events = [event_json(event) for event in run.events if event.node_id == node_id]
        return {
            "node": node,
            "state": run.node_states.get(node_id),
            "agent_id": node_id if node_id in {FIREGUARD_AGENT_ID, DATA_CHECKS_NODE_ID} else None,
            "history": state.history_json(session_id, run_id),
            "transcript": state.history_json(session_id, run_id),
            "events": events,
            "trace": events,
        }

    @app.get("/sessions/{session_id}/runs/{run_id}/stream")
    async def stream_run(
        session_id: str,
        run_id: str,
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        async def body() -> AsyncIterator[str]:
            async for event in state.stream_events(session_id, run_id, last_event_id):
                if await request.is_disconnected():
                    break
                yield event.to_sse()

        return StreamingResponse(body(), media_type="text/event-stream")

    @app.post("/sessions/{session_id}/runs/{run_id}/restart")
    async def restart_run(session_id: str, run_id: str) -> dict[str, object]:
        run = state.require_run(session_id, run_id)
        return await _start_adk_run(state, session_id, StartRunRequest(prompt=run.prompt, payload=run.payload))

    @app.post("/sessions/{session_id}/chat/restart")
    async def restart_chat(session_id: str, request: ChatRestartRequest) -> dict[str, object]:
        run = state.require_run(session_id, request.run_id)
        prompt = request.user_message if request.user_message and request.user_message.strip() else run.prompt
        return await _start_adk_run(state, session_id, StartRunRequest(prompt=prompt, payload=run.payload))

    @app.post("/sessions/{session_id}/runs/{run_id}/stop")
    async def stop_run(session_id: str, run_id: str) -> dict[str, object]:
        run = state.require_run(session_id, run_id)
        if run.status not in TERMINAL_STATUSES:
            run.status = "stopped"
            run.current_node_id = "terminal"
            now = now_iso()
            run.updated_at = now
            run.node_states[FIREGUARD_AGENT_ID]["status"] = "skipped"
            run.node_states["terminal"]["status"] = "completed"
            run.node_states["terminal"]["completed_at"] = now
            state.publish(run, "run.stopped", "terminal", None, {})
        return state.run_json(session_id, run_id)

    return app


async def _start_adk_run(state: "RuntimeState", session_id: str, request: "StartRunRequest") -> dict[str, object]:
    state.require_session(session_id)
    run = state.create_run(session_id, request.prompt, request.payload)
    asyncio.create_task(_execute_adk_run(state, run))
    return state.run_json(session_id, run.run_id)


async def _execute_adk_run(state: "RuntimeState", run: "RunRecord") -> None:
    try:
        now = now_iso()
        run.status = "running"
        run.current_node_id = DATA_CHECKS_NODE_ID
        run.updated_at = now
        run.node_states["human_trigger"]["status"] = "completed"
        run.node_states["human_trigger"]["completed_at"] = now
        run.node_states[DATA_CHECKS_NODE_ID]["status"] = "running"
        run.node_states[DATA_CHECKS_NODE_ID]["started_at"] = now
        state.publish(run, "run.started", None, None, {})
        state.publish(run, "workflow.node.started", "human_trigger", None, {})
        state.publish(run, "workflow.node.completed", "human_trigger", None, {"prompt": run.prompt, "payload": run.payload})
        state.publish(
            run,
            "workflow.handoff.created",
            "human_trigger",
            None,
            {
                "from_node_id": "human_trigger",
                "to_node_id": DATA_CHECKS_NODE_ID,
                "condition": "default",
                "payload": {"prompt": run.prompt, "payload": run.payload},
            },
        )
        state.publish(run, "workflow.node.started", DATA_CHECKS_NODE_ID, DATA_CHECKS_NODE_ID, {})

        evidence = await _collect_fireguard_evidence(state, run)
        now = now_iso()
        run.node_states[DATA_CHECKS_NODE_ID]["status"] = "completed"
        run.node_states[DATA_CHECKS_NODE_ID]["completed_at"] = now
        run.node_states[DATA_CHECKS_NODE_ID]["output_payload"] = evidence
        run.current_node_id = FIREGUARD_AGENT_ID
        state.publish(run, "workflow.node.completed", DATA_CHECKS_NODE_ID, DATA_CHECKS_NODE_ID, evidence)
        state.publish(run, "workflow.handoff.created", DATA_CHECKS_NODE_ID, DATA_CHECKS_NODE_ID, {"to_node_id": FIREGUARD_AGENT_ID, "payload": evidence, "condition": "default", "from_node_id": DATA_CHECKS_NODE_ID})

        run.node_states[FIREGUARD_AGENT_ID]["status"] = "running"
        run.node_states[FIREGUARD_AGENT_ID]["started_at"] = now
        state.publish(run, "workflow.node.started", FIREGUARD_AGENT_ID, FIREGUARD_AGENT_ID, {})
        state.publish(run, "agent.started", FIREGUARD_AGENT_ID, FIREGUARD_AGENT_ID, {"name": "FireGuard ADK Agent"})

        text_parts: list[str] = []
        tool_names: dict[str, str] = {}
        usage: dict[str, Any] | None = None
        model_version: str | None = None
        async for chunk in _stream_agent_runtime(_agent_runtime_message(run.prompt, evidence), run.session_id):
            model_version = chunk.get("model_version") if isinstance(chunk.get("model_version"), str) else model_version
            usage = chunk.get("usage_metadata") if isinstance(chunk.get("usage_metadata"), dict) else usage
            content = chunk.get("content")
            if not isinstance(content, dict):
                continue
            for part in content.get("parts", []):
                if not isinstance(part, dict):
                    continue
                call = part.get("function_call")
                if isinstance(call, dict):
                    invocation_id = str(call.get("id") or new_id("tool"))
                    tool_name = str(call.get("name") or "tool")
                    args = call.get("args") if isinstance(call.get("args"), dict) else {}
                    tool_names[invocation_id] = tool_name
                    state.publish(
                        run,
                        "agent.tool_calls.requested",
                        FIREGUARD_AGENT_ID,
                        FIREGUARD_AGENT_ID,
                        {"tool_calls": [{"id": invocation_id, "name": tool_name, "args": args}]},
                    )
                    state.publish(
                        run,
                        "tool.started",
                        FIREGUARD_AGENT_ID,
                        FIREGUARD_AGENT_ID,
                        {"invocation_id": invocation_id, "tool_name": tool_name, "args": args},
                    )
                response = part.get("function_response")
                if isinstance(response, dict):
                    invocation_id = str(response.get("id") or new_id("tool"))
                    tool_name = str(response.get("name") or tool_names.get(invocation_id) or "tool")
                    output = response.get("response") if isinstance(response.get("response"), dict) else {}
                    state.publish(
                        run,
                        "tool.completed",
                        FIREGUARD_AGENT_ID,
                        FIREGUARD_AGENT_ID,
                        {"invocation_id": invocation_id, "tool_name": tool_name, "ok": True, "output": output},
                    )
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
        assistant_text = "".join(text_parts).strip()
        run.assistant_text = assistant_text
        run.history.append(
            {
                "role": "assistant",
                "content": assistant_text,
                "agent_id": FIREGUARD_AGENT_ID,
                "run_id": run.run_id,
                "model_version": model_version,
            }
        )
        if usage is not None:
            run.usage.append(
                {
                    "model": model_version or _model_name(),
                    "model_tier": "pro",
                    "call_type": "agent_runtime",
                    "prompt_tokens": usage.get("prompt_token_count"),
                    "completion_tokens": usage.get("candidates_token_count"),
                    "total_tokens": usage.get("total_token_count"),
                    "reasoning_tokens": usage.get("thoughts_token_count"),
                    "cached_tokens": None,
                    "cost": None,
                }
            )
            state.publish(run, "usage.updated", FIREGUARD_AGENT_ID, FIREGUARD_AGENT_ID, run.usage[-1])
        now = now_iso()
        run.status = "completed"
        run.current_node_id = "terminal"
        run.updated_at = now
        run.node_states[FIREGUARD_AGENT_ID]["status"] = "completed"
        run.node_states[FIREGUARD_AGENT_ID]["completed_at"] = now
        run.node_states[FIREGUARD_AGENT_ID]["output_payload"] = {"response": assistant_text, "model_version": model_version}
        run.node_states["terminal"]["status"] = "completed"
        run.node_states["terminal"]["started_at"] = now
        run.node_states["terminal"]["completed_at"] = now
        run.node_states["terminal"]["output_payload"] = {"response": assistant_text}
        state.publish(run, "agent.message.completed", FIREGUARD_AGENT_ID, FIREGUARD_AGENT_ID, {"content": assistant_text})
        state.publish(run, "workflow.node.completed", FIREGUARD_AGENT_ID, FIREGUARD_AGENT_ID, {"response": assistant_text})
        state.publish(
            run,
            "workflow.handoff.created",
            FIREGUARD_AGENT_ID,
            FIREGUARD_AGENT_ID,
            {
                "from_node_id": FIREGUARD_AGENT_ID,
                "to_node_id": "terminal",
                "condition": "default",
                "payload": {"response": assistant_text},
            },
        )
        state.publish(run, "workflow.node.started", "terminal", None, {})
        state.publish(run, "workflow.node.completed", "terminal", None, {"response": assistant_text})
        state.publish(run, "run.completed", "terminal", None, {"status": "completed"})
    except Exception as exc:
        now = now_iso()
        run.status = "failed"
        run.current_node_id = FIREGUARD_AGENT_ID
        run.updated_at = now
        run.node_states[FIREGUARD_AGENT_ID]["status"] = "failed"
        run.node_states[FIREGUARD_AGENT_ID]["completed_at"] = now
        run.node_states[FIREGUARD_AGENT_ID]["error"] = str(exc)
        state.publish(run, "workflow.node.failed", FIREGUARD_AGENT_ID, FIREGUARD_AGENT_ID, {"error": str(exc)})
        state.publish(run, "run.failed", FIREGUARD_AGENT_ID, FIREGUARD_AGENT_ID, {"error": str(exc)})
    finally:
        state.close_stream(run)


async def _stream_agent_runtime(message: str, user_id: str) -> AsyncIterator[dict[str, Any]]:
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(AuthRequest())
    headers = {"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"}
    body = {
        "class_method": "async_stream_query",
        "input": {"user_id": user_id, "message": message},
    }
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", _agent_runtime_endpoint(), headers=headers, json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                yield json.loads(line)


async def _collect_fireguard_evidence(state: "RuntimeState", run: "RunRecord") -> dict[str, Any]:
    threat = run.payload.get("threat")
    if not isinstance(threat, dict):
        return {"mode": "chat", "tools": []}
    hotspot = threat.get("hotspot")
    zone = threat.get("zone")
    if not isinstance(hotspot, dict) or not isinstance(zone, dict):
        return {"mode": "chat", "tools": []}
    hot_lat = _number(hotspot.get("lat"))
    hot_lon = _number(hotspot.get("lon"))
    if hot_lat is None or hot_lon is None:
        return {"mode": "chat", "tools": []}
    zone_lat = _number(zone.get("latitude")) or hot_lat
    zone_lon = _number(zone.get("longitude")) or hot_lon
    replay = _replay_context(run.payload)
    registry = _tool_registry()
    evidence: dict[str, Any] = {
        "mode": "evacuation",
        "hotspot": hotspot,
        "zone": zone,
        "tools": [],
    }

    async def tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
        output = await _run_fireguard_tool(state, run, registry, name, args)
        evidence["tools"].append({"name": name, "args": args, "output": output})
        return output

    zones = await tool(
        "fireguard_search_zones",
        {"latitude": hot_lat, "longitude": hot_lon, "radius_km": 150, "size": 25},
    )
    shelters = await tool(
        "fireguard_search_shelters",
        {"latitude": zone_lat, "longitude": zone_lon, "radius_km": 300, "size": 25},
    )
    roads = await tool(
        "fireguard_search_road_events",
        {"latitude": zone_lat, "longitude": zone_lon, "radius_km": 250, "size": 25},
    )
    events_args: dict[str, Any] = {
        "latitude": hot_lat,
        "longitude": hot_lon,
        "radius_km": 100,
        "size": 75,
    }
    if replay.get("start_date"):
        events_args["start_date"] = replay["start_date"]
    if replay.get("end_date"):
        events_args["end_date"] = replay["end_date"]
    fires = await tool("fireguard_search_events", events_args)
    bcws = await tool(
        "fireguard_bcws_context",
        {"latitude": hot_lat, "longitude": hot_lon, "radius_km": 120, "size": 25},
    )

    evidence.update(
        {
            "replay": replay,
            "zones": zones,
            "shelters": shelters,
            "road_events": roads,
            "fire_detections": fires,
            "bcws": bcws,
        }
    )
    return evidence


async def _run_fireguard_tool(
    state: "RuntimeState",
    run: "RunRecord",
    registry: Any,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    invocation_id = new_id("tool")
    state.publish(
        run,
        "tool.started",
        DATA_CHECKS_NODE_ID,
        DATA_CHECKS_NODE_ID,
        {"invocation_id": invocation_id, "tool_name": tool_name, "args": args},
    )
    invocation = ToolInvocation(
        invocation_id=invocation_id,
        tool_name=tool_name,
        session_id=run.session_id,
        run_id=run.run_id,
        node_id=DATA_CHECKS_NODE_ID,
        agent_id=DATA_CHECKS_NODE_ID,
        args=args,
    )
    result = (await registry.run_tools([invocation]))[0]
    event_type = "tool.completed" if result.ok else "tool.failed"
    state.publish(
        run,
        event_type,
        DATA_CHECKS_NODE_ID,
        DATA_CHECKS_NODE_ID,
        {
            "invocation_id": invocation_id,
            "tool_name": tool_name,
            "ok": result.ok,
            "output": result.output,
        },
    )
    return result.output


def _tool_registry() -> Any:
    return build_base_tool_registry(
        default_timeout_seconds=float(os.environ.get("FIREGUARD_TOOL_TIMEOUT_SECONDS", "90")),
        max_parallel_tools=8,
        fireguard_elasticsearch_url=os.environ.get("ELASTICSEARCH_URL", ""),
        fireguard_elasticsearch_api_key=os.environ.get("ELASTICSEARCH_API_KEY", ""),
        fireguard_elasticsearch_index_prefix=os.environ.get("ELASTICSEARCH_INDEX_PREFIX", "fireguard"),
    )


async def _run_tool_direct(registry: Any, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool directly without SSE events — used by the proxy endpoints."""
    invocation = ToolInvocation(
        invocation_id=new_id("tool"),
        tool_name=tool_name,
        session_id="proxy",
        run_id="proxy",
        node_id="proxy",
        agent_id=None,
        args=args,
    )
    results = await registry.run_tools([invocation])
    result = results[0]
    if not result.ok:
        raise HTTPException(status_code=500, detail=result.output.get("error", "tool error"))
    return result.output


def _agent_runtime_message(prompt: str, evidence: dict[str, Any]) -> str:
    if evidence.get("mode") != "evacuation":
        return prompt
    compact = _compact_evidence_for_model(evidence)
    replay = evidence.get("replay", {})
    date_hint = ""
    if isinstance(replay, dict) and replay.get("start_date") and replay.get("end_date"):
        date_hint = (
            f"\nREPLAY DATE RANGE: {replay['start_date']} to {replay['end_date']}. "
            f"Pass start_date/end_date to fireguard_evaluate_route.\n"
        )
    return (
        f"{prompt}\n\n"
        "FIREGUARD_EVIDENCE — raw indexed data, no conclusions drawn yet. "
        "Follow your protocol: check shelter status, evaluate route to an OPEN shelter, "
        "annotate the map, push action plan, then write the brief.\n"
        f"{date_hint}\n"
        f"EVIDENCE:\n{json.dumps(compact, separators=(',', ':'), default=str)}"
    )


def _compact_evidence_for_model(evidence: dict[str, Any]) -> dict[str, Any]:
    """Compact raw evidence to send to the ADK agent as context."""
    shelters = evidence.get("shelters", {}).get("shelters", []) if isinstance(evidence.get("shelters"), dict) else []
    road_events = evidence.get("road_events", {}).get("road_events", []) if isinstance(evidence.get("road_events"), dict) else []
    fires = evidence.get("fire_detections", {}).get("events", []) if isinstance(evidence.get("fire_detections"), dict) else []
    bcws = evidence.get("bcws") if isinstance(evidence.get("bcws"), dict) else {}
    return {
        "hotspot": evidence.get("hotspot"),
        "zone": evidence.get("zone"),
        "shelters": shelters[:10] if isinstance(shelters, list) else [],
        "road_events": road_events[:8] if isinstance(road_events, list) else [],
        "fire_detections": fires[:12] if isinstance(fires, list) else [],
        "bcws_incident_count": len(bcws.get("incidents", [])) if isinstance(bcws.get("incidents"), list) else 0,
        "bcws_perimeter_count": len(bcws.get("perimeters", [])) if isinstance(bcws.get("perimeters"), list) else 0,
    }


def _replay_context(payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("session_context")
    replay = context.get("replay") if isinstance(context, dict) else None
    return replay if isinstance(replay, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _point(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = _number(payload.get("latitude"))
    lon = _number(payload.get("longitude"))
    if lat is not None and lon is not None:
        return lat, lon
    location = payload.get("location")
    if isinstance(location, dict):
        return _number(location.get("lat")), _number(location.get("lon"))
    return None, None


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = "FireGuard Intelligence Session"
    metadata: dict[str, Any] = Field(default_factory=dict)


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    workflow_id: str = WORKFLOW_ID
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatRestartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    event_id: str | None = None
    node_id: str | None = None
    user_message: str | None = None


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class StreamEvent:
    event_type: str
    session_id: str
    run_id: str
    node_id: str | None
    agent_id: str | None
    data: dict[str, Any]
    event_id: str = field(default_factory=lambda: new_id("sse"))
    timestamp: str = field(default_factory=now_iso)

    def to_sse(self) -> str:
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {json.dumps(event_json(self), separators=(',', ':'))}\n\n"


@dataclass
class RunRecord:
    session_id: str
    run_id: str
    prompt: str
    payload: dict[str, Any]
    workflow: dict[str, Any]
    status: str = "created"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    current_node_id: str | None = "human_trigger"
    node_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals: dict[str, Any] = field(default_factory=dict)
    usage: list[dict[str, Any]] = field(default_factory=list)
    attempt: int = 1
    parent_run_id: str | None = None
    events: list[StreamEvent] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    assistant_text: str = ""
    queues: list[asyncio.Queue[StreamEvent | None]] = field(default_factory=list)


class RuntimeState:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, RunRecord]] = {}

    def create_session(self, title: str, metadata: dict[str, Any]) -> dict[str, Any]:
        session_id = new_id("ses")
        now = now_iso()
        session = {
            "session_id": session_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "metadata": metadata,
        }
        self.sessions[session_id] = session
        self.runs[session_id] = {}
        return session

    def session_order(self) -> list[str]:
        return sorted(self.sessions, key=lambda item: self.sessions[item]["updated_at"], reverse=True)

    def session_item(self, session_id: str) -> dict[str, object]:
        session = self.require_session(session_id)
        latest = self.latest_run_id(session_id)
        return {**session, "latest_run": None if latest is None else self.run_json(session_id, latest)}

    def require_session(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session

    def latest_run_id(self, session_id: str) -> str | None:
        runs = self.runs.get(session_id, {})
        if len(runs) == 0:
            return None
        return max(runs, key=lambda item: runs[item].created_at)

    def create_run(self, session_id: str, prompt: str, payload: dict[str, Any]) -> RunRecord:
        run_id = new_id("run")
        workflow = {"workflow_id": WORKFLOW_ID, "name": "FireGuard ADK", "start_node_id": "human_trigger", "nodes": WORKFLOW_NODES, "edges": WORKFLOW_EDGES}
        states = {node["node_id"]: node_state(node["node_id"]) for node in WORKFLOW_NODES}
        states["human_trigger"]["input_payload"] = {"prompt": prompt, "payload": payload}
        run = RunRecord(
            session_id=session_id,
            run_id=run_id,
            prompt=prompt,
            payload=payload,
            workflow=workflow,
            node_states=states,
            history=[{"role": "user", "content": prompt, "agent_id": None, "run_id": run_id}],
        )
        self.runs[session_id][run_id] = run
        self.sessions[session_id]["updated_at"] = run.updated_at
        return run

    def require_run(self, session_id: str, run_id: str) -> RunRecord:
        self.require_session(session_id)
        run = self.runs.get(session_id, {}).get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    def run_json(self, session_id: str, run_id: str) -> dict[str, object]:
        run = self.require_run(session_id, run_id)
        return {
            "session_id": run.session_id,
            "run_id": run.run_id,
            "workflow": run.workflow,
            "status": run.status,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "current_node_id": run.current_node_id,
            "node_states": run.node_states,
            "approvals": run.approvals,
            "usage": run.usage,
            "attempt": run.attempt,
            "parent_run_id": run.parent_run_id,
        }

    def events_json(self, session_id: str, run_id: str) -> list[dict[str, object]]:
        return [event_json(event) for event in self.require_run(session_id, run_id).events]

    def history_json(self, session_id: str, run_id: str) -> list[dict[str, object]]:
        return list(self.require_run(session_id, run_id).history)

    def chat_messages(self, run: RunRecord) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = [
            {"id": "user_prompt", "role": "user", "content": run.prompt, "annotations": []}
        ]
        if run.assistant_text:
            messages.append(
                {
                    "id": "assistant_0",
                    "role": "assistant",
                    "content": run.assistant_text,
                    "annotations": annotations_for_events(run.events),
                    "agent_id": FIREGUARD_AGENT_ID,
                    "run_id": run.run_id,
                    "node_id": FIREGUARD_AGENT_ID,
                }
            )
        return messages

    def publish(
        self,
        run: RunRecord,
        event_type: str,
        node_id: str | None,
        agent_id: str | None,
        data: dict[str, Any],
    ) -> StreamEvent:
        event = StreamEvent(event_type=event_type, session_id=run.session_id, run_id=run.run_id, node_id=node_id, agent_id=agent_id, data=data)
        run.events.append(event)
        for queue in run.queues:
            queue.put_nowait(event)
        return event

    async def stream_events(self, session_id: str, run_id: str, last_event_id: str | None) -> AsyncIterator[StreamEvent]:
        run = self.require_run(session_id, run_id)
        start = 0
        if last_event_id:
            for index, event in enumerate(run.events):
                if event.event_id == last_event_id:
                    start = index + 1
                    break
        for event in run.events[start:]:
            yield event
        if run.status in TERMINAL_STATUSES:
            return
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        run.queues.append(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if queue in run.queues:
                run.queues.remove(queue)

    def close_stream(self, run: RunRecord) -> None:
        for queue in run.queues:
            queue.put_nowait(None)


def annotations_for_events(events: list[StreamEvent]) -> list[dict[str, object]]:
    annotations: list[dict[str, object]] = []
    for event in events:
        if event.event_type in {"tool.started", "tool.completed", "tool.failed"}:
            annotations.append({"type": event.event_type, "event_id": event.event_id, "node_id": event.node_id, "agent_id": event.agent_id, **event.data})
    return annotations


def node_state(node_id: str) -> dict[str, Any]:
    return {"node_id": node_id, "status": "pending", "input_payload": None, "output_payload": None, "error": None, "started_at": None, "completed_at": None}


def event_json(event: StreamEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "session_id": event.session_id,
        "run_id": event.run_id,
        "node_id": event.node_id,
        "agent_id": event.agent_id,
        "timestamp": event.timestamp,
        "data": event.data,
    }


def _agent_runtime_resource() -> str:
    resource = os.environ.get("AGENT_RUNTIME_RESOURCE", "").strip()
    if not resource:
        raise RuntimeError("AGENT_RUNTIME_RESOURCE is required")
    return resource


def _resource_location() -> str:
    parts = _agent_runtime_resource().split("/")
    return parts[3] if len(parts) >= 4 else "us-central1"


def _agent_runtime_endpoint() -> str:
    resource = _agent_runtime_resource()
    location = _resource_location()
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    return f"https://{host}/v1/{resource}:streamQuery?alt=sse"


def _model_name() -> str:
    return os.environ.get("AGENT_RUNTIME_GEMINI_MODEL", "gemini-3.1-pro-preview")
