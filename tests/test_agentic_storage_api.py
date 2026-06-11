from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

import app.agentic as agentic
from app.agentic.api import _chat_messages, create_app
from app.agentic.config import AppConfig
from app.agentic.main import main as agentic_main
from app.agentic.models import Checkpoint, SessionRecord, StreamEvent, WorkflowRun
from app.agentic.storage import FileStore
from app.agentic.workflows import built_in_workflow
from app.main import app as fireguard_app


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        state_dir=tmp_path,
        fireguard_elasticsearch_url="http://elastic.invalid",
        fireguard_elasticsearch_api_key="test-key",
    )


def test_file_store_round_trips_session_run_events_and_checkpoint(tmp_path: Path) -> None:
    store = FileStore(_config(tmp_path))
    session = SessionRecord(session_id="ses_test", title="Test")
    workflow = built_in_workflow("fireguard_intelligence")
    run = WorkflowRun(session_id=session.session_id, run_id="run_test", workflow=workflow)
    event = StreamEvent(event_type="run.started", session_id=session.session_id, run_id=run.run_id)

    store.save_session(session)
    store.save_run(run)
    store.append_event(event)
    checkpoint = Checkpoint(session_id=session.session_id, run_id=run.run_id, run_state=run)
    store.write_checkpoint(checkpoint)
    assets_dir = store.assets_dir(session.session_id)

    assert store.load_session(session.session_id).title == "Test"
    assert store.load_run(session.session_id, run.run_id).workflow.workflow_id == "fireguard_intelligence"
    assert [item.session_id for item in store.list_sessions()] == [session.session_id]
    assert [item.run_id for item in store.list_runs(session.session_id)] == [run.run_id]
    latest = store.latest_run(session.session_id)
    assert latest is not None
    assert latest.run_id == run.run_id
    assert store.read_events(session.session_id, run.run_id)[0].event_id == event.event_id
    assert store.latest_checkpoint(session.session_id, run.run_id).checkpoint_id == checkpoint.checkpoint_id
    assert assets_dir.exists()
    assert assets_dir.name == "assets"


def test_agentic_package_exports_runtime_entrypoints() -> None:
    assert agentic.AppConfig is AppConfig
    assert agentic.create_app is create_app


def test_env_example_includes_agentic_runtime_settings() -> None:
    lines = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    ).splitlines()
    assert all(line and "=" in line for line in lines)
    keys = {line.split("=", 1)[0] for line in lines}

    assert {
        "FIREGUARD_INTELLIGENCE_PROVIDER",
        "FIREGUARD_INTELLIGENCE_STREAM_TIMEOUT_SECONDS",
        "FIREGUARD_INTELLIGENCE_MAX_RETRIES",
        "FIREGUARD_INTELLIGENCE_MAX_PARALLEL_TOOLS",
        "FIREGUARD_INTELLIGENCE_MAX_FLEET_CONCURRENCY",
        "FIREGUARD_INTELLIGENCE_DEFAULT_AGENT_TIMEOUT_SECONDS",
        "FIREGUARD_INTELLIGENCE_DEFAULT_TOOL_TIMEOUT_SECONDS",
        "EXA_BASE_URL",
        "FIREGUARD_DATA_BOOTSTRAP_ENABLED",
        "FIREGUARD_DATA_BOOTSTRAP_MAX_DOCS_PER_INDEX",
        "FIREGUARD_DATA_BOOTSTRAP_PAGE_SIZE",
        "DOCKER_SANDBOX_CONTAINER_PREFIX",
        "DOCKER_SANDBOX_NETWORK",
        "DOCKER_SANDBOX_POOL_SIZE",
        "DOCKER_SANDBOX_PIP_PACKAGES",
    }.issubset(keys)


def test_agentic_api_creates_sessions_and_exposes_settings(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path))

    with TestClient(app) as client:
        settings = client.get("/settings")
        created = client.post(
            "/sessions",
            json={"title": "FireGuard check", "metadata": {"area": "bc"}},
        )
        asset_path = app.state.engine.store.assets_dir(created.json()["session_id"]) / "plot.txt"
        asset_path.write_text("asset", encoding="utf-8")
        asset = client.get(f"/sessions/{created.json()['session_id']}/assets/plot.txt")
        missing_asset = client.get(f"/sessions/{created.json()['session_id']}/assets/missing.txt")
        listed = client.get("/sessions")

    assert settings.status_code == 200
    assert settings.json()["fireguard_data_configured"] is True
    assert settings.json()["fireguard_data_bootstrap_enabled"] is True
    assert created.status_code == 200
    assert created.json()["title"] == "FireGuard check"
    assert created.json()["metadata"] == {"area": "bc"}
    assert asset.status_code == 200
    assert asset.text == "asset"
    assert missing_asset.status_code == 404
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_chat_messages_keep_annotation_only_assistant_entries() -> None:
    questions = [{"id": "area", "question": "Which area?", "options": ["North", "South"]}]
    messages = _chat_messages(
        {"prompt": "assess detections", "started_at": "2026-01-01T00:00:00Z"},
        [
            {
                "role": "assistant",
                "content": (
                    '{"action":"ask_user","user_response":"","handoff":null,'
                    '"questions":[{"id":"area","question":"Which area?","options":["North","South"]}]}'
                ),
                "agent_id": "chat_agent",
                "run_id": "run_test",
            }
        ],
        [
            {
                "event_id": "evt_ask",
                "event_type": "agent.message.completed",
                "agent_id": "chat_agent",
                "data": {"structured": {"action": "ask_user", "questions": questions}},
            }
        ],
    )

    assert messages[1]["content"] == ""
    assert messages[1]["annotations"] == [
        {
            "type": "structured.ask_user",
            "event_id": "evt_ask",
            "tool_name": "ask_user",
            "output": {"title": "Clarify request", "questions": questions},
        }
    ]


def test_agentic_main_runs_configured_app(monkeypatch, tmp_path: Path) -> None:
    config = _config(tmp_path).model_copy(update={"host": "127.0.0.7", "port": 8877})
    calls: dict[str, object] = {}

    def build_app(received_config: AppConfig):
        calls["config"] = received_config
        return "app-object"

    def run_app(app, *, host: str, port: int) -> None:
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr("app.agentic.main.get_config", lambda: config)
    monkeypatch.setattr("app.agentic.main.create_app", build_app)
    monkeypatch.setattr("app.agentic.main.uvicorn.run", run_app)

    agentic_main()

    assert calls == {
        "config": config,
        "app": "app-object",
        "host": "127.0.0.7",
        "port": 8877,
    }


def test_main_app_mounts_agentic_api_and_removes_old_intelligence_routes() -> None:
    with TestClient(fireguard_app) as client:
        assert client.get("/api/intelligence/health").status_code == 200
        for path in (
            "/api/workflows",
            "/api/workflow-runs/run_test",
            "/api/skills",
            "/api/memory",
            "/api/tools",
            "/api/triggers",
        ):
            assert client.get(path).status_code == 404


def test_main_app_loads_root_env_before_agentic_runtime() -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    load_line = None
    agentic_line = None
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "load_env"
        ):
            load_line = node.lineno
        if isinstance(node, ast.Assign):
            target_names = [
                target.id for target in node.targets if isinstance(target, ast.Name)
            ]
            if (
                "agentic_app" in target_names
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "create_agentic_app"
            ):
                agentic_line = node.lineno

    assert load_line is not None
    assert agentic_line is not None
    assert load_line < agentic_line


def test_main_app_mounts_complete_agentic_route_surface() -> None:
    mount = next(
        route for route in fireguard_app.routes
        if getattr(route, "path", None) == "/api/intelligence"
    )
    actual_routes = {
        (method, route.path)
        for route in mount.app.routes
        for method in getattr(route, "methods", set())
        if method in {"GET", "POST"}
        and not str(route.path).startswith(("/docs", "/redoc", "/openapi.json"))
    }

    assert actual_routes == {
        ("GET", "/health"),
        ("GET", "/settings"),
        ("GET", "/sessions"),
        ("POST", "/sessions"),
        ("GET", "/sessions/{session_id}/runs/latest"),
        ("POST", "/sessions/{session_id}/workflows/runs"),
        ("POST", "/sessions/{session_id}/chat/runs"),
        ("GET", "/sessions/{session_id}/runs/{run_id}"),
        ("GET", "/sessions/{session_id}/runs/{run_id}/events"),
        ("GET", "/sessions/{session_id}/runs/{run_id}/chat"),
        ("GET", "/sessions/{session_id}/runs/{run_id}/history"),
        ("GET", "/sessions/{session_id}/runs/{run_id}/trace"),
        ("GET", "/sessions/{session_id}/runs/{run_id}/nodes/{node_id}"),
        ("GET", "/sessions/{session_id}/runs/{run_id}/stream"),
        ("POST", "/sessions/{session_id}/runs/{run_id}/approvals/{approval_id}"),
        ("POST", "/sessions/{session_id}/runs/{run_id}/restart"),
        ("POST", "/sessions/{session_id}/chat/restart"),
        ("POST", "/sessions/{session_id}/runs/{run_id}/stop"),
        ("GET", "/sessions/{session_id}/agents/{agent_id}/history"),
        ("GET", "/sessions/{session_id}/assets/{filename}"),
    }


def test_main_app_parent_route_surface_stays_narrow() -> None:
    actual_routes = {
        (method, route.path)
        for route in fireguard_app.routes
        for method in getattr(route, "methods", set())
        if method in {"GET", "POST"}
        and not str(route.path).startswith(("/docs", "/redoc", "/openapi.json"))
    }
    mount_paths = {
        ("MOUNT", route.path)
        for route in fireguard_app.routes
        if getattr(route, "path", None) == "/api/intelligence"
    }

    assert actual_routes | mount_paths == {
        ("MOUNT", "/api/intelligence"),
        ("GET", "/api/health"),
        ("GET", "/api/config"),
        ("GET", "/api/stats"),
        ("POST", "/api/replay/stream"),
    }
