from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import app.agent_runtime.api as runtime_api


def test_agent_runtime_settings_require_resource(monkeypatch) -> None:
    monkeypatch.setenv(
        "AGENT_RUNTIME_RESOURCE",
        "projects/test-project/locations/us-central1/reasoningEngines/123",
    )
    client = TestClient(runtime_api.create_app())

    response = client.get("/settings")

    assert response.status_code == 200
    assert response.json()["provider"] == "google-adk-agent-runtime"
    assert "reasoningEngines/123" in response.json()["base_url"]


def test_agent_runtime_run_records_tool_events(monkeypatch) -> None:
    monkeypatch.setenv(
        "AGENT_RUNTIME_RESOURCE",
        "projects/test-project/locations/us-central1/reasoningEngines/123",
    )

    async def stream(message: str, user_id: str):
        assert message == "Check FireGuard status."
        assert user_id.startswith("ses_")
        yield {
            "model_version": "gemini-3.1-pro-preview",
            "content": {
                "parts": [
                    {
                        "function_call": {
                            "id": "call_1",
                            "name": "fireguard_health",
                            "args": {},
                        }
                    }
                ]
            },
        }
        yield {
            "content": {
                "parts": [
                    {
                        "function_response": {
                            "id": "call_1",
                            "name": "fireguard_health",
                            "response": {"health": {"status": "ok"}},
                        }
                    }
                ]
            },
        }
        yield {
            "model_version": "gemini-3.1-pro-preview",
            "content": {"parts": [{"text": "FireGuard is online."}]},
            "usage_metadata": {
                "prompt_token_count": 10,
                "candidates_token_count": 4,
                "total_token_count": 14,
                "thoughts_token_count": 0,
            },
        }

    monkeypatch.setattr(runtime_api, "_stream_agent_runtime", stream)
    state = runtime_api.RuntimeState()
    session = state.create_session("check", {})
    run = state.create_run(session["session_id"], "Check FireGuard status.", {})

    asyncio.run(runtime_api._execute_adk_run(state, run))

    assert run.status == "completed"
    assert run.current_node_id == "terminal"
    assert run.usage[0]["model"] == "gemini-3.1-pro-preview"
    assert run.assistant_text == "FireGuard is online."
    assert [
        event["event_type"]
        for event in state.events_json(session["session_id"], run.run_id)
        if event["event_type"].startswith("tool.")
    ] == ["tool.started", "tool.completed"]


def test_casual_chat_does_not_call_tools(monkeypatch) -> None:
    monkeypatch.setenv(
        "AGENT_RUNTIME_RESOURCE",
        "projects/test-project/locations/us-central1/reasoningEngines/123",
    )

    async def stream(message: str, user_id: str):
        raise AssertionError(f"casual chat should not call Agent Runtime: {message} {user_id}")
        yield {}

    monkeypatch.setattr(runtime_api, "_stream_agent_runtime", stream)
    state = runtime_api.RuntimeState()
    session = state.create_session("casual", {})
    run = state.create_run(session["session_id"], "hello there", {})

    asyncio.run(runtime_api._execute_adk_run(state, run))

    assert run.status == "completed"
    assert "FireGuard" in run.assistant_text
    assert [
        event["event_type"]
        for event in state.events_json(session["session_id"], run.run_id)
        if event["event_type"].startswith("tool.")
    ] == []
