from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from app.agentic.api import create_app
from app.agentic.config import AppConfig
from app.agentic.docker_sandbox import DockerSandboxManager
from app.agentic.engine import (
    WorkflowEngine,
    _agent_user_message,
    _assistant_visible_content,
)
from app.agentic.models import (
    AgentDefinition,
    ChatMessage,
    CreateSessionRequest,
    MessageRole,
    ModelTier,
    NodeStatus,
    NodeRunState,
    RestartRunRequest,
    RunStatus,
    StartRunRequest,
    StreamEvent,
    TokenUsage,
    ToolDefinition,
    TraceEvent,
    WorkflowRun,
    utc_now,
)
from app.agentic.chat_stream import ChatComplete, ChatDelta
from app.agentic.project_data import PROJECT_DATA_PATH, ProjectDataBootstrapper
from app.agentic.storage import EventBroker, FileStore
from app.agentic.tools import build_base_tool_registry
from app.agentic.workflows import built_in_workflow


class ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.user_contents: list[str] = []
        self.system_contents: list[str] = []
        self.response_formats: list[dict[str, Any] | None] = []

    async def stream_chat(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        model_tier: ModelTier,
        call_type: str,
        emit_retry: Any,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[ChatDelta | ChatComplete | TokenUsage]:
        del emit_retry
        if len(self.responses) == 0:
            raise AssertionError(f"unexpected model call {call_type}")
        content = self.responses.pop(0)
        self.system_contents.append(messages[0].content if len(messages) > 0 else "")
        self.user_contents.append(messages[-1].content if len(messages) > 0 else "")
        self.response_formats.append(response_format)
        self.calls.append(
            {
                "call_type": call_type,
                "model_tier": model_tier.value,
                "message_roles": [message.role.value for message in messages],
                "tool_names": [tool.name for tool in tools],
            }
        )
        midpoint = max(1, len(content) // 2)
        yield ChatDelta(content[:midpoint])
        yield ChatDelta(content[midpoint:])
        yield TokenUsage(
            model="scripted",
            model_tier=model_tier,
            call_type=call_type,
            prompt_tokens=1,
            completion_tokens=2,
            total_tokens=3,
        )
        yield ChatComplete(
            message=ChatMessage(role=MessageRole.assistant, content=content),
            usage=None,
        )

    async def close(self) -> None:
        return None


class StubProjectDataBootstrapper:
    enabled = True

    async def ensure_project_data(self, session_id: str) -> dict[str, Any]:
        return {
            "scope": "fireguard",
            "path": PROJECT_DATA_PATH,
            "index_prefix": "fireguard",
            "datasets": [
                {
                    "name": "firms",
                    "index": "fireguard-firms",
                    "file": "firms.ndjson",
                    "total_matches": 3,
                    "exported_docs": 3,
                    "truncated": False,
                    "source_fields": ["source"],
                }
            ],
        }


class FailingProjectDataBootstrapper:
    enabled = True

    async def ensure_project_data(self, session_id: str) -> dict[str, Any]:
        del session_id
        raise RuntimeError("project data unavailable")


class ScriptedSandboxManager:
    enabled = True

    async def start(self) -> None:
        return None

    async def ensure(self, session_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            session_id=session_id,
            container_id="container_test",
            container_name="container_test",
            image="fireguard-intelligence-sandbox:local",
            timeout_seconds=60,
            idle_timeout_seconds=60,
            packages=[],
            leased_from_pool=False,
        )

    async def terminate(self, session_id: str) -> None:
        del session_id
        return None

    async def close(self) -> None:
        return None


def _make_engine(tmp_path: Path, responses: list[str]) -> tuple[WorkflowEngine, ScriptedClient]:
    config = AppConfig(
        state_dir=tmp_path,
        fireguard_elasticsearch_url="http://elastic.invalid",
        fireguard_elasticsearch_api_key="test-key",
        default_tool_timeout_seconds=5,
        max_parallel_tools=4,
    )
    store = FileStore(config)
    broker = EventBroker()
    client = ScriptedClient(responses)
    sandbox_manager = DockerSandboxManager(config)
    tools = build_base_tool_registry(
        default_timeout_seconds=config.default_tool_timeout_seconds,
        max_parallel_tools=config.max_parallel_tools,
        fireguard_elasticsearch_url=config.fireguard_elasticsearch_url,
        fireguard_elasticsearch_api_key=config.fireguard_elasticsearch_api_key,
        fireguard_elasticsearch_index_prefix=config.fireguard_elasticsearch_index_prefix,
        sandbox_manager=sandbox_manager,
    )
    return (
        WorkflowEngine(
            config=config,
            store=store,
            broker=broker,
            client=client,  # type: ignore[arg-type]
            tools=tools,
            sandbox_manager=sandbox_manager,
            project_data_bootstrapper=ProjectDataBootstrapper(config, sandbox_manager),
        ),
        client,
    )


async def _finish_run(engine: WorkflowEngine, run: WorkflowRun) -> WorkflowRun:
    while True:
        task = engine._tasks.get((run.session_id, run.run_id))
        if task is None:
            return engine.get_run(run.session_id, run.run_id)
        await task


async def _replay_until_completed(engine: WorkflowEngine, run: WorkflowRun) -> list[StreamEvent]:
    events: list[StreamEvent] = []
    async for event in engine.stream_events(run.session_id, run.run_id, last_event_id=None):
        events.append(event)
        if event.event_type == "run.completed":
            break
    return events


def test_chat_run_streams_stores_trace_history_and_checkpoints(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, client = _make_engine(
            tmp_path,
            [
                (
                    '{"action":"respond","user_response":"FireGuard ready.",'
                    '"handoff":null,"questions":null}'
                ),
            ],
        )
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard check"))
            run = engine.start_chat_run(session.session_id, StartRunRequest(prompt="hello"))
            completed = await _finish_run(engine, run)
            replayed = await _replay_until_completed(engine, completed)
        finally:
            await engine.close()

        assert completed.status == RunStatus.completed
        assert completed.current_node_id == "terminal"
        assert completed.node_states["chat_agent"].output_payload is not None
        assert completed.node_states["chat_agent"].output_payload["message"] == "FireGuard ready."
        assert client.calls == [
            {
                "call_type": "agent:chat_agent",
                "model_tier": "light",
                "message_roles": ["system", "user"],
                "tool_names": [],
            }
        ]
        assert client.response_formats == [
            next(agent for agent in completed.workflow.agents if agent.agent_id == "chat_agent").response_format
        ]

        event_types = [event.event_type for event in engine.get_events(run.session_id, run.run_id)]
        assert "agent.message.delta" in event_types
        assert "agent.message.completed" in event_types
        assert "usage.updated" in event_types
        assert "workflow.handoff.created" in event_types
        assert "run.completed" in event_types
        assert "checkpoint.created" in event_types
        assert [event.event_type for event in replayed][-1] == "run.completed"

        trace_types = [
            item["event_type"]
            for item in engine.store.read_run_trace(run.session_id, run.run_id)
        ]
        assert trace_types[: len(event_types)] == event_types

        history = engine.store.read_run_history(run.session_id, run.run_id)
        assert [entry["role"] for entry in history] == ["system", "user", "assistant"]
        assert history[-1]["content"].endswith('"questions":null}')
        assert engine.store.latest_checkpoint(run.session_id, run.run_id).node_id == "terminal"
        assert completed.usage[0].call_type == "agent:chat_agent"
        message_event = next(
            event for event in engine.get_events(run.session_id, run.run_id)
            if event.event_type == "agent.message.completed"
        )
        event_checkpoint = engine.store.checkpoint_for_event(
            run.session_id, run.run_id, message_event.event_id
        )
        assert event_checkpoint.node_id == "chat_agent"
        checkpoint_event = next(
            event for event in engine.get_events(run.session_id, run.run_id)
            if event.event_type == "checkpoint.created"
            and event.data["checkpoint_id"] == event_checkpoint.checkpoint_id
        )
        assert engine.store.checkpoint_for_event(
            run.session_id, run.run_id, checkpoint_event.event_id
        ).checkpoint_id == event_checkpoint.checkpoint_id

    asyncio.run(exercise())


def test_stream_events_resumes_after_last_event_id(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(tmp_path, [])
        session_id = "ses_test"
        run_id = "run_test"
        first = StreamEvent(
            event_id="evt_first",
            event_type="run.started",
            session_id=session_id,
            run_id=run_id,
        )
        second = StreamEvent(
            event_id="evt_second",
            event_type="agent.message.delta",
            session_id=session_id,
            run_id=run_id,
            data={"delta": "FireGuard"},
        )
        third = StreamEvent(
            event_id="evt_third",
            event_type="run.completed",
            session_id=session_id,
            run_id=run_id,
        )
        try:
            engine.store.append_event(first)
            engine.store.append_event(second)
            engine.store.append_event(third)

            stream = engine.stream_events(
                session_id,
                run_id,
                last_event_id=first.event_id,
            )
            try:
                resumed_first = await asyncio.wait_for(anext(stream), timeout=1)
                resumed_second = await asyncio.wait_for(anext(stream), timeout=1)
            finally:
                await stream.aclose()
        finally:
            await engine.close()

        assert [resumed_first.event_id, resumed_second.event_id] == [
            second.event_id,
            third.event_id,
        ]
        assert second.to_sse().startswith(
            "id: evt_second\n"
            "event: agent.message.delta\n"
        )
        assert '"event_id":"evt_second"' in second.to_sse()

    asyncio.run(exercise())


def test_start_run_persists_initial_state_without_waiting_for_provider(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(tmp_path, [])
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard runtime"))
            run = engine.start_run(
                session.session_id,
                StartRunRequest(
                    prompt="Build an intelligence report",
                    payload={"area": "bc"},
                ),
            )
            loaded = engine.get_run(session.session_id, run.run_id)
        finally:
            await engine.close()

        assert loaded.workflow.workflow_id == "fireguard_intelligence"
        assert loaded.current_node_id == "human_trigger"
        assert loaded.node_states["human_trigger"].input_payload == {
            "prompt": "Build an intelligence report",
            "payload": {"area": "bc"},
        }

    asyncio.run(exercise())


def test_restart_requires_checkpoint(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(tmp_path, [])
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard runtime"))
            run = engine.start_run(session.session_id, StartRunRequest(prompt="Build a report"))
            try:
                engine.restart_run(session.session_id, run.run_id, RestartRunRequest())
            except FileNotFoundError:
                return
            raise AssertionError("restart without checkpoint should fail")
        finally:
            await engine.close()

    asyncio.run(exercise())


def test_builtin_workflow_routes_downstream_errors_to_chat_agent(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(tmp_path, [])
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard runtime"))
            run = engine.start_run(session.session_id, StartRunRequest(prompt="Build a report"))

            assert engine._next_node(run, "research_agent", "error") == "chat_agent"
            assert engine._next_node(run, "writer_agent", "error") == "chat_agent"
            assert engine._next_node(run, "style_agent", "error") == "chat_agent"
            assert engine._next_node(run, "chat_agent", "report_failure") == "terminal"
            assert engine._next_node(run, "chat_agent", "ask_user") == "terminal"
            assert engine._next_node(run, "chat_agent", "respond") == "terminal"
            assert engine._next_node(run, "chat_agent", "handoff_to_research") == "research_agent"
            assert engine._next_node(run, "chat_agent", "handoff_to_writer") == "writer_agent"
        finally:
            await engine.close()

    asyncio.run(exercise())


def test_lineage_reads_preserve_parent_run_subagent_context(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])
    session = engine.create_session(CreateSessionRequest(title="FireGuard lineage"))
    workflow = built_in_workflow("fireguard_intelligence")
    parent = WorkflowRun(session_id=session.session_id, run_id="run_parent", workflow=workflow)
    child = parent.model_copy(
        deep=True,
        update={"run_id": "run_child", "parent_run_id": parent.run_id},
    )
    engine.store.save_run(parent)
    engine.store.save_run(child)
    engine.store.append_event(
        StreamEvent(
            event_id="sse_parent_subagent",
            event_type="subagent.completed",
            session_id=session.session_id,
            run_id=parent.run_id,
            node_id="research_agent",
            agent_id="subagent_old",
            data={"ok": True},
        )
    )
    engine.store.append_event(
        StreamEvent(
            event_id="sse_child_writer",
            event_type="agent.started",
            session_id=session.session_id,
            run_id=child.run_id,
            node_id="writer_agent",
            agent_id="writer_agent",
        )
    )
    engine.store.append_history(
        session.session_id,
        parent.run_id,
        "research_agent",
        ChatMessage(role=MessageRole.assistant, content="parent research"),
    )
    engine.store.append_history(
        session.session_id,
        child.run_id,
        "writer_agent",
        ChatMessage(role=MessageRole.assistant, content="child rewrite"),
    )

    assert [
        event.event_id for event in engine.get_events(session.session_id, child.run_id)
    ] == ["sse_child_writer"]
    assert [
        event.event_id
        for event in engine.get_events(
            session.session_id, child.run_id, include_ancestors=True
        )
    ] == ["sse_parent_subagent", "sse_child_writer"]
    assert [
        entry["content"]
        for entry in engine.get_run_history(
            session.session_id, child.run_id, include_ancestors=True
        )
    ] == ["parent research", "child rewrite"]


def test_writer_to_style_handoff_uses_editorial_fireguard_task(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])

    payload = engine._task_for_edge(
        "writer_agent",
        "style_agent",
        "completed",
        {"message": "# Draft\n\n- A\n- B"},
        {"prompt": "Make a FireGuard report"},
    )

    assert payload["objective"] == (
        "Edit the markdown draft into a polished FireGuard operational intelligence report."
    )
    assert payload["report_markdown"] == "# Draft\n\n- A\n- B"
    assert any("Reduce bullet-heavy note dumps" in item for item in payload["constraints"])
    assert any("Preserve factual content exactly" in item for item in payload["constraints"])
    assert any("Do not invent missing analysis" in item for item in payload["constraints"])


def test_research_handoff_routes_through_writer(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, client = _make_engine(
            tmp_path,
            [
                (
                    '{"action":"handoff_to_research","user_response":"Checking FireGuard context.",'
                    '"handoff":{"objective":"Assess active detections near the route.",'
                    '"user_request":"Assess active detections near the route.",'
                    '"constraints":["Use FireGuard indexed data."],'
                    '"questions_to_answer":["What changed?"],'
                    '"context":{"area":"route"},"attachments_summary":[]},"questions":null}'
                ),
                "Research notes.",
                "Final report.",
                "Styled report.",
            ],
        )
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard handoff"))
            run = engine.start_chat_run(
                session.session_id,
                StartRunRequest(prompt="Assess active detections near the route."),
            )
            completed = await _finish_run(engine, run)
        finally:
            await engine.close()

        assert completed.status == RunStatus.completed
        assert completed.current_node_id == "terminal"
        assert completed.node_states["research_agent"].output_payload is not None
        assert completed.node_states["writer_agent"].output_payload is not None
        assert completed.node_states["writer_agent"].output_payload["message"] == "Final report."
        assert completed.node_states["style_agent"].output_payload is not None
        assert completed.node_states["style_agent"].output_payload["message"] == "Styled report."
        assert [call["call_type"] for call in client.calls] == [
            "agent:chat_agent",
            "agent:research_agent",
            "agent:writer_agent",
            "agent:style_agent",
        ]
        assert "fireguard_stats" in client.calls[1]["tool_names"]
        assert "exa_search" in client.calls[1]["tool_names"]
        assert "sandbox_exec" in client.calls[1]["tool_names"]
        assert "spawn_subagent" in client.calls[1]["tool_names"]
        assert "Final report." in client.user_contents[-1]

        handoffs = [
            event
            for event in engine.get_events(run.session_id, run.run_id)
            if event.event_type == "workflow.handoff.created"
        ]
        handoff_pairs = [
            (event.data["from_node_id"], event.data["to_node_id"])
            for event in handoffs
            if "from_node_id" in event.data
        ]
        assert ("chat_agent", "research_agent") in handoff_pairs
        assert ("research_agent", "writer_agent") in handoff_pairs
        assert ("writer_agent", "style_agent") in handoff_pairs
        assert ("style_agent", "terminal") in handoff_pairs

        history = engine.store.read_run_history(run.session_id, run.run_id)
        assert [entry["agent_id"] for entry in history if entry["role"] == "assistant"] == [
            "chat_agent",
            "research_agent",
            "writer_agent",
            "style_agent",
        ]
        trace_types = [
            item["event_type"]
            for item in engine.store.read_run_trace(run.session_id, run.run_id)
        ]
        assert trace_types[-2:] == ["run.completed", "checkpoint.created"]

    asyncio.run(exercise())


def test_chat_writer_handoff_skips_research_node(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, client = _make_engine(
            tmp_path,
            [
                (
                    '{"action":"handoff_to_writer","user_response":"Updating the report.",'
                    '"handoff":{"objective":"Shorten the existing report.",'
                    '"user_request":"Shorten the existing report.",'
                    '"constraints":["Preserve FireGuard facts."],'
                    '"questions_to_answer":[],"context":{"session_context":'
                    '{"active_result":{"kind":"deliverable","content":"Prior FireGuard report"}}},'
                    '"attachments_summary":[]},"questions":null}'
                ),
                "Shorter report.",
                "Styled shorter report.",
            ],
        )
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard writer handoff"))
            run = engine.start_chat_run(
                session.session_id,
                StartRunRequest(
                    prompt="make the prior report shorter",
                    payload={
                        "session_context": {
                            "active_result": {
                                "kind": "deliverable",
                                "content": "Prior FireGuard report",
                            }
                        }
                    },
                ),
            )
            completed = await _finish_run(engine, run)
        finally:
            await engine.close()

        assert completed.status == RunStatus.completed
        assert completed.node_states["research_agent"].status == NodeStatus.pending
        assert completed.node_states["writer_agent"].output_payload is not None
        assert completed.node_states["writer_agent"].output_payload["message"] == "Shorter report."
        assert [call["call_type"] for call in client.calls] == [
            "agent:chat_agent",
            "agent:writer_agent",
            "agent:style_agent",
        ]
        handoff_pairs = [
            (event.data["from_node_id"], event.data["to_node_id"])
            for event in engine.get_events(run.session_id, run.run_id)
            if event.event_type == "workflow.handoff.created" and "from_node_id" in event.data
        ]
        assert ("chat_agent", "writer_agent") in handoff_pairs
        assert ("research_agent", "writer_agent") not in handoff_pairs

    asyncio.run(exercise())


def test_project_data_context_is_omitted_when_sandbox_disabled(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, client = _make_engine(
            tmp_path,
            [
                (
                    '{"action":"respond","user_response":"FireGuard ready.",'
                    '"handoff":null,"questions":null}'
                ),
            ],
        )
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard context"))
            run = engine.start_chat_run(session.session_id, StartRunRequest(prompt="hello"))
            completed = await _finish_run(engine, run)
        finally:
            await engine.close()

        assert completed.status == RunStatus.completed
        assert PROJECT_DATA_PATH not in client.system_contents[0]
        event_types = [event.event_type for event in engine.get_events(run.session_id, run.run_id)]
        assert "project_data.starting" not in event_types

    asyncio.run(exercise())


def test_agent_prompt_includes_fireguard_data_context_when_enabled(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])
    engine.project_data_bootstrapper = StubProjectDataBootstrapper()  # type: ignore[assignment]
    agent = AgentDefinition(
        agent_id="research_agent",
        name="Research",
        system_prompt="Base prompt.",
    )

    prompt = engine._agent_system_prompt("ses_test", agent)

    assert "Base prompt." in prompt
    assert "FireGuard sandbox data context" in prompt
    assert f"{PROJECT_DATA_PATH}/manifest.json" in prompt
    assert "firms.ndjson" in prompt
    assert "bcws_incidents.ndjson" in prompt
    assert "sandbox_exec" in prompt


def test_project_data_bootstrap_events_use_compact_manifest(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(tmp_path, [])
        engine.project_data_bootstrapper = StubProjectDataBootstrapper()  # type: ignore[assignment]
        run = WorkflowRun(
            session_id="ses_test",
            run_id="run_test",
            workflow=built_in_workflow("fireguard_intelligence"),
        )
        try:
            await engine._ensure_project_data(run)
        finally:
            await engine.close()

        events = engine.get_events(run.session_id, run.run_id)
        assert [event.event_type for event in events] == [
            "project_data.starting",
            "project_data.ready",
        ]
        assert events[0].data == {"scope": "fireguard", "path": PROJECT_DATA_PATH}
        assert events[1].data["manifest"] == {
            "scope": "fireguard",
            "path": PROJECT_DATA_PATH,
            "index_prefix": "fireguard",
            "reused": False,
            "datasets": [
                {
                    "name": "firms",
                    "index": "fireguard-firms",
                    "file": "firms.ndjson",
                    "total_matches": 3,
                    "exported_docs": 3,
                    "truncated": False,
                }
            ],
        }

    asyncio.run(exercise())


def test_setup_failure_marks_run_failed_and_emits_events(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(tmp_path, [])
        engine.sandbox_manager = ScriptedSandboxManager()  # type: ignore[assignment]
        engine.project_data_bootstrapper = FailingProjectDataBootstrapper()  # type: ignore[assignment]
        try:
            session = engine.create_session(CreateSessionRequest(title="setup failure"))
            run = engine.start_chat_run(session.session_id, StartRunRequest(prompt="hello"))
            completed = await _finish_run(engine, run)
        finally:
            await engine.close()

        assert completed.status == RunStatus.failed
        assert completed.current_node_id == "human_trigger"
        event_types = [event.event_type for event in engine.get_events(run.session_id, run.run_id)]
        assert event_types == [
            "run.started",
            "sandbox.starting",
            "sandbox.ready",
            "project_data.starting",
            "project_data.failed",
            "run.failed",
        ]

    asyncio.run(exercise())


def test_api_chat_run_exposes_chat_trace_events_and_node_detail(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(
            tmp_path,
            [
                (
                    '{"action":"respond","user_response":"FireGuard ready.",'
                    '"handoff":null,"questions":null}'
                ),
            ],
        )
        app = create_app(engine.config, engine=engine)
        transport = httpx.ASGITransport(app=app)
        try:
            await engine.start()
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                session_response = await client.post(
                    "/sessions", json={"title": "FireGuard API check"}
                )
                assert session_response.status_code == 200
                session_id = session_response.json()["session_id"]

                run_response = await client.post(
                    f"/sessions/{session_id}/chat/runs",
                    json={"prompt": "hello", "payload": {"source": "chat"}},
                )
                assert run_response.status_code == 200
                run = WorkflowRun.model_validate(run_response.json())
                completed = await _finish_run(engine, run)

                latest = await client.get(f"/sessions/{session_id}/runs/latest")
                events = await client.get(
                    f"/sessions/{session_id}/runs/{completed.run_id}/events"
                )
                chat = await client.get(f"/sessions/{session_id}/runs/{completed.run_id}/chat")
                trace = await client.get(
                    f"/sessions/{session_id}/runs/{completed.run_id}/trace"
                )
                node = await client.get(
                    f"/sessions/{session_id}/runs/{completed.run_id}/nodes/chat_agent"
                )

            assert latest.status_code == 200
            assert latest.json()["run_id"] == completed.run_id
            assert events.status_code == 200
            assert any(item["event_type"] == "agent.message.delta" for item in events.json())
            assert chat.status_code == 200
            assert chat.json()["messages"][-1]["content"] == "FireGuard ready."
            assert trace.status_code == 200
            assert trace.json()[-2]["event_type"] == "run.completed"
            assert node.status_code == 200
            assert node.json()["agent_id"] == "chat_agent"
            assert node.json()["history"][-1]["content"].endswith('"questions":null}')
        finally:
            await engine.close()

    asyncio.run(exercise())


def test_api_chat_restart_uses_event_checkpoint_and_user_message(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, client_for_run = _make_engine(
            tmp_path,
            [
                (
                    '{"action":"respond","user_response":"FireGuard ready.",'
                    '"handoff":null,"questions":null}'
                ),
                (
                    '{"action":"respond","user_response":"Restarted FireGuard response.",'
                    '"handoff":null,"questions":null}'
                ),
            ],
        )
        app = create_app(engine.config, engine=engine)
        transport = httpx.ASGITransport(app=app)
        try:
            await engine.start()
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                session_response = await client.post(
                    "/sessions", json={"title": "FireGuard restart check"}
                )
                session_id = session_response.json()["session_id"]
                run_response = await client.post(
                    f"/sessions/{session_id}/chat/runs",
                    json={"prompt": "first prompt", "payload": {"source": "chat"}},
                )
                run = WorkflowRun.model_validate(run_response.json())
                completed = await _finish_run(engine, run)
                message_event = next(
                    event for event in engine.get_events(session_id, completed.run_id)
                    if event.event_type == "agent.message.completed"
                )

                restart_response = await client.post(
                    f"/sessions/{session_id}/chat/restart",
                    json={
                        "run_id": completed.run_id,
                        "event_id": message_event.event_id,
                        "node_id": "chat_agent",
                        "user_message": "second prompt",
                    },
                )
                assert restart_response.status_code == 200
                restarted = WorkflowRun.model_validate(restart_response.json())
                restarted_completed = await _finish_run(engine, restarted)

            assert restarted.parent_run_id == completed.run_id
            assert restarted_completed.status == RunStatus.completed
            assert "second prompt" in client_for_run.user_contents[-1]
            assert "first prompt" not in client_for_run.user_contents[-1]
            assert restarted_completed.node_states["chat_agent"].input_payload is not None
            assert restarted_completed.node_states["chat_agent"].input_payload["prompt"] == "second prompt"
        finally:
            await engine.close()

    asyncio.run(exercise())


def test_start_chat_run_includes_prior_chat_history(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(
            tmp_path,
            [
                (
                    '{"action":"respond","user_response":"I have the prior context.",'
                    '"handoff":null,"questions":null}'
                ),
            ],
        )
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard context"))
            engine.store.append_history(
                session.session_id,
                "run_previous",
                "chat_agent",
                ChatMessage(
                    role=MessageRole.user,
                    content='{"prompt":"hi","payload":{"source":"chat"}}',
                ),
            )
            engine.store.append_history(
                session.session_id,
                "run_previous",
                "chat_agent",
                ChatMessage(
                    role=MessageRole.assistant,
                    content=(
                        '{"action":"respond","user_response":"Hi. How can I help?",'
                        '"handoff":null}'
                    ),
                ),
            )

            run = engine.start_chat_run(
                session.session_id, StartRunRequest(prompt="what was my previous message")
            )
            payload = run.node_states["human_trigger"].input_payload
            completed = await _finish_run(engine, run)
        finally:
            await engine.close()

        assert completed.status == RunStatus.completed
        assert payload is not None
        assert payload["prompt"] == "what was my previous message"
        assert payload["payload"]["previous_user_message"] == "hi"
        assert payload["payload"]["conversation_history"] == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hi. How can I help?"},
        ]

    asyncio.run(exercise())


def test_start_chat_run_links_latest_run_and_session_context(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(
            tmp_path,
            [
                (
                    '{"action":"respond","user_response":"I can update that report.",'
                    '"handoff":null,"questions":null}'
                ),
            ],
        )
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard follow-up"))
            workflow = built_in_workflow("fireguard_intelligence")
            prior = WorkflowRun(
                session_id=session.session_id,
                run_id="run_prior",
                workflow=workflow,
                status=RunStatus.completed,
                current_node_id="terminal",
                node_states={
                    node.node_id: NodeRunState(node_id=node.node_id)
                    for node in workflow.nodes
                },
            )
            prior.node_states["style_agent"] = prior.node_states["style_agent"].model_copy(
                update={
                    "status": NodeStatus.completed,
                    "output_payload": {"message": "Prior FireGuard report"},
                    "completed_at": utc_now(),
                }
            )
            engine.store.save_run(prior)

            run = engine.start_chat_run(
                session.session_id, StartRunRequest(prompt="update the prior report")
            )
            payload = run.node_states["human_trigger"].input_payload
            completed = await _finish_run(engine, run)
        finally:
            await engine.close()

        assert completed.status == RunStatus.completed
        assert run.parent_run_id == prior.run_id
        assert payload is not None
        assert payload["payload"]["parent_run_id"] == prior.run_id
        session_context = payload["payload"]["session_context"]
        assert session_context["latest_run"]["run_id"] == prior.run_id
        assert session_context["active_result"]["kind"] == "deliverable"
        assert session_context["active_result"]["content"] == "Prior FireGuard report"
        assert payload["payload"]["prior_result"] == session_context["active_result"]

    asyncio.run(exercise())


def test_start_chat_run_includes_latest_failure_context(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(tmp_path, [])
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard recovery"))
            workflow = built_in_workflow("fireguard_intelligence")
            prior = WorkflowRun(
                session_id=session.session_id,
                run_id="run_failed",
                workflow=workflow,
                status=RunStatus.failed,
                current_node_id="writer_agent",
                node_states={
                    node.node_id: NodeRunState(node_id=node.node_id)
                    for node in workflow.nodes
                },
            )
            prior.node_states["research_agent"] = prior.node_states[
                "research_agent"
            ].model_copy(
                update={
                    "status": NodeStatus.completed,
                    "output_payload": {"message": "Verified detections: 7"},
                    "completed_at": utc_now(),
                }
            )
            prior.node_states["writer_agent"] = prior.node_states["writer_agent"].model_copy(
                update={
                    "status": NodeStatus.failed,
                    "error": "writer exceeded max turns",
                    "completed_at": utc_now(),
                }
            )
            engine.store.save_run(prior)

            run = engine.start_chat_run(
                session.session_id, StartRunRequest(prompt="what happened?")
            )
            payload = run.node_states["human_trigger"].input_payload
        finally:
            await engine.close()

        assert run.parent_run_id == prior.run_id
        assert payload is not None
        active_result = payload["payload"]["session_context"]["active_result"]
        assert active_result["kind"] == "failure"
        assert active_result["node_id"] == "writer_agent"
        assert active_result["error"] == "writer exceeded max turns"
        assert active_result["last_successful_result"]["kind"] == "research_notes"
        assert (
            active_result["last_successful_result"]["content"]
            == "Verified detections: 7"
        )
        assert payload["payload"]["prior_result"] == active_result

    asyncio.run(exercise())


def test_default_research_handoff_preserves_session_context(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])
    session_context = {
        "latest_run": {"run_id": "run_prior", "status": "completed"},
        "active_result": {
            "kind": "deliverable",
            "node_id": "style_agent",
            "content": "Prior FireGuard report",
            "truncated": False,
        },
    }

    handoff = engine._default_research_handoff(
        {
            "prompt": "add the latest perimeter context",
            "payload": {"source": "chat", "session_context": session_context},
        },
        "I'll update the report.",
    )

    assert handoff["context"]["session_context"] == session_context
    assert handoff["objective"].startswith("Use the provided session context")
    assert any("Ground claims in inspected FireGuard data" in item for item in handoff["constraints"])
    assert any("Do not invent missing data" in item for item in handoff["constraints"])
    assert any(
        "context.session_context.active_result.kind is deliverable" in item
        for item in handoff["constraints"]
    )


def test_default_writer_handoff_preserves_session_context(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])
    session_context = {
        "latest_run": {"run_id": "run_prior", "status": "completed"},
        "active_result": {
            "kind": "deliverable",
            "node_id": "style_agent",
            "content": "Prior FireGuard report",
            "truncated": False,
        },
    }

    handoff = engine._default_writer_handoff(
        {
            "prompt": "make it shorter",
            "payload": {"source": "chat", "session_context": session_context},
        },
        "I'll update the report.",
    )

    assert handoff["context"]["session_context"] == session_context
    assert handoff["objective"].startswith("Edit the existing FireGuard intelligence report")
    assert any("Apply only the edits" in item for item in handoff["constraints"])
    assert any("Do not invent new content" in item for item in handoff["constraints"])
    assert any(
        "context.session_context.active_result.content" in item
        for item in handoff["constraints"]
    )


def test_research_to_writer_task_preserves_session_context(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])
    session_context = {
        "latest_run": {"run_id": "run_prior", "status": "completed"},
        "active_result": {
            "kind": "deliverable",
            "content": "Prior FireGuard report",
        },
    }

    task = engine._task_for_edge(
        "research_agent",
        "writer_agent",
        "default",
        {
            "message": "Research update.",
            "payload": {
                "context": {
                    "session_context": session_context,
                },
            },
        },
        {"prompt": "update the prior report", "payload": {}},
    )

    assert task["session_context"] == session_context
    assert task["research_notes"] == "Research update."
    assert any("Preserve data-quality limits" in item for item in task["constraints"])
    assert any("Do not invent missing data" in item for item in task["constraints"])
    assert any("update that existing report" in item for item in task["constraints"])


def test_api_run_views_can_include_parent_lineage(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(tmp_path, [])
        app = create_app(engine.config, engine=engine)
        transport = httpx.ASGITransport(app=app)
        try:
            session = engine.create_session(CreateSessionRequest(title="FireGuard lineage"))
            workflow = built_in_workflow("fireguard_intelligence")
            parent = WorkflowRun(
                session_id=session.session_id,
                run_id="run_parent",
                workflow=workflow,
                current_node_id="terminal",
                node_states={
                    node.node_id: NodeRunState(node_id=node.node_id)
                    for node in workflow.nodes
                },
            )
            child = WorkflowRun(
                session_id=session.session_id,
                run_id="run_child",
                workflow=workflow,
                current_node_id="terminal",
                parent_run_id=parent.run_id,
                node_states={
                    node.node_id: NodeRunState(node_id=node.node_id)
                    for node in workflow.nodes
                },
            )
            parent.node_states["human_trigger"].input_payload = {
                "prompt": "parent prompt",
                "payload": {},
            }
            child.node_states["human_trigger"].input_payload = {
                "prompt": "child prompt",
                "payload": {},
            }
            engine.store.save_run(parent)
            engine.store.save_run(child)
            engine.store.append_event(
                StreamEvent(
                    event_type="parent.event",
                    session_id=session.session_id,
                    run_id=parent.run_id,
                    node_id="chat_agent",
                    agent_id="chat_agent",
                )
            )
            engine.store.append_event(
                StreamEvent(
                    event_type="child.event",
                    session_id=session.session_id,
                    run_id=child.run_id,
                    node_id="chat_agent",
                    agent_id="chat_agent",
                )
            )
            engine.store.append_history(
                session.session_id,
                parent.run_id,
                "chat_agent",
                ChatMessage(role=MessageRole.assistant, content="parent note"),
            )
            engine.store.append_history(
                session.session_id,
                child.run_id,
                "chat_agent",
                ChatMessage(
                    role=MessageRole.assistant,
                    content=(
                        '{"action":"handoff_to_research","user_response":"",'
                        '"handoff":{"objective":"continue"},"questions":null}'
                    ),
                ),
            )
            engine.store.append_history(
                session.session_id,
                child.run_id,
                "chat_agent",
                ChatMessage(role=MessageRole.assistant, content="child note"),
            )
            engine.store.append_trace(
                TraceEvent(
                    event_type="parent.trace",
                    session_id=session.session_id,
                    run_id=parent.run_id,
                    node_id="chat_agent",
                    agent_id="chat_agent",
                )
            )
            engine.store.append_trace(
                TraceEvent(
                    event_type="child.trace",
                    session_id=session.session_id,
                    run_id=child.run_id,
                    node_id="chat_agent",
                    agent_id="chat_agent",
                )
            )

            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                child_events = await client.get(
                    f"/sessions/{session.session_id}/runs/{child.run_id}/events"
                )
                lineage_events = await client.get(
                    f"/sessions/{session.session_id}/runs/{child.run_id}/events",
                    params={"include_ancestors": "true"},
                )
                lineage_history = await client.get(
                    f"/sessions/{session.session_id}/runs/{child.run_id}/history",
                    params={"include_ancestors": "true"},
                )
                lineage_trace = await client.get(
                    f"/sessions/{session.session_id}/runs/{child.run_id}/trace",
                    params={"include_ancestors": "true"},
                )
                lineage_chat = await client.get(
                    f"/sessions/{session.session_id}/runs/{child.run_id}/chat",
                    params={"include_ancestors": "true"},
                )
                node_detail = await client.get(
                    f"/sessions/{session.session_id}/runs/{child.run_id}/nodes/chat_agent",
                    params={"include_ancestors": "true"},
                )
        finally:
            await engine.close()

        assert [event["event_type"] for event in child_events.json()] == ["child.event"]
        assert [event["event_type"] for event in lineage_events.json()] == [
            "parent.event",
            "child.event",
        ]
        assert [entry["run_id"] for entry in lineage_history.json()] == [
            parent.run_id,
            child.run_id,
            child.run_id,
        ]
        assert [event["event_type"] for event in lineage_trace.json()] == [
            "parent.trace",
            "child.trace",
        ]
        assert [message["content"] for message in lineage_chat.json()["messages"]] == [
            "parent prompt",
            "parent note",
            "child note",
        ]
        assert [entry["run_id"] for entry in node_detail.json()["transcript"]] == [
            parent.run_id,
            child.run_id,
            child.run_id,
        ]

    asyncio.run(exercise())


def test_chat_ask_user_requires_structured_questions(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])
    workflow = built_in_workflow("fireguard_intelligence")
    chat_agent = next(agent for agent in workflow.agents if agent.agent_id == "chat_agent")

    without_questions = engine._structured_chat_output(
        chat_agent,
        '{"action":"ask_user","user_response":"More detail is needed.","handoff":null}',
        {"prompt": "hi"},
    )
    with_questions = engine._structured_chat_output(
        chat_agent,
        (
            '{"action":"ask_user","user_response":"I need one detail.",'
            '"questions":[{"id":"goal","question":"What goal?","options":["Learn","Assess"]}],'
            '"handoff":null}'
        ),
        {"prompt": "assess detections"},
    )

    assert without_questions["action"] == "respond"
    assert with_questions["action"] == "ask_user"
    assert with_questions["questions"] == [
        {"id": "goal", "question": "What goal?", "options": ["Learn", "Assess"]}
    ]


def test_chat_structured_output_parse_failure_is_not_respond(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])
    workflow = built_in_workflow("fireguard_intelligence")
    chat_agent = next(agent for agent in workflow.agents if agent.agent_id == "chat_agent")

    try:
        try:
            engine._structured_chat_output(
                chat_agent,
                '{"action":"handoff_to_research","user_response":"","handoff":null',
                {"prompt": "continue"},
            )
        except RuntimeError as exc:
            assert "invalid structured output JSON" in str(exc)
            return
        raise AssertionError("malformed chat routing output should fail")
    finally:
        asyncio.run(engine.close())


def test_chat_structured_output_accepts_fenced_vertex_route_shape(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])
    workflow = built_in_workflow("fireguard_intelligence")
    chat_agent = next(agent for agent in workflow.agents if agent.agent_id == "chat_agent")

    try:
        output = engine._structured_chat_output(
            chat_agent,
            (
                "```json\n"
                "{\n"
                '  "route": "respond",\n'
                '  "respond": {"message": "Hello from FireGuard."}\n'
                "}\n"
                "```"
            ),
            {"prompt": "hi"},
        )

        assert output["action"] == "respond"
        assert output["user_response"] == "Hello from FireGuard."
    finally:
        asyncio.run(engine.close())


def test_empty_chat_handoff_is_not_replayed_as_visible_history() -> None:
    assert (
        _assistant_visible_content(
            '{"action":"handoff_to_research","user_response":"",'
            '"handoff":{"objective":"continue"},"questions":null}'
        )
        is None
    )
    assert (
        _assistant_visible_content(
            '{"action":"respond","user_response":"Visible response","handoff":null}'
        )
        == "Visible response"
    )


def test_agent_user_message_builds_multimodal_content_parts() -> None:
    message = _agent_user_message(
        {
            "prompt": "Summarize these.",
            "payload": {
                "attachments": [
                    {
                        "name": "chart.png",
                        "media_type": "image/png",
                        "size": 42,
                        "data_url": "data:image/png;base64,abc",
                    },
                    {
                        "name": "brief.pdf",
                        "media_type": "application/pdf",
                        "size": 43,
                        "data_url": "data:application/pdf;base64,def",
                    },
                    {
                        "name": "notes.txt",
                        "media_type": "text/plain",
                        "size": 12,
                        "data_url": "data:text/plain;base64,Z2hp",
                        "text": "plain notes",
                    },
                ]
            },
        }
    )

    parts = message.metadata["provider_content_parts"]
    assert any(part.get("type") == "image_url" for part in parts)
    assert any(
        part.get("type") == "file" and part.get("file", {}).get("filename") == "brief.pdf"
        for part in parts
    )
    assert any(
        part.get("type") == "text" and "plain notes" in part.get("text", "")
        for part in parts
    )


def test_agent_timeout_uses_configured_floor(tmp_path: Path) -> None:
    engine, _ = _make_engine(tmp_path, [])
    agent = AgentDefinition(
        agent_id="short_timeout",
        name="Short Timeout",
        system_prompt="test",
        timeout_seconds=1,
    )

    assert engine._agent_timeout(agent) == engine.config.default_agent_timeout_seconds


def test_malformed_tool_arguments_return_failed_tool_result(tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, _ = _make_engine(tmp_path, [])
        run = WorkflowRun(
            session_id="ses_test",
            run_id="run_test",
            workflow=built_in_workflow("fireguard_intelligence"),
        )
        try:
            result = await engine._execute_agent_tool_calls(
                run,
                "research_agent",
                AgentDefinition(
                    agent_id="research_agent",
                    name="Research",
                    system_prompt="test",
                    model_tier=ModelTier.pro,
                    tool_names=[],
                ),
                [
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {
                            "name": "complete_workflow_node",
                            "arguments": "{\"payload\": \"unterminated",
                        },
                    }
                ],
                {},
            )
        finally:
            await engine.close()

        assert len(result) == 1
        assert result[0].ok is False
        assert result[0].output["error"] == "tool_call_arguments_json_decode_failed"

    asyncio.run(exercise())
