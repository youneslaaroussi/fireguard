from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, ORJSONResponse, StreamingResponse

from .config import AppConfig, get_config
from .engine import WorkflowEngine
from .models import (
    ApprovalResolutionRequest,
    ChatRestartRequest,
    CreateSessionRequest,
    RestartRunRequest,
    StartRunRequest,
)


def create_app(
    config: AppConfig | None = None, engine: WorkflowEngine | None = None
) -> FastAPI:
    resolved_config = config if config is not None else (
        engine.config if engine is not None else get_config()
    )
    resolved_engine = engine if engine is not None else WorkflowEngine.from_config(resolved_config)
    app = FastAPI(default_response_class=ORJSONResponse, title="FireGuard Intelligence")
    app.state.engine = resolved_engine

    @app.on_event("startup")
    async def startup() -> None:
        await resolved_engine.start()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await resolved_engine.close()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/settings")
    async def settings() -> dict[str, object]:
        return {
            "provider": resolved_config.provider,
            "base_url": _settings_base_url(resolved_config),
            "light_model": resolved_config.light_model,
            "pro_model": resolved_config.pro_model,
            "max_completion_tokens": resolved_config.max_completion_tokens,
            "max_agent_turns": resolved_config.max_agent_turns,
            "exa_configured": len(resolved_config.exa_api_key.strip()) > 0,
            "google_project_configured": len(resolved_config.google_cloud_project.strip()) > 0,
            "google_cloud_location": resolved_config.google_cloud_location,
            "fireguard_data_configured": (
                len(resolved_config.fireguard_elasticsearch_url.strip()) > 0
                and len(resolved_config.fireguard_elasticsearch_api_key.strip()) > 0
            ),
            "fireguard_index_prefix": resolved_config.fireguard_elasticsearch_index_prefix,
            "fireguard_data_bootstrap_enabled": resolved_config.fireguard_data_bootstrap_enabled,
            "docker_sandbox_enabled": resolved_config.docker_sandbox_enabled,
            "docker_sandbox_image": resolved_config.docker_sandbox_image,
            "docker_sandbox_network": resolved_config.docker_sandbox_network,
            "docker_sandbox_pool_size": resolved_config.docker_sandbox_pool_size,
            "docker_sandbox_install_packages_on_start": (
                resolved_config.docker_sandbox_install_packages_on_start
            ),
        }

    @app.get("/sessions")
    async def list_sessions() -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for session in resolved_engine.store.list_sessions():
            latest = resolved_engine.store.latest_run(session.session_id)
            items.append(
                {
                    **session.model_dump(mode="json"),
                    "latest_run": latest.model_dump(mode="json") if latest is not None else None,
                }
            )
        return sorted(items, key=_session_sort_key, reverse=True)

    @app.post("/sessions")
    async def create_session(request: CreateSessionRequest) -> dict[str, object]:
        return resolved_engine.create_session(request).model_dump(mode="json")

    @app.get("/sessions/{session_id}/runs/latest")
    async def latest_run(session_id: str) -> dict[str, object] | None:
        try:
            resolved_engine.store.load_session(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        run = resolved_engine.store.latest_run(session_id)
        return run.model_dump(mode="json") if run is not None else None

    @app.post("/sessions/{session_id}/workflows/runs")
    async def start_run(session_id: str, request: StartRunRequest) -> dict[str, object]:
        try:
            return resolved_engine.start_run(session_id, request).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/chat/runs")
    async def start_chat_run(session_id: str, request: StartRunRequest) -> dict[str, object]:
        try:
            return resolved_engine.start_chat_run(session_id, request).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/runs/{run_id}")
    async def get_run(session_id: str, run_id: str) -> dict[str, object]:
        try:
            return resolved_engine.get_run(session_id, run_id).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/runs/{run_id}/events")
    async def get_events(
        session_id: str, run_id: str, include_ancestors: bool = False
    ) -> list[dict[str, object]]:
        return [
            event.model_dump(mode="json")
            for event in resolved_engine.get_events(
                session_id, run_id, include_ancestors=include_ancestors
            )
        ]

    @app.get("/sessions/{session_id}/runs/{run_id}/chat")
    async def chat_history(
        session_id: str, run_id: str, include_ancestors: bool = False
    ) -> dict[str, object]:
        try:
            run = resolved_engine.get_run(session_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        events = [
            event.model_dump(mode="json")
            for event in resolved_engine.get_events(
                session_id, run_id, include_ancestors=include_ancestors
            )
        ]
        history = resolved_engine.get_run_history(
            session_id, run_id, include_ancestors=include_ancestors
        )
        return {
            "session_id": session_id,
            "run_id": run_id,
            "messages": _chat_messages(
                resolved_engine.get_chat_trigger_payload(
                    session_id, run.run_id, include_ancestors=include_ancestors
                ),
                history,
                events,
            ),
            "events": events,
        }

    @app.get("/sessions/{session_id}/runs/{run_id}/history")
    async def run_history(
        session_id: str, run_id: str, include_ancestors: bool = False
    ) -> list[dict[str, object]]:
        return resolved_engine.get_run_history(
            session_id, run_id, include_ancestors=include_ancestors
        )

    @app.get("/sessions/{session_id}/runs/{run_id}/trace")
    async def run_trace(
        session_id: str, run_id: str, include_ancestors: bool = False
    ) -> list[dict[str, object]]:
        return resolved_engine.get_run_trace(
            session_id, run_id, include_ancestors=include_ancestors
        )

    @app.get("/sessions/{session_id}/runs/{run_id}/nodes/{node_id}")
    async def node_detail(
        session_id: str,
        run_id: str,
        node_id: str,
        include_ancestors: bool = False,
    ) -> dict[str, object]:
        try:
            run = resolved_engine.get_run(session_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        node = next((item for item in run.workflow.nodes if item.node_id == node_id), None)
        if node is None:
            raise HTTPException(status_code=404, detail=f"node {node_id} does not exist")
        state = run.node_states.get(node_id)
        agent_id = None
        if node.config.kind == "agent":
            agent_id = str(node.config.agent_id)
        history = resolved_engine.get_run_history(
            session_id, run_id, include_ancestors=include_ancestors
        )
        trace = resolved_engine.get_run_trace(
            session_id, run_id, include_ancestors=include_ancestors
        )
        events = [
            event.model_dump(mode="json")
            for event in resolved_engine.get_events(
                session_id, run_id, include_ancestors=include_ancestors
            )
        ]
        node_events = [event for event in events if event.get("node_id") == node_id]
        node_trace = [event for event in trace if event.get("node_id") == node_id]
        if agent_id is not None:
            node_history = [entry for entry in history if entry.get("agent_id") == agent_id]
        else:
            node_history = []
        return {
            "node": node.model_dump(mode="json"),
            "state": state.model_dump(mode="json") if state is not None else None,
            "agent_id": agent_id,
            "history": node_history,
            "transcript": history,
            "events": node_events,
            "trace": node_trace,
        }

    @app.get("/sessions/{session_id}/runs/{run_id}/stream")
    async def stream_run(
        session_id: str,
        run_id: str,
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        async def body() -> AsyncIterator[str]:
            async for event in resolved_engine.stream_events(
                session_id, run_id, last_event_id=last_event_id
            ):
                if await request.is_disconnected():
                    break
                yield event.to_sse()

        return StreamingResponse(body(), media_type="text/event-stream")

    @app.post("/sessions/{session_id}/runs/{run_id}/approvals/{approval_id}")
    async def resolve_approval(
        session_id: str,
        run_id: str,
        approval_id: str,
        request: ApprovalResolutionRequest,
    ) -> dict[str, object]:
        try:
            return resolved_engine.resolve_approval(
                session_id, run_id, approval_id, request
            ).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/runs/{run_id}/restart")
    async def restart_run(
        session_id: str,
        run_id: str,
        request: RestartRunRequest,
    ) -> dict[str, object]:
        try:
            return resolved_engine.restart_run(session_id, run_id, request).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/chat/restart")
    async def restart_chat(session_id: str, request: ChatRestartRequest) -> dict[str, object]:
        try:
            restart_request = RestartRunRequest(event_id=request.event_id, node_id=request.node_id)
            if request.event_id is not None:
                try:
                    checkpoint = resolved_engine.store.checkpoint_for_event(
                        session_id, request.run_id, request.event_id
                    )
                    restart_request.checkpoint_id = checkpoint.checkpoint_id
                except FileNotFoundError:
                    restart_request.event_id = None
            input_payload = None
            if request.user_message is not None and len(request.user_message.strip()) > 0:
                input_payload = {
                    "prompt": request.user_message,
                    "payload": {"source": "chat_restart", "parent_run_id": request.run_id},
                }
            run = resolved_engine.restart_run(
                session_id, request.run_id, restart_request, input_payload=input_payload
            )
            return run.model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/runs/{run_id}/stop")
    async def stop_run(session_id: str, run_id: str) -> dict[str, object]:
        try:
            return (await resolved_engine.stop_run(session_id, run_id)).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/agents/{agent_id}/history")
    async def agent_history(session_id: str, agent_id: str) -> list[dict[str, object]]:
        return resolved_engine.store.read_agent_history(session_id, agent_id)

    @app.get("/sessions/{session_id}/assets/{filename}")
    async def get_session_asset(session_id: str, filename: str) -> FileResponse:
        asset_path = resolved_engine.store.assets_dir(session_id) / filename
        if not asset_path.exists() or not asset_path.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(str(asset_path))

    return app


def _chat_messages(
    trigger_payload: dict[str, object] | None,
    history: list[dict[str, object]],
    events: list[dict[str, object]],
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    if trigger_payload is not None:
        prompt = trigger_payload.get("prompt")
        if isinstance(prompt, str):
            messages.append(
                {
                    "id": "user_prompt",
                    "role": "user",
                    "content": prompt,
                    "annotations": [],
                    "created_at": trigger_payload.get("started_at"),
                }
            )
    assistant_index = 0
    for entry in history:
        if entry.get("role") != "assistant":
            continue
        content = entry.get("content")
        if not isinstance(content, str):
            continue
        agent_id = entry.get("agent_id")
        run_id = entry.get("run_id")
        annotations = _annotations_for_agent(
            events, agent_id if isinstance(agent_id, str) else None
        )
        content = _visible_assistant_content(content)
        if content is None:
            if len(annotations) == 0:
                continue
            content = ""
        messages.append(
            {
                "id": f"assistant_{assistant_index}",
                "role": "assistant",
                "content": content,
                "annotations": annotations,
                "agent_id": agent_id,
                "run_id": run_id,
                "created_at": None,
            }
        )
        assistant_index += 1
    return messages


def _settings_base_url(config: AppConfig) -> str:
    location = config.google_cloud_location.strip()
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    return f"https://{host}/v1"


def _visible_assistant_content(content: str) -> str | None:
    if len(content.strip()) == 0:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    if isinstance(payload, dict):
        user_response = payload.get("user_response")
        if isinstance(user_response, str) and len(user_response.strip()) > 0:
            return user_response
        return None
    return content


def _annotations_for_agent(
    events: list[dict[str, object]], agent_id: str | None
) -> list[dict[str, object]]:
    annotations: list[dict[str, object]] = []
    if agent_id is None:
        return annotations
    for event in events:
        if event.get("agent_id") != agent_id:
            continue
        event_type = event.get("event_type")
        data = event.get("data")
        if not isinstance(event_type, str) or not isinstance(data, dict):
            continue
        if event_type == "agent.message.completed":
            structured = data.get("structured")
            if isinstance(structured, dict) and structured.get("action") == "ask_user":
                questions = structured.get("questions")
                if isinstance(questions, list) and len(questions) > 0:
                    annotations.append(
                        {
                            "type": "structured.ask_user",
                            "event_id": event.get("event_id"),
                            "tool_name": "ask_user",
                            "output": {"title": "Clarify request", "questions": questions},
                        }
                    )
            continue
        if event_type in {
            "tool.started",
            "tool.completed",
            "tool.failed",
            "workflow.node.failed",
            "workflow.error.routed",
        }:
            annotations.append({"type": event_type, "event_id": event.get("event_id"), **data})
    return annotations


def _session_sort_key(item: dict[str, object]) -> str:
    latest = item.get("latest_run")
    if isinstance(latest, dict):
        updated = latest.get("updated_at")
        if isinstance(updated, str):
            return updated
    updated = item.get("updated_at")
    return updated if isinstance(updated, str) else ""
