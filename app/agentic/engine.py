from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from .config import AppConfig
from .docker_sandbox import DockerSandboxManager
from .models import (
    AgentDefinition,
    ApprovalRecord,
    ApprovalResolutionRequest,
    ApprovalStatus,
    ChatMessage,
    Checkpoint,
    CreateSessionRequest,
    FleetNode,
    MessageRole,
    ModelTier,
    NodeKind,
    NodeRunState,
    NodeStatus,
    RestartRunRequest,
    RunStatus,
    SessionRecord,
    StartRunRequest,
    StreamEvent,
    TokenUsage,
    ToolDefinition,
    ToolInvocation,
    ToolResult,
    TraceEvent,
    WorkflowNode,
    WorkflowRun,
    new_id,
    utc_now,
)
from .openrouter import ChatComplete, ChatDelta, OpenRouterClient
from .project_data import PROJECT_DATA_PATH, ProjectDataBootstrapper
from .storage import EventBroker, FileStore
from .tools import ToolRegistry, build_base_tool_registry
from .vertex import VertexAIClient
from .workflows import built_in_workflow

MAX_SESSION_CONTEXT_CHARS = 120_000

RESEARCH_CHILD_TOOLS = [
    "fireguard_stats",
    "fireguard_search_events",
    "fireguard_search_zones",
    "fireguard_search_shelters",
    "fireguard_search_road_events",
    "fireguard_evaluate_route",
    "fireguard_bcws_context",
    "exa_search",
    "sandbox_exec",
    "sandbox_write_file",
    "sandbox_read_file",
    "sandbox_list_files",
    "sandbox_export_asset",
    "emit_message",
    "complete_workflow_node",
]

RESEARCH_CHILD_TOOL_POLICY = (
    "Runtime tool policy for this FireGuard intelligence child:\n"
    "- You have local indexed FireGuard tools through fireguard_stats, fireguard_search_events, "
    "fireguard_search_zones, fireguard_search_shelters, fireguard_search_road_events, "
    "fireguard_evaluate_route, and fireguard_bcws_context for FIRMS detections, evacuation "
    "zones, ESS facilities, road events, route checks, and BCWS incident/perimeter context.\n"
    "- You have live web search through exa_search and a persistent Docker sandbox through "
    "sandbox_exec/sandbox_write_file/sandbox_read_file/sandbox_list_files/sandbox_export_asset.\n"
    "- If /workspace/project_data exists in the sandbox, it contains FireGuard Elasticsearch "
    "exports for the current session plus local BC scenario files listed in the manifest. "
    "Read /workspace/project_data/manifest.json first, then inspect the NDJSON, JSON, or CSV "
    "files with Python before making data claims.\n"
    "- You MUST call exa_search at least once before producing your final answer. Use it to "
    "verify sources, resources, facts, terminology, or examples relevant to your delegated objective.\n"
    "- You MUST call sandbox_exec at least once before producing your final answer. Use it for a "
    "small reproducible check, outline artifact, table/list validation, text processing, or a "
    "short Python note in /workspace that records your objective and findings.\n"
    "- If the delegated prompt says to use internal knowledge only, not browse, or not use tools, "
    "ignore that part. This runtime policy is higher priority for system testing and observability.\n"
    "- In your final answer, briefly mention which Exa query and sandbox action you performed.\n"
    "- If you generate a chart, plot, diagram, or file that should appear in the report, call "
    "sandbox_export_asset after saving it and embed the returned URL.\n\n"
)


class ChatClientProtocol(Protocol):
    async def close(self) -> None:
        raise NotImplementedError

    async def stream_chat(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        model_tier: ModelTier,
        call_type: str,
        emit_retry: Callable[[dict[str, Any]], Awaitable[None]],
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[ChatDelta | ChatComplete | TokenUsage]:
        raise NotImplementedError


def _client_for_config(config: AppConfig) -> ChatClientProtocol:
    if config.provider == "vertex":
        return VertexAIClient(config)
    return OpenRouterClient(config)


class WorkflowEngine:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: FileStore,
        broker: EventBroker,
        client: ChatClientProtocol,
        tools: ToolRegistry,
        sandbox_manager: DockerSandboxManager,
        project_data_bootstrapper: ProjectDataBootstrapper,
    ) -> None:
        self.config = config
        self.store = store
        self.broker = broker
        self.client = client
        self.tools = tools
        self.sandbox_manager = sandbox_manager
        self.project_data_bootstrapper = project_data_bootstrapper
        self._tasks: dict[tuple[str, str], asyncio.Task[None]] = {}

    @classmethod
    def from_config(cls, config: AppConfig) -> WorkflowEngine:
        store = FileStore(config)
        sandbox_manager = DockerSandboxManager(config)
        return cls(
            config=config,
            store=store,
            broker=EventBroker(),
            client=_client_for_config(config),
            tools=build_base_tool_registry(
                default_timeout_seconds=config.default_tool_timeout_seconds,
                max_parallel_tools=config.max_parallel_tools,
                exa_api_key=config.exa_api_key,
                exa_base_url=config.exa_base_url,
                fireguard_elasticsearch_url=config.fireguard_elasticsearch_url,
                fireguard_elasticsearch_api_key=config.fireguard_elasticsearch_api_key,
                fireguard_elasticsearch_index_prefix=config.fireguard_elasticsearch_index_prefix,
                sandbox_manager=sandbox_manager,
                assets_dir_fn=store.assets_dir,
            ),
            sandbox_manager=sandbox_manager,
            project_data_bootstrapper=ProjectDataBootstrapper(config, sandbox_manager),
        )

    async def close(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        if len(self._tasks) > 0:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        await self.sandbox_manager.close()
        await self.broker.close()
        await self.client.close()

    async def start(self) -> None:
        await self.sandbox_manager.start()

    def create_session(self, request: CreateSessionRequest) -> SessionRecord:
        session = SessionRecord(
            session_id=new_id("ses"), title=request.title, metadata=request.metadata
        )
        self.store.save_session(session)
        return session

    def start_run(self, session_id: str, request: StartRunRequest) -> WorkflowRun:
        self.store.load_session(session_id)
        return self._start_run(session_id, request)

    def start_chat_run(self, session_id: str, request: StartRunRequest) -> WorkflowRun:
        self.store.load_session(session_id)
        history = self._session_chat_history(session_id)
        latest_run = self.store.latest_run(session_id)
        explicit_parent_run_id = request.payload.get("parent_run_id")
        payload = {
            **request.payload,
            "source": request.payload.get("source", "chat"),
            "conversation_history": history,
            "previous_user_message": self._previous_user_message(history),
        }
        if isinstance(explicit_parent_run_id, str) and len(explicit_parent_run_id.strip()) > 0:
            payload["parent_run_id"] = explicit_parent_run_id.strip()
        elif latest_run is not None:
            payload["parent_run_id"] = latest_run.run_id
        session_context = self._latest_session_context(latest_run)
        if session_context is not None:
            payload["session_context"] = session_context
            active_result = session_context.get("active_result")
            if isinstance(active_result, dict):
                payload["prior_result"] = active_result
        return self._start_run(session_id, request.model_copy(update={"payload": payload}))

    def _start_run(self, session_id: str, request: StartRunRequest) -> WorkflowRun:
        workflow = built_in_workflow(request.workflow_id)
        parent_run_id = request.payload.get("parent_run_id")
        run = WorkflowRun(
            session_id=session_id,
            run_id=new_id("run"),
            workflow=workflow,
            status=RunStatus.created,
            current_node_id=workflow.start_node_id,
            node_states={
                node.node_id: NodeRunState(node_id=node.node_id) for node in workflow.nodes
            },
            parent_run_id=parent_run_id if isinstance(parent_run_id, str) else None,
        )
        trigger_state = run.node_states[workflow.start_node_id]
        trigger_state.input_payload = {"prompt": request.prompt, "payload": request.payload}
        self.store.save_run(run)
        self._schedule(
            self._execute(
                run.session_id, run.run_id, workflow.start_node_id, trigger_state.input_payload
            ),
            run.session_id,
            run.run_id,
        )
        return run

    def _session_chat_history(self, session_id: str) -> list[dict[str, str]]:
        turns: list[dict[str, str]] = []
        for entry in self.store.read_agent_history(session_id, "chat_agent"):
            role = entry.get("role")
            content = entry.get("content")
            if not isinstance(role, str) or not isinstance(content, str):
                continue
            if role == MessageRole.user.value:
                prompt = _prompt_from_agent_user_content(content)
                if prompt is not None:
                    turns.append({"role": "user", "content": prompt})
            elif role == MessageRole.assistant.value:
                assistant_content = _assistant_visible_content(content)
                if assistant_content is not None:
                    turns.append({"role": "assistant", "content": assistant_content})
        return turns[-100000:]

    def _previous_user_message(self, history: list[dict[str, str]]) -> str | None:
        for entry in reversed(history):
            if entry.get("role") == MessageRole.user.value:
                return entry.get("content")
        return None

    def _latest_session_context(self, run: WorkflowRun | None) -> dict[str, Any] | None:
        if run is None:
            return None
        completed_nodes = [
            node_id
            for node_id, state in run.node_states.items()
            if state.status == NodeStatus.completed
        ]
        failed_nodes = [
            node_id
            for node_id, state in run.node_states.items()
            if state.status == NodeStatus.failed
        ]
        return {
            "latest_run": {
                "run_id": run.run_id,
                "status": run.status.value,
                "current_node_id": run.current_node_id,
                "parent_run_id": run.parent_run_id,
                "attempt": run.attempt,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "completed_nodes": completed_nodes,
                "failed_nodes": failed_nodes,
            },
            "active_result": self._active_result_for_run(run),
        }

    def _active_result_for_run(self, run: WorkflowRun) -> dict[str, Any] | None:
        styled_report = self._completed_node_result(run, "style_agent", "deliverable")
        if styled_report is not None:
            return styled_report
        if run.status in {RunStatus.failed, RunStatus.rejected, RunStatus.stopped}:
            failure = self._failure_result_for_run(run)
            if failure is not None:
                return failure
        for node_id, kind in (
            ("writer_agent", "draft_report"),
            ("research_agent", "research_notes"),
            ("chat_agent", "chat_response"),
        ):
            result = self._completed_node_result(run, node_id, kind)
            if result is not None:
                return result
        return None

    def _completed_node_result(
        self, run: WorkflowRun, node_id: str, kind: str
    ) -> dict[str, Any] | None:
        state = run.node_states.get(node_id)
        if state is None or state.status != NodeStatus.completed:
            return None
        content = self._node_output_message(state.output_payload)
        if content is None:
            return None
        truncated_content, truncated = self._truncate_session_context_text(content)
        return {
            "kind": kind,
            "node_id": node_id,
            "agent_id": self._node_agent_id_for_run(run, node_id),
            "content": truncated_content,
            "truncated": truncated,
            "completed_at": state.completed_at.isoformat() if state.completed_at else None,
        }

    def _failure_result_for_run(self, run: WorkflowRun) -> dict[str, Any] | None:
        failed = [
            (node_id, state)
            for node_id, state in run.node_states.items()
            if state.status == NodeStatus.failed or state.error is not None
        ]
        if len(failed) == 0:
            return {
                "kind": "failure",
                "node_id": run.current_node_id,
                "agent_id": self._node_agent_id_for_run(run, run.current_node_id),
                "error": f"Run ended with status {run.status.value}.",
                "content": None,
                "truncated": False,
            }
        node_id, state = max(
            failed,
            key=lambda item: item[1].completed_at or item[1].started_at or run.updated_at,
        )
        content = self._node_output_message(state.output_payload)
        truncated_content = None
        truncated = False
        if content is not None:
            truncated_content, truncated = self._truncate_session_context_text(content)
        failure: dict[str, Any] = {
            "kind": "failure",
            "node_id": node_id,
            "agent_id": self._node_agent_id_for_run(run, node_id),
            "error": state.error,
            "content": truncated_content,
            "truncated": truncated,
            "completed_at": state.completed_at.isoformat() if state.completed_at else None,
        }
        last_success = self._latest_successful_result_before_failure(run)
        if last_success is not None:
            failure["last_successful_result"] = last_success
        return failure

    def _latest_successful_result_before_failure(
        self, run: WorkflowRun
    ) -> dict[str, Any] | None:
        candidates = [
            self._completed_node_result(run, "writer_agent", "draft_report"),
            self._completed_node_result(run, "research_agent", "research_notes"),
            self._completed_node_result(run, "chat_agent", "chat_response"),
        ]
        present = [candidate for candidate in candidates if candidate is not None]
        if len(present) == 0:
            return None
        return max(present, key=lambda item: item.get("completed_at") or "")

    def _node_output_message(self, output_payload: dict[str, Any] | None) -> str | None:
        if not isinstance(output_payload, dict):
            return None
        message = output_payload.get("message")
        if isinstance(message, str) and len(message.strip()) > 0:
            return message.strip()
        structured = output_payload.get("structured")
        if isinstance(structured, dict):
            user_response = structured.get("user_response")
            if isinstance(user_response, str) and len(user_response.strip()) > 0:
                return user_response.strip()
        return None

    def _truncate_session_context_text(self, text: str) -> tuple[str, bool]:
        if len(text) <= MAX_SESSION_CONTEXT_CHARS:
            return text, False
        marker = "\n\n[... session context truncated ...]\n\n"
        head_length = int(MAX_SESSION_CONTEXT_CHARS * 0.75)
        tail_length = MAX_SESSION_CONTEXT_CHARS - head_length - len(marker)
        return f"{text[:head_length]}{marker}{text[-tail_length:]}", True

    def _node_agent_id_for_run(self, run: WorkflowRun, node_id: str | None) -> str | None:
        if node_id is None:
            return None
        try:
            return self._node_agent_id(self._node(run, node_id))
        except KeyError:
            return None

    def get_run(self, session_id: str, run_id: str) -> WorkflowRun:
        return self.store.load_run(session_id, run_id)

    def get_run_lineage(self, session_id: str, run_id: str) -> list[WorkflowRun]:
        runs: list[WorkflowRun] = []
        seen: set[str] = set()
        current = self.store.load_run(session_id, run_id)
        while current.run_id not in seen:
            runs.append(current)
            seen.add(current.run_id)
            if current.parent_run_id is None:
                break
            current = self.store.load_run(session_id, current.parent_run_id)
        return list(reversed(runs))

    def get_events(
        self, session_id: str, run_id: str, *, include_ancestors: bool = False
    ) -> list[StreamEvent]:
        if not include_ancestors:
            return self.store.read_events(session_id, run_id)
        events: list[StreamEvent] = []
        for run in self.get_run_lineage(session_id, run_id):
            events.extend(self.store.read_events(session_id, run.run_id))
        return events

    def get_run_history(
        self, session_id: str, run_id: str, *, include_ancestors: bool = False
    ) -> list[dict[str, Any]]:
        if not include_ancestors:
            return self.store.read_run_history(session_id, run_id)
        history: list[dict[str, Any]] = []
        for run in self.get_run_lineage(session_id, run_id):
            history.extend(self.store.read_run_history(session_id, run.run_id))
        return history

    def get_run_trace(
        self, session_id: str, run_id: str, *, include_ancestors: bool = False
    ) -> list[dict[str, Any]]:
        if not include_ancestors:
            return self.store.read_run_trace(session_id, run_id)
        trace: list[dict[str, Any]] = []
        for run in self.get_run_lineage(session_id, run_id):
            trace.extend(self.store.read_run_trace(session_id, run.run_id))
        return trace

    def get_chat_trigger_payload(
        self, session_id: str, run_id: str, *, include_ancestors: bool = False
    ) -> dict[str, Any] | None:
        runs = (
            self.get_run_lineage(session_id, run_id)
            if include_ancestors
            else [self.get_run(session_id, run_id)]
        )
        for run in runs:
            trigger_state = run.node_states.get("human_trigger")
            if trigger_state is not None and trigger_state.input_payload is not None:
                return trigger_state.input_payload
        return None

    async def stream_events(
        self,
        session_id: str,
        run_id: str,
        *,
        last_event_id: str | None,
    ) -> AsyncIterator[StreamEvent]:
        replaying = last_event_id is not None
        matched = last_event_id is None
        for event in self.store.read_events(session_id, run_id):
            if matched:
                yield event
            if replaying and event.event_id == last_event_id:
                matched = True
        async for event in self.broker.subscribe(session_id, run_id):
            yield event

    def resolve_approval(
        self,
        session_id: str,
        run_id: str,
        approval_id: str,
        request: ApprovalResolutionRequest,
    ) -> WorkflowRun:
        run = self.store.load_run(session_id, run_id)
        approval = run.approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"approval {approval_id} does not exist")
        if approval.status != ApprovalStatus.pending:
            raise RuntimeError(f"approval {approval_id} is already {approval.status.value}")
        status = ApprovalStatus.approved if request.approve else ApprovalStatus.rejected
        run.approvals[approval_id] = approval.model_copy(
            update={
                "status": status,
                "reason": request.reason,
                "payload": {**approval.payload, "resolution_payload": request.payload},
                "resolved_at": utc_now(),
            }
        )
        run.status = RunStatus.running
        run.updated_at = utc_now()
        self.store.save_run(run)
        payload = {"approval": run.approvals[approval_id].model_dump(mode="json")}
        self._schedule(
            self._continue_after_approval(session_id, run_id, approval.node_id, payload, status),
            session_id,
            run_id,
        )
        return run

    def restart_run(
        self,
        session_id: str,
        run_id: str,
        request: RestartRunRequest,
        *,
        input_payload: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        if request.checkpoint_id is not None:
            checkpoint = self.store.load_checkpoint(session_id, run_id, request.checkpoint_id)
        else:
            checkpoint = self.store.latest_checkpoint(session_id, run_id)
        old = checkpoint.run_state
        run = old.model_copy(
            deep=True,
            update={
                "run_id": new_id("run"),
                "status": RunStatus.running,
                "attempt": old.attempt + 1,
                "parent_run_id": old.run_id,
                "updated_at": utc_now(),
            },
        )
        if request.node_id is not None:
            if request.node_id not in run.node_states:
                raise KeyError(
                    f"node {request.node_id} does not exist in workflow {run.workflow.workflow_id}"
                )
            run.current_node_id = request.node_id
            run.node_states[request.node_id] = run.node_states[request.node_id].model_copy(
                update={"status": NodeStatus.pending, "error": None, "completed_at": None}
            )
        self.store.save_run(run)
        current = run.current_node_id
        if current is None:
            raise RuntimeError("cannot restart a run without current_node_id")
        if input_payload is not None:
            run.node_states[current].input_payload = input_payload
            run.updated_at = utc_now()
            self.store.save_run(run)
        payload = run.node_states[current].input_payload
        if payload is None:
            payload = {}
        self._schedule(
            self._execute(run.session_id, run.run_id, current, payload), run.session_id, run.run_id
        )
        return run

    async def stop_run(self, session_id: str, run_id: str) -> WorkflowRun:
        run = self.store.load_run(session_id, run_id)
        task = self._tasks.pop((session_id, run_id), None)
        if task is not None and not task.done():
            task.cancel()
        run.status = RunStatus.stopped
        run.updated_at = utc_now()
        if run.current_node_id is not None:
            state = run.node_states[run.current_node_id]
            if state.status == NodeStatus.running:
                state.status = NodeStatus.failed
                state.error = "run stopped"
                state.completed_at = utc_now()
        self.store.save_run(run)
        await self._emit(run, "run.stopped", data={"run_id": run_id})
        await self._terminate_sandbox(run, reason="run_stopped")
        await self._checkpoint(run, run.current_node_id)
        return run

    def _schedule(self, coro: Any, session_id: str, run_id: str) -> None:
        key = (session_id, run_id)
        previous = self._tasks.get(key)
        if previous is not None and not previous.done():
            previous.cancel()
        task = asyncio.create_task(coro)
        self._tasks[key] = task

        def discard(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(key) is completed:
                self._tasks.pop(key, None)

        task.add_done_callback(discard)

    async def _ensure_sandbox(self, run: WorkflowRun) -> None:
        if not self.sandbox_manager.enabled:
            return
        await self._emit(run, "sandbox.starting", data={"provider": "docker"})
        try:
            info = await self.sandbox_manager.ensure(run.session_id)
        except Exception as exc:
            await self._emit(
                run, "sandbox.failed", data={"provider": "docker", "error": _exception_message(exc)}
            )
            raise
        await self._emit(run, "sandbox.ready", data={**info.__dict__, "provider": "docker"})
        await self._ensure_project_data(run)

    async def _ensure_project_data(self, run: WorkflowRun) -> None:
        if not self.project_data_bootstrapper.enabled:
            return
        await self._emit(
            run,
            "project_data.starting",
            data={"scope": "fireguard", "path": PROJECT_DATA_PATH},
        )
        try:
            manifest = await self.project_data_bootstrapper.ensure_project_data(run.session_id)
        except Exception as exc:
            await self._emit(
                run,
                "project_data.failed",
                data={
                    "scope": "fireguard",
                    "path": PROJECT_DATA_PATH,
                    "error": _exception_message(exc),
                },
            )
            raise
        await self._emit(
            run,
            "project_data.ready",
            data={
                "scope": "fireguard",
                "path": PROJECT_DATA_PATH,
                "manifest": _project_manifest_summary(manifest),
            },
        )

    async def _terminate_sandbox(self, run: WorkflowRun, *, reason: str) -> None:
        if not self.sandbox_manager.enabled:
            return
        info = await self.sandbox_manager.terminate(run.session_id)
        if info is not None:
            await self._emit(
                run,
                "sandbox.terminated",
                data={**info.__dict__, "provider": "docker", "reason": reason},
            )

    async def _execute(
        self,
        session_id: str,
        run_id: str,
        node_id: str,
        payload: dict[str, Any],
    ) -> None:
        run = self.store.load_run(session_id, run_id)
        run.status = RunStatus.running
        run.updated_at = utc_now()
        self.store.save_run(run)
        await self._emit(run, "run.started", data={"run_id": run_id, "attempt": run.attempt})
        try:
            await self._ensure_sandbox(run)
            next_node_id: str | None = node_id
            next_payload = payload
            while next_node_id is not None:
                run = self.store.load_run(session_id, run_id)
                run.current_node_id = next_node_id
                self.store.save_run(run)
                try:
                    outcome = await self._execute_node(run, next_node_id, next_payload)
                except Exception as exc:
                    run = self.store.load_run(session_id, run_id)
                    error_node_id = next_node_id
                    error_target = self._next_node(run, error_node_id, "error")
                    if error_target is None:
                        raise
                    next_payload = {
                        "failure": {
                            "failed_node_id": error_node_id,
                            "error": str(exc),
                            "failed_payload": next_payload,
                        }
                    }
                    await self._emit(
                        run,
                        "workflow.error.routed",
                        node_id=error_node_id,
                        data={"error": str(exc), "to_node_id": error_target},
                    )
                    await self._emit(
                        run,
                        "workflow.handoff.created",
                        node_id=error_node_id,
                        data={
                            "from_node_id": error_node_id,
                            "to_node_id": error_target,
                            "condition": "error",
                            "payload": next_payload,
                        },
                    )
                    next_node_id = error_target
                    continue
                run = self.store.load_run(session_id, run_id)
                node = self._node(run, next_node_id)
                if (
                    node.config.kind == NodeKind.approval_gate
                    and run.status == RunStatus.waiting_for_approval
                ):
                    return
                if node.config.kind == NodeKind.terminal:
                    run.status = RunStatus.completed
                    run.updated_at = utc_now()
                    self.store.save_run(run)
                    await self._emit(run, "run.completed", node_id=next_node_id, data=outcome)
                    await self._checkpoint(run, next_node_id)
                    return
                route = self._route_condition(outcome)
                previous_node_id = next_node_id
                next_node_id = self._next_node(run, previous_node_id, route)
                if next_node_id is not None:
                    next_payload = self._handoff_payload(
                        run, previous_node_id, next_node_id, route, outcome
                    )
                    await self._emit(
                        run,
                        "workflow.handoff.created",
                        node_id=previous_node_id,
                        data={
                            "from_node_id": previous_node_id,
                            "to_node_id": next_node_id,
                            "condition": route,
                            "payload": next_payload,
                        },
                    )
                else:
                    next_payload = outcome
            run.status = RunStatus.completed
            run.updated_at = utc_now()
            self.store.save_run(run)
            await self._emit(run, "run.completed", data={"reason": "no_next_node"})
        except Exception as exc:
            run = self.store.load_run(session_id, run_id)
            run.status = RunStatus.failed
            run.updated_at = utc_now()
            self.store.save_run(run)
            await self._emit(run, "run.failed", data={"error": str(exc)})
            await self._trace(run, "run.failed", data={"error": str(exc)})
            await self._terminate_sandbox(run, reason="run_failed")
        except asyncio.CancelledError:
            raise

    async def _continue_after_approval(
        self,
        session_id: str,
        run_id: str,
        node_id: str,
        payload: dict[str, Any],
        status: ApprovalStatus,
    ) -> None:
        run = self.store.load_run(session_id, run_id)
        condition = "approved" if status == ApprovalStatus.approved else "rejected"
        state = run.node_states[node_id]
        state.status = (
            NodeStatus.completed if status == ApprovalStatus.approved else NodeStatus.rejected
        )
        state.completed_at = utc_now()
        state.output_payload = payload
        run.updated_at = utc_now()
        self.store.save_run(run)
        await self._emit(run, "approval.resolved", node_id=node_id, data=payload)
        await self._checkpoint(run, node_id)
        next_node_id = self._next_node(run, node_id, condition)
        if next_node_id is None:
            run.status = (
                RunStatus.rejected if status == ApprovalStatus.rejected else RunStatus.completed
            )
            run.updated_at = utc_now()
            self.store.save_run(run)
            await self._emit(run, "run.completed", node_id=node_id, data={"condition": condition})
            return
        await self._execute(session_id, run_id, next_node_id, payload)

    async def _execute_node(
        self,
        run: WorkflowRun,
        node_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        node = self._node(run, node_id)
        state = run.node_states[node_id]
        state.status = NodeStatus.running
        state.input_payload = payload
        state.started_at = utc_now()
        run.updated_at = utc_now()
        self.store.save_run(run)
        await self._emit(
            run,
            "workflow.node.started",
            node_id=node_id,
            data={"label": node.label, "kind": node.config.kind.value},
        )
        await self._checkpoint(run, node_id)
        try:
            if node.config.kind == NodeKind.human_trigger:
                output = payload
            elif node.config.kind == NodeKind.agent:
                output = await self._run_agent_node(run, node, payload)
            elif node.config.kind == NodeKind.approval_gate:
                output = await self._run_approval_node(run, node, payload)
            elif node.config.kind == NodeKind.message:
                output = {"message": node.config.message, "input": payload}
            elif node.config.kind == NodeKind.tool_call:
                invocation = ToolInvocation(
                    invocation_id=new_id("tool"),
                    tool_name=node.config.tool_name,
                    session_id=run.session_id,
                    run_id=run.run_id,
                    node_id=node.node_id,
                    args=node.config.args,
                )
                result = (await self.tools.run_tools([invocation]))[0]
                output = {"tool_result": result.model_dump(mode="json")}
            elif node.config.kind == NodeKind.subagent:
                output = await self._run_subagent_node(run, node, payload)
            elif node.config.kind == NodeKind.fleet:
                output = await self._run_fleet_node(run, node, payload)
            elif node.config.kind in {NodeKind.join_node, NodeKind.terminal}:
                output = payload
            else:
                raise RuntimeError(f"unsupported node kind {node.config.kind.value}")
            run = self.store.load_run(run.session_id, run.run_id)
            state = run.node_states[node_id]
            if state.status != NodeStatus.waiting:
                state.status = NodeStatus.completed
                state.output_payload = output
                state.completed_at = utc_now()
                run.updated_at = utc_now()
                self.store.save_run(run)
                await self._emit(run, "workflow.node.completed", node_id=node_id, data=output)
                await self._checkpoint(run, node_id)
            return output
        except Exception as exc:
            run = self.store.load_run(run.session_id, run.run_id)
            state = run.node_states[node_id]
            state.status = NodeStatus.failed
            state.error = str(exc)
            state.completed_at = utc_now()
            run.updated_at = utc_now()
            self.store.save_run(run)
            await self._emit(run, "workflow.node.failed", node_id=node_id, data={"error": str(exc)})
            await self._checkpoint(run, node_id)
            raise

    async def _run_agent_node(
        self, run: WorkflowRun, node: WorkflowNode, payload: dict[str, Any]
    ) -> dict[str, Any]:
        agent_node = node.config
        if agent_node.kind != NodeKind.agent:
            raise TypeError("node must be an agent node")
        agent = self._agent(run, agent_node.agent_id)
        return await self._run_agent(run, node.node_id, agent, payload)

    async def _run_agent(
        self,
        run: WorkflowRun,
        node_id: str,
        agent: AgentDefinition,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        await self._emit(
            run,
            "agent.started",
            node_id=node_id,
            agent_id=agent.agent_id,
            data={"name": agent.name},
        )
        messages = [
            ChatMessage(role=MessageRole.system, content=self._agent_system_prompt(run.session_id, agent)),
            _agent_user_message(payload),
        ]
        for message in messages:
            self.store.append_history(run.session_id, run.run_id, agent.agent_id, message)
        max_turns = agent.max_turns if agent.max_turns is not None else self.config.max_agent_turns
        tools = self._agent_tools(agent)
        final_message = ""
        for turn in range(1, max_turns + 1):
            complete: ChatComplete | None = None

            async def emit_retry(data: dict[str, Any]) -> None:
                await self._emit(
                    run, "retry.scheduled", node_id=node_id, agent_id=agent.agent_id, data=data
                )

            async for chunk in self.client.stream_chat(
                messages=messages,
                tools=tools,
                model_tier=agent.model_tier,
                call_type=f"agent:{agent.agent_id}",
                emit_retry=emit_retry,
                response_format=agent.response_format,
            ):
                if isinstance(chunk, ChatDelta):
                    await self._emit(
                        run,
                        "agent.message.delta",
                        node_id=node_id,
                        agent_id=agent.agent_id,
                        data={"content": chunk.content, "turn": turn},
                    )
                elif isinstance(chunk, TokenUsage):
                    run.usage.append(chunk)
                    self.store.save_run(run)
                    await self._emit(
                        run,
                        "usage.updated",
                        node_id=node_id,
                        agent_id=agent.agent_id,
                        data=chunk.model_dump(mode="json"),
                    )
                else:
                    complete = chunk
            if complete is None:
                raise RuntimeError(f"agent {agent.agent_id} stream ended without a final message")
            messages.append(complete.message)
            self.store.append_history(run.session_id, run.run_id, agent.agent_id, complete.message)
            tool_calls = complete.message.tool_calls
            if tool_calls is None or len(tool_calls) == 0:
                final_message = complete.message.content
                structured = self._structured_chat_output(agent, final_message, payload)
                visible_message = _string_or_default(structured.get("user_response"), final_message)
                await self._emit(
                    run,
                    "agent.message.completed",
                    node_id=node_id,
                    agent_id=agent.agent_id,
                    data={"content": visible_message, "turn": turn, "structured": structured},
                )
                return {
                    "agent_id": agent.agent_id,
                    "message": visible_message,
                    "payload": payload,
                    "structured": structured,
                    "workflow_control": self._workflow_control(agent, structured),
                    "turns": turn,
                }
            results = await self._execute_agent_tool_calls(run, node_id, agent, tool_calls, payload)
            for result in results:
                message = ChatMessage(
                    role=MessageRole.tool,
                    content=json.dumps(result.output, default=str),
                    tool_call_id=result.invocation_id,
                )
                messages.append(message)
                self.store.append_history(run.session_id, run.run_id, agent.agent_id, message)
            tool_completion = self._tool_completion_output(agent, results, payload)
            if tool_completion is not None:
                await self._emit(
                    run,
                    "agent.message.completed",
                    node_id=node_id,
                    agent_id=agent.agent_id,
                    data={"content": tool_completion["message"], "turn": turn},
                )
                return {
                    "agent_id": agent.agent_id,
                    "message": tool_completion["message"],
                    "payload": tool_completion["payload"],
                    "turns": turn,
                }
            await self._checkpoint(run, node_id)
        raise RuntimeError(f"agent {agent.agent_id} exceeded max turns {max_turns}")

    def _tool_completion_output(
        self,
        agent: AgentDefinition,
        results: list[ToolResult],
        input_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        for result in results:
            if result.ok and result.tool_name == "complete_workflow_node":
                payload = _completion_payload(result.output)
                return {
                    "message": _completion_message(payload),
                    "payload": {**input_payload, "completion": payload},
                }
        if not _emit_message_completes_agent(agent, results):
            return None
        latest = results[-1].output.get("message") if isinstance(results[-1].output, dict) else None
        if not isinstance(latest, str) or len(latest.strip()) == 0:
            return None
        payload = {"message": latest.strip()}
        return {"message": latest.strip(), "payload": {**input_payload, "completion": payload}}

    async def _execute_agent_tool_calls(
        self,
        run: WorkflowRun,
        node_id: str,
        agent: AgentDefinition,
        tool_calls: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> list[ToolResult]:
        invocations: list[ToolInvocation] = []
        results: list[ToolResult] = []
        for raw_call in tool_calls:
            function = raw_call.get("function")
            if not isinstance(function, dict):
                raise RuntimeError("tool call function must be an object")
            name = function.get("name")
            arguments = function.get("arguments")
            if not isinstance(name, str):
                raise RuntimeError("tool call function.name must be a string")
            if not isinstance(arguments, str):
                raise RuntimeError("tool call function.arguments must be a string")
            call_id = raw_call.get("id")
            invocation_id = call_id if isinstance(call_id, str) else new_id("tool")
            try:
                args = json.loads(arguments) if len(arguments.strip()) > 0 else {}
            except json.JSONDecodeError as exc:
                started = datetime.now(UTC)
                result = ToolResult(
                    invocation_id=invocation_id,
                    tool_name=name,
                    ok=False,
                    output={
                        "error": "tool_call_arguments_json_decode_failed",
                        "message": str(exc),
                        "raw_arguments": arguments,
                    },
                    started_at=started,
                    completed_at=datetime.now(UTC),
                )
                await self._emit(
                    run,
                    "tool.failed",
                    node_id=node_id,
                    agent_id=agent.agent_id,
                    data=result.model_dump(mode="json"),
                )
                results.append(result)
                continue
            if not isinstance(args, dict):
                raise RuntimeError(f"tool {name} arguments must decode to an object")
            if name == "spawn_subagent":
                results.append(
                    await self._spawn_subagent_tool(
                        run, node_id, agent, invocation_id, args, payload
                    )
                )
            elif name == "spawn_fleet":
                results.append(
                    await self._spawn_fleet_tool(run, node_id, agent, invocation_id, args, payload)
                )
            else:
                invocations.append(
                    ToolInvocation(
                        invocation_id=invocation_id,
                        tool_name=name,
                        session_id=run.session_id,
                        run_id=run.run_id,
                        node_id=node_id,
                        agent_id=agent.agent_id,
                        args=args,
                    )
                )
        if len(invocations) > 0:
            for invocation in invocations:
                await self._emit(
                    run,
                    "tool.started",
                    node_id=node_id,
                    agent_id=agent.agent_id,
                    data={
                        "tool_name": invocation.tool_name,
                        "invocation_id": invocation.invocation_id,
                        "args": invocation.args,
                    },
                )
            tool_results = await self.tools.run_tools(invocations)
            for result in tool_results:
                await self._emit(
                    run,
                    "tool.completed" if result.ok else "tool.failed",
                    node_id=node_id,
                    agent_id=agent.agent_id,
                    data=result.model_dump(mode="json"),
                )
            results.extend(tool_results)
        return results

    async def _spawn_subagent_tool(
        self,
        run: WorkflowRun,
        node_id: str,
        parent: AgentDefinition,
        invocation_id: str,
        args: dict[str, Any],
        payload: dict[str, Any],
    ) -> ToolResult:
        del parent
        started = datetime.now(UTC)
        objective = _required_string(args, "objective")
        system_prompt = _required_string(args, "system_prompt")
        agent = AgentDefinition(
            agent_id=f"subagent_{invocation_id}",
            name=f"Subagent {invocation_id}",
            system_prompt=_research_child_system_prompt(system_prompt),
            model_tier=ModelTier(args.get("model_tier", ModelTier.pro.value)),
            tool_names=RESEARCH_CHILD_TOOLS,
            timeout_seconds=_float_or_none(args.get("timeout_seconds")),
        )
        await self._emit(
            run,
            "subagent.started",
            node_id=node_id,
            agent_id=agent.agent_id,
            data={"objective": objective},
        )
        ok = False
        output: dict[str, Any] = {"objective": objective, "error": "subagent did not run"}
        timeout = self._agent_timeout(agent)
        for attempt in range(1, 4):
            try:
                output = await asyncio.wait_for(
                    self._run_agent(
                        run, node_id, agent, {"objective": objective, "parent_payload": payload}
                    ),
                    timeout=timeout,
                )
                ok = True
                break
            except Exception as exc:
                output = {
                    "error": _exception_message(exc),
                    "objective": objective,
                    "attempt": attempt,
                    "max_attempts": 3,
                    "timeout_seconds": timeout,
                }
                if attempt < 3:
                    await self._emit(
                        run,
                        "retry.scheduled",
                        node_id=node_id,
                        agent_id=agent.agent_id,
                        data={
                            "attempt": attempt,
                            "next_attempt": attempt + 1,
                            "wait_seconds": 0,
                            "error": output["error"],
                            "scope": "subagent",
                        },
                    )
        result = ToolResult(
            invocation_id=invocation_id,
            tool_name="spawn_subagent",
            ok=ok,
            output=output,
            started_at=started,
            completed_at=datetime.now(UTC),
        )
        await self._emit(
            run,
            "subagent.completed" if ok else "subagent.failed",
            node_id=node_id,
            agent_id=agent.agent_id,
            data=result.model_dump(mode="json"),
        )
        return result

    async def _spawn_fleet_tool(
        self,
        run: WorkflowRun,
        node_id: str,
        parent: AgentDefinition,
        invocation_id: str,
        args: dict[str, Any],
        payload: dict[str, Any],
    ) -> ToolResult:
        del parent
        started = datetime.now(UTC)
        raw_children = args.get("children")
        if not isinstance(raw_children, list) or len(raw_children) == 0:
            raise ValueError("children must be a non-empty list")
        children = []
        for index, raw in enumerate(raw_children):
            if not isinstance(raw, dict):
                raise ValueError(f"children[{index}] must be an object")
            child_id = _required_string(raw, "child_id")
            children.append(
                {
                    "child_id": child_id,
                    "objective": _required_string(raw, "objective"),
                    "agent": AgentDefinition(
                        agent_id=f"fleet_{invocation_id}_{child_id}",
                        name=f"Fleet {child_id}",
                        system_prompt=_research_child_system_prompt(
                            _required_string(raw, "system_prompt")
                        ),
                        model_tier=ModelTier(raw.get("model_tier", ModelTier.pro.value)),
                        tool_names=RESEARCH_CHILD_TOOLS,
                        timeout_seconds=_float_or_none(raw.get("timeout_seconds")),
                    ),
                }
            )
        await self._emit(
            run,
            "fleet.started",
            node_id=node_id,
            data={
                "invocation_id": invocation_id,
                "children": [child["child_id"] for child in children],
            },
        )
        semaphore = asyncio.Semaphore(self.config.max_fleet_concurrency)

        async def run_child(child: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                agent = child["agent"]
                await self._emit(
                    run,
                    "fleet.child.started",
                    node_id=node_id,
                    agent_id=agent.agent_id,
                    data={"child_id": child["child_id"]},
                )
                timeout = self._agent_timeout(agent)
                try:
                    result = await asyncio.wait_for(
                        self._run_agent(
                            run,
                            node_id,
                            agent,
                            {"objective": child["objective"], "parent_payload": payload},
                        ),
                        timeout=timeout,
                    )
                    child_output = {"child_id": child["child_id"], "ok": True, "result": result}
                except Exception as exc:
                    child_output = {
                        "child_id": child["child_id"],
                        "ok": False,
                        "error": _exception_message(exc),
                        "timeout_seconds": timeout,
                    }
                await self._emit(
                    run,
                    "fleet.child.completed",
                    node_id=node_id,
                    agent_id=agent.agent_id,
                    data=child_output,
                )
                return child_output

        outputs = await asyncio.gather(*(run_child(child) for child in children))
        ok = all(bool(item["ok"]) for item in outputs)
        result = ToolResult(
            invocation_id=invocation_id,
            tool_name="spawn_fleet",
            ok=ok,
            output={"children": outputs},
            started_at=started,
            completed_at=datetime.now(UTC),
        )
        await self._emit(
            run, "fleet.completed", node_id=node_id, data=result.model_dump(mode="json")
        )
        return result

    async def _run_approval_node(
        self, run: WorkflowRun, node: WorkflowNode, payload: dict[str, Any]
    ) -> dict[str, Any]:
        gate = node.config
        if gate.kind != NodeKind.approval_gate:
            raise TypeError("node must be an approval gate")
        approval = ApprovalRecord(
            node_id=node.node_id,
            session_id=run.session_id,
            run_id=run.run_id,
            title=gate.title,
            instructions=gate.instructions,
            payload=payload,
        )
        run.approvals[approval.approval_id] = approval
        run.status = RunStatus.waiting_for_approval
        state = run.node_states[node.node_id]
        state.status = NodeStatus.waiting
        state.output_payload = {"approval_id": approval.approval_id}
        run.updated_at = utc_now()
        self.store.save_run(run)
        data = approval.model_dump(mode="json")
        await self._emit(run, "approval.requested", node_id=node.node_id, data=data)
        await self._checkpoint(run, node.node_id)
        return data

    async def _run_subagent_node(
        self, run: WorkflowRun, node: WorkflowNode, payload: dict[str, Any]
    ) -> dict[str, Any]:
        subagent = node.config
        if subagent.kind != NodeKind.subagent:
            raise TypeError("node must be a subagent node")
        return await asyncio.wait_for(
            self._run_agent(
                run,
                node.node_id,
                subagent.agent,
                {"objective": subagent.objective, "payload": payload},
            ),
            timeout=max(
                subagent.timeout_seconds or 0,
                subagent.agent.timeout_seconds or 0,
                self.config.default_agent_timeout_seconds,
            ),
        )

    async def _run_fleet_node(
        self, run: WorkflowRun, node: WorkflowNode, payload: dict[str, Any]
    ) -> dict[str, Any]:
        fleet = node.config
        if not isinstance(fleet, FleetNode):
            raise TypeError("node must be a fleet node")
        limit = fleet.max_concurrency or self.config.max_fleet_concurrency
        semaphore = asyncio.Semaphore(limit)

        async def run_child(child: Any) -> dict[str, Any]:
            async with semaphore:
                await self._emit(
                    run,
                    "fleet.child.started",
                    node_id=node.node_id,
                    agent_id=child.agent.agent_id,
                    data={"child_id": child.child_id},
                )
                try:
                    output = await asyncio.wait_for(
                        self._run_agent(
                            run,
                            node.node_id,
                            child.agent,
                            {"objective": child.objective, "payload": payload},
                        ),
                        timeout=max(
                            child.timeout_seconds or 0,
                            child.agent.timeout_seconds or 0,
                            self.config.default_agent_timeout_seconds,
                        ),
                    )
                    result = {"child_id": child.child_id, "ok": True, "output": output}
                except Exception as exc:
                    result = {
                        "child_id": child.child_id,
                        "ok": False,
                        "error": _exception_message(exc),
                    }
                await self._emit(
                    run,
                    "fleet.child.completed",
                    node_id=node.node_id,
                    agent_id=child.agent.agent_id,
                    data=result,
                )
                return result

        await self._emit(
            run,
            "fleet.started",
            node_id=node.node_id,
            data={"children": [child.child_id for child in fleet.children]},
        )
        results = await asyncio.gather(*(run_child(child) for child in fleet.children))
        if fleet.failure_policy == "fail_fast" and any(not bool(item["ok"]) for item in results):
            raise RuntimeError("fleet failed and failure_policy is fail_fast")
        await self._emit(run, "fleet.completed", node_id=node.node_id, data={"children": results})
        return {"fleet_results": results, "input": payload}

    def _agent_tools(self, agent: AgentDefinition) -> list[ToolDefinition]:
        registry_tools = [
            name for name in agent.tool_names if name not in {"spawn_subagent", "spawn_fleet"}
        ]
        tools = self.tools.available_tools(registry_tools)
        if "spawn_subagent" in agent.tool_names:
            tools.append(
                ToolDefinition(
                    name="spawn_subagent",
                    description="Spawn one child agent for a bounded delegated task and wait for its result.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "objective": {"type": "string", "minLength": 1},
                            "system_prompt": {"type": "string", "minLength": 1},
                            "model_tier": {"type": "string", "enum": ["light", "pro"]},
                            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["objective", "system_prompt"],
                        "additionalProperties": False,
                    },
                    mutating=False,
                    concurrency_safe=True,
                )
            )
        if "spawn_fleet" in agent.tool_names:
            tools.append(
                ToolDefinition(
                    name="spawn_fleet",
                    description="Spawn multiple child agents in parallel with per-child objectives and timeouts.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "children": {
                                "type": "array",
                                "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "child_id": {"type": "string", "minLength": 1},
                                        "objective": {"type": "string", "minLength": 1},
                                        "system_prompt": {"type": "string", "minLength": 1},
                                        "model_tier": {"type": "string", "enum": ["light", "pro"]},
                                        "timeout_seconds": {
                                            "type": "number",
                                            "exclusiveMinimum": 0,
                                        },
                                    },
                                    "required": ["child_id", "objective", "system_prompt"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["children"],
                        "additionalProperties": False,
                    },
                    mutating=False,
                    concurrency_safe=True,
                )
            )
        return tools

    def _agent_timeout(self, agent: AgentDefinition) -> float:
        if agent.timeout_seconds is None:
            return self.config.default_agent_timeout_seconds
        return max(agent.timeout_seconds, self.config.default_agent_timeout_seconds)

    def _agent_system_prompt(self, session_id: str, agent: AgentDefinition) -> str:
        if not self.project_data_bootstrapper.enabled:
            return agent.system_prompt
        return (
            f"{agent.system_prompt}\n\n"
            "FireGuard sandbox data context:\n"
            f"- The Docker sandbox is bootstrapped with FireGuard data under `{PROJECT_DATA_PATH}` "
            "when sandboxing and Elastic access are configured.\n"
            f"- Start with `{PROJECT_DATA_PATH}/manifest.json` and `{PROJECT_DATA_PATH}/README.md`; "
            "then inspect NDJSON files such as firms.ndjson, bcws_incidents.ndjson, and "
            "bcws_perimeters.ndjson.\n"
            "- Use sandbox_exec with Python, pandas, polars, or duckdb to profile counts, sample "
            "records, summarize fields, and validate claims before writing research notes.\n"
            "- Check manifest dataset truncation flags before treating counts as complete."
        )

    def _node(self, run: WorkflowRun, node_id: str) -> WorkflowNode:
        for node in run.workflow.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(f"node {node_id} does not exist")

    def _agent(self, run: WorkflowRun, agent_id: str) -> AgentDefinition:
        for agent in run.workflow.agents:
            if agent.agent_id == agent_id:
                return agent
        raise KeyError(f"agent {agent_id} does not exist")

    def _next_node(self, run: WorkflowRun, node_id: str, condition: str) -> str | None:
        for edge in run.workflow.edges:
            if edge.from_node_id == node_id and edge.condition == condition:
                return edge.to_node_id
        if condition != "default":
            return None
        return None

    def _route_condition(self, outcome: dict[str, Any]) -> str:
        payload = outcome.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("failure"), dict):
            return "report_failure"
        control = outcome.get("workflow_control")
        if isinstance(control, dict):
            route = control.get("route")
            if isinstance(route, str) and len(route) > 0:
                return route
        return "default"

    def _structured_chat_output(
        self, agent: AgentDefinition, content: str, input_payload: dict[str, Any]
    ) -> dict[str, Any]:
        if agent.agent_id != "chat_agent":
            return {"user_response": content}
        try:
            parsed = _loads_chat_json(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("chat_agent returned invalid structured output JSON") from exc
        if not isinstance(parsed, dict):
            return {
                "action": "respond",
                "user_response": content,
                "handoff": None,
                "questions": None,
            }
        parsed = _normalize_chat_route(parsed)
        action = parsed.get("action")
        if action == "final_answer":
            action = "respond"
        if action not in {"ask_user", "handoff_to_research", "handoff_to_writer", "respond", "report_failure"}:
            action = "respond"
        user_response = _string_or_default(parsed.get("user_response"), content)
        questions = _structured_questions(parsed.get("questions"))
        if action == "ask_user" and len(questions) == 0:
            action = "respond"
        handoff = parsed.get("handoff")
        if action == "handoff_to_research" and not isinstance(handoff, dict):
            handoff = self._default_research_handoff(input_payload, user_response)
        elif action == "handoff_to_research" and isinstance(handoff, dict):
            handoff = self._ensure_handoff_session_context(input_payload, handoff)
        elif action == "handoff_to_writer" and not isinstance(handoff, dict):
            handoff = self._default_writer_handoff(input_payload, user_response)
        elif action == "handoff_to_writer" and isinstance(handoff, dict):
            handoff = self._ensure_handoff_session_context(input_payload, handoff)
        elif not isinstance(handoff, dict):
            handoff = None
        return {
            "action": action,
            "user_response": user_response,
            "handoff": handoff,
            "questions": questions,
        }

    def _workflow_control(
        self, agent: AgentDefinition, structured: dict[str, Any]
    ) -> dict[str, Any] | None:
        if agent.agent_id != "chat_agent":
            return None
        action = structured.get("action")
        if isinstance(action, str):
            return {"route": action}
        return {"route": "ask_user"}

    def _default_research_handoff(
        self, input_payload: dict[str, Any], user_response: str
    ) -> dict[str, Any]:
        request = self._extract_user_request(input_payload)
        session_context = self._session_context_from_payload(input_payload)
        constraints = [
            "Ground claims in inspected FireGuard data, returned tool output, or cited sources.",
            "Do not invent missing data, statistics, examples, citations, or results.",
            "Label assumptions, gaps, and uncertainty.",
            "Keep notes compact.",
        ]
        context: dict[str, Any] = {"chat_response": user_response}
        if session_context is not None:
            context["session_context"] = session_context
            constraints.extend(
                [
                    "Read context.session_context before planning new work.",
                    "If context.session_context.active_result.kind is deliverable, preserve the existing report and specify the concrete changes the writer should apply.",
                    "If context.session_context.active_result.kind is failure, use the failed node, error, and last successful result to recover.",
                    "Do not replace concrete prior values with placeholders.",
                ]
            )
        return {
            "objective": (
                f"Use the provided session context to analyze the user's FireGuard intelligence request: {request}"
                if session_context is not None
                else f"Analyze the user's FireGuard intelligence request: {request}"
            ),
            "user_request": request,
            "constraints": constraints,
            "questions_to_answer": [
                "What fire, weather, location, and timing context matters?",
                "What should the writer produce?",
            ],
            "context": context,
            "attachments_summary": _attachment_summaries(input_payload),
        }

    def _default_writer_handoff(
        self, input_payload: dict[str, Any], user_response: str
    ) -> dict[str, Any]:
        request = self._extract_user_request(input_payload)
        session_context = self._session_context_from_payload(input_payload)
        task: dict[str, Any] = {
            "objective": f"Edit the existing FireGuard intelligence report as requested: {request}",
            "user_request": request,
            "research_notes": None,
            "constraints": [
                "Apply only the edits the user requested.",
                "Preserve unchanged sections from the existing report.",
                "Preserve all facts, statistics, citations, source notes, assumptions, gaps, and uncertainty labels.",
                "Do not invent new content, sources, analysis, statistics, or examples.",
            ],
            "context": {"chat_response": user_response},
            "attachments_summary": _attachment_summaries(input_payload),
        }
        if session_context is not None:
            task["context"]["session_context"] = session_context
            task["constraints"].append(
                "The existing report is in context.session_context.active_result.content; edit that instead of starting from scratch."
            )
        return task

    def _ensure_handoff_session_context(
        self, input_payload: dict[str, Any], handoff: dict[str, Any]
    ) -> dict[str, Any]:
        session_context = self._session_context_from_payload(input_payload)
        if session_context is None:
            return handoff
        next_handoff = {**handoff}
        context = next_handoff.get("context")
        next_context = {**context} if isinstance(context, dict) else {}
        next_context.setdefault("session_context", session_context)
        next_handoff["context"] = next_context
        constraints = next_handoff.get("constraints")
        extra = (
            "Use context.session_context as prior run state; do not replace concrete prior "
            "results with placeholders."
        )
        if isinstance(constraints, list):
            next_handoff["constraints"] = [*constraints, extra]
        else:
            next_handoff["constraints"] = [extra]
        return next_handoff

    def _session_context_from_payload(self, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        direct = payload.get("session_context")
        if isinstance(direct, dict):
            return direct
        nested_payload = payload.get("payload")
        if isinstance(nested_payload, dict):
            nested_context = nested_payload.get("session_context")
            if isinstance(nested_context, dict):
                return nested_context
        handoff = payload.get("handoff")
        if isinstance(handoff, dict):
            task = handoff.get("task")
            if isinstance(task, dict):
                context = task.get("context")
                if isinstance(context, dict):
                    session_context = context.get("session_context")
                    if isinstance(session_context, dict):
                        return session_context
        context = payload.get("context")
        if isinstance(context, dict):
            session_context = context.get("session_context")
            if isinstance(session_context, dict):
                return session_context
        return None

    def _handoff_payload(
        self,
        run: WorkflowRun,
        from_node_id: str,
        to_node_id: str,
        condition: str,
        outcome: dict[str, Any],
    ) -> dict[str, Any]:
        from_node = self._node(run, from_node_id)
        to_node = self._node(run, to_node_id)
        user_request = self._initial_user_request(run)
        structured = outcome.get("structured")
        if from_node_id == "chat_agent" and condition in {"handoff_to_research", "handoff_to_writer"}:
            handoff = structured.get("handoff") if isinstance(structured, dict) else None
            if isinstance(handoff, dict):
                return {
                    "handoff": {
                        "from_node_id": from_node_id,
                        "from_label": from_node.label,
                        "from_agent_id": self._node_agent_id(from_node),
                        "to_node_id": to_node_id,
                        "to_label": to_node.label,
                        "to_agent_id": self._node_agent_id(to_node),
                        "condition": condition,
                        "task": handoff,
                    }
                }
        if from_node_id == "chat_agent" and condition in {"ask_user", "respond", "report_failure"}:
            return {
                "message": outcome.get("message"),
                "action": condition,
                "user_request": user_request,
                "questions": structured.get("questions") if isinstance(structured, dict) else None,
            }
        return {
            "handoff": {
                "from_node_id": from_node_id,
                "from_label": from_node.label,
                "from_agent_id": self._node_agent_id(from_node),
                "to_node_id": to_node_id,
                "to_label": to_node.label,
                "to_agent_id": self._node_agent_id(to_node),
                "condition": condition,
                "user_request": user_request,
                "task": self._task_for_edge(
                    from_node_id, to_node_id, condition, outcome, user_request
                ),
            }
        }

    def _task_for_edge(
        self,
        from_node_id: str,
        to_node_id: str,
        condition: str,
        outcome: dict[str, Any],
        user_request: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if from_node_id == "research_agent" and to_node_id == "writer_agent":
            task = {
                "objective": "Write the final FireGuard intelligence response.",
                "user_request": user_request,
                "research_notes": outcome.get("message"),
                "constraints": [
                    "Preserve data-quality limits, uncertainty labels, and unsupported-result notes from research.",
                    "Do not invent missing data, statistics, examples, citations, or results.",
                    "Keep the response concise.",
                ],
            }
            session_context = self._session_context_from_payload(outcome.get("payload"))
            if session_context is not None:
                task["session_context"] = session_context
                task["constraints"].extend(
                    [
                        "If session_context.active_result.kind is deliverable, update that existing report instead of starting from scratch.",
                        "Preserve unchanged sections from the existing report unless the research notes call for changes.",
                        "If session_context.active_result.kind is failure, use the last successful result and recovery notes as the starting point.",
                    ]
                )
            return task
        if from_node_id == "writer_agent" and to_node_id == "style_agent":
            return {
                "objective": "Edit the markdown draft into a polished FireGuard operational intelligence report.",
                "user_request": user_request,
                "report_markdown": outcome.get("message"),
                "constraints": [
                    "Improve structure, hierarchy, rhythm, and layout.",
                    "Reduce bullet-heavy note dumps by using short prose, tables, or callouts where appropriate.",
                    "Preserve factual content exactly: do not alter statistics, dates, names, sources, caveats, or findings.",
                    "Do not invent missing analysis, examples, recommendations, sources, or computations.",
                    "Use supported layout directives only where they improve presentation.",
                ],
            }
        return {
            "objective": f"Continue workflow from {from_node_id} to {to_node_id}.",
            "condition": condition,
            "user_request": user_request,
            "upstream_result": {
                "agent_id": outcome.get("agent_id"),
                "message": outcome.get("message"),
            },
        }

    def _extract_user_request(self, payload: dict[str, Any]) -> str:
        if "prompt" in payload and isinstance(payload["prompt"], str):
            return payload["prompt"]
        handoff = payload.get("handoff")
        if isinstance(handoff, dict):
            request = handoff.get("user_request")
            if isinstance(request, str):
                return request
            if isinstance(request, dict):
                prompt = request.get("prompt")
                if isinstance(prompt, str):
                    return prompt
        return json.dumps(payload, default=str)

    def _node_agent_id(self, node: WorkflowNode) -> str | None:
        if node.config.kind == NodeKind.agent:
            return node.config.agent_id
        return None

    def _initial_user_request(self, run: WorkflowRun) -> dict[str, Any] | None:
        state = run.node_states.get(run.workflow.start_node_id)
        if state is None:
            return None
        payload = state.output_payload if state.output_payload is not None else state.input_payload
        return payload

    async def _emit(
        self,
        run: WorkflowRun,
        event_type: str,
        *,
        node_id: str | None = None,
        agent_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> StreamEvent:
        event = StreamEvent(
            event_type=event_type,
            session_id=run.session_id,
            run_id=run.run_id,
            node_id=node_id,
            agent_id=agent_id,
            data=data if data is not None else {},
        )
        return await self._record_event(event)

    async def _record_event(self, event: StreamEvent) -> StreamEvent:
        self.store.append_event(event)
        self.store.append_trace(
            TraceEvent(
                event_id=event.event_id,
                session_id=event.session_id,
                run_id=event.run_id,
                node_id=event.node_id,
                agent_id=event.agent_id,
                event_type=event.event_type,
                data=event.data,
            )
        )
        await self.broker.publish(event)
        return event

    async def _trace(self, run: WorkflowRun, event_type: str, *, data: dict[str, Any]) -> None:
        self.store.append_trace(
            TraceEvent(
                session_id=run.session_id,
                run_id=run.run_id,
                event_type=event_type,
                data=data,
            )
        )

    async def _checkpoint(self, run: WorkflowRun, node_id: str | None) -> None:
        run = self.store.load_run(run.session_id, run.run_id)
        checkpoint = Checkpoint(
            session_id=run.session_id, run_id=run.run_id, node_id=node_id, run_state=run
        )
        event = StreamEvent(
            event_type="checkpoint.created",
            session_id=run.session_id,
            run_id=run.run_id,
            node_id=node_id,
            data={"checkpoint_id": checkpoint.checkpoint_id},
        )
        checkpoint.event_id = event.event_id
        self.store.write_checkpoint(checkpoint)
        await self._record_event(event)


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or len(value.strip()) == 0:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    raise ValueError("timeout_seconds must be a number when provided")


def _exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if len(message) > 0:
        return message
    return exc.__class__.__name__


def _research_child_system_prompt(system_prompt: str) -> str:
    return f"{RESEARCH_CHILD_TOOL_POLICY}{system_prompt}"


def _project_manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        datasets = []
    return {
        "scope": manifest.get("scope"),
        "path": manifest.get("path"),
        "index_prefix": manifest.get("index_prefix"),
        "reused": manifest.get("reused", False),
        "datasets": [
            {
                "name": dataset.get("name"),
                "index": dataset.get("index"),
                "file": dataset.get("file"),
                "total_matches": dataset.get("total_matches"),
                "exported_docs": dataset.get("exported_docs"),
                "truncated": dataset.get("truncated"),
            }
            for dataset in datasets
            if isinstance(dataset, dict)
        ],
    }


def _string_or_default(value: Any, default: str) -> str:
    if isinstance(value, str) and len(value.strip()) > 0:
        return value
    return default


def _prompt_from_agent_user_content(content: str) -> str | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content if len(content.strip()) > 0 else None
    if not isinstance(payload, dict):
        return content if len(content.strip()) > 0 else None
    prompt = payload.get("prompt")
    if isinstance(prompt, str) and len(prompt.strip()) > 0:
        return prompt
    handoff = payload.get("handoff")
    if isinstance(handoff, dict):
        user_request = handoff.get("user_request")
        if isinstance(user_request, dict):
            nested_prompt = user_request.get("prompt")
            if isinstance(nested_prompt, str) and len(nested_prompt.strip()) > 0:
                return nested_prompt
        if isinstance(user_request, str) and len(user_request.strip()) > 0:
            return user_request
    return None


def _assistant_visible_content(content: str) -> str | None:
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


def _structured_questions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    questions: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        if not isinstance(question, str) or len(question.strip()) == 0:
            continue
        options = item.get("options")
        normalized_options = (
            [option for option in options if isinstance(option, str) and len(option.strip()) > 0]
            if isinstance(options, list)
            else []
        )
        questions.append(
            {
                "id": item.get("id") if isinstance(item.get("id"), str) else f"q{index + 1}",
                "question": question,
                "options": normalized_options,
            }
        )
    return questions


def _loads_chat_json(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)


def _normalize_chat_route(parsed: dict[str, Any]) -> dict[str, Any]:
    if "action" in parsed:
        return parsed
    route = parsed.get("route")
    if route == "respond" and isinstance(parsed.get("respond"), dict):
        message = parsed["respond"].get("message")
        return {
            "action": "respond",
            "user_response": message if isinstance(message, str) else "",
            "handoff": None,
            "questions": None,
        }
    return parsed


def _agent_user_message(payload: dict[str, Any]) -> ChatMessage:
    text = json.dumps(payload, default=str)
    content_parts = _content_parts_for_payload(payload)
    metadata: dict[str, Any] = {}
    if content_parts is not None:
        metadata["openai_content_parts"] = content_parts
    return ChatMessage(role=MessageRole.user, content=text, metadata=metadata)


def _completion_payload(output: dict[str, Any]) -> dict[str, Any]:
    payload = output.get("payload") if isinstance(output, dict) else None
    if not isinstance(payload, dict):
        return output if isinstance(output, dict) else {"value": output}
    nested = payload.get("payload")
    if isinstance(nested, dict) and set(payload.keys()) == {"payload"}:
        return nested
    return payload


def _completion_message(payload: dict[str, Any]) -> str:
    for key in ("message", "report_markdown", "research_notes", "brief", "content", "user_response"):
        value = payload.get(key)
        if isinstance(value, str) and len(value.strip()) > 0:
            return value.strip()
    return json.dumps(payload, indent=2, default=str)


def _emit_message_completes_agent(agent: AgentDefinition, results: list[ToolResult]) -> bool:
    if len(results) == 0:
        return False
    if set(agent.tool_names) - {"emit_message", "complete_workflow_node"}:
        return False
    return all(result.ok and result.tool_name == "emit_message" for result in results)


def _content_parts_for_payload(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    attachments = _attachments_from_payload(payload)
    if len(attachments) == 0:
        return None
    parts: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Use the user request JSON and the attached files below. "
                "Images and PDFs are supplied as provider-native content parts. "
                "Text-like files are supplied as text parts."
            ),
        },
        {
            "type": "text",
            "text": json.dumps(_payload_without_attachment_data(payload), default=str),
        },
    ]
    for attachment in attachments:
        part = _content_part_for_attachment(attachment)
        if part is not None:
            parts.append(part)
    return parts


def _attachments_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_payload = payload.get("payload")
    if isinstance(raw_payload, dict):
        raw_attachments = raw_payload.get("attachments")
        if isinstance(raw_attachments, list):
            return [item for item in raw_attachments if isinstance(item, dict)]
    raw_attachments = payload.get("attachments")
    if isinstance(raw_attachments, list):
        return [item for item in raw_attachments if isinstance(item, dict)]
    return []


def _attachment_summaries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for attachment in _attachments_from_payload(payload):
        summary: dict[str, Any] = {}
        for key in ("name", "media_type", "size"):
            value = attachment.get(key)
            if isinstance(value, str | int):
                summary[key] = value
        if len(summary) > 0:
            summaries.append(summary)
    return summaries


def _payload_without_attachment_data(payload: dict[str, Any]) -> dict[str, Any]:
    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    f"<{len(str(item))} chars omitted>"
                    if key in {"data_url", "base64", "text"}
                    and isinstance(item, str)
                    and len(item) > 500
                    else scrub(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    scrubbed = scrub(payload)
    return scrubbed if isinstance(scrubbed, dict) else payload


def _content_part_for_attachment(attachment: dict[str, Any]) -> dict[str, Any] | None:
    name = str(attachment.get("name") or "attachment")
    media_type = str(
        attachment.get("media_type") or attachment.get("type") or "application/octet-stream"
    )
    data_url = attachment.get("data_url")
    text = attachment.get("text")
    if (
        media_type.startswith("image/")
        and isinstance(data_url, str)
        and data_url.startswith("data:")
    ):
        return {"type": "image_url", "image_url": {"url": data_url}}
    if (
        media_type == "application/pdf"
        and isinstance(data_url, str)
        and data_url.startswith("data:")
    ):
        return {"type": "file", "file": {"filename": name, "file_data": data_url}}
    if isinstance(text, str) and len(text.strip()) > 0:
        return {
            "type": "text",
            "text": f"Attached file: {name}\nMedia type: {media_type}\n\n{text}",
        }
    if isinstance(data_url, str) and data_url.startswith("data:"):
        return {"type": "file", "file": {"filename": name, "file_data": data_url}}
    return None
