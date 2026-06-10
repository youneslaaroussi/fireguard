from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class NodeKind(StrEnum):
    human_trigger = "human_trigger"
    agent = "agent"
    approval_gate = "approval_gate"
    tool_call = "tool_call"
    message = "message"
    subagent = "subagent"
    fleet = "fleet"
    join_node = "join"
    terminal = "terminal"


class RunStatus(StrEnum):
    created = "created"
    running = "running"
    waiting_for_approval = "waiting_for_approval"
    completed = "completed"
    failed = "failed"
    rejected = "rejected"
    stopped = "stopped"


class NodeStatus(StrEnum):
    pending = "pending"
    running = "running"
    waiting = "waiting"
    completed = "completed"
    failed = "failed"
    rejected = "rejected"
    skipped = "skipped"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ModelTier(StrEnum):
    light = "light"
    pro = "pro"


class MessageRole(StrEnum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    model_tier: ModelTier
    call_type: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    cost: float | None = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]
    mutating: bool = False
    concurrency_safe: bool = True
    requires_permission: bool = False
    timeout_seconds: float | None = None
    retry_attempts: int = 1


class ToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invocation_id: str
    tool_name: str
    session_id: str
    run_id: str
    node_id: str
    agent_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invocation_id: str
    tool_name: str
    ok: bool
    output: dict[str, Any]
    started_at: datetime
    completed_at: datetime


class AgentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    name: str
    system_prompt: str
    model_tier: ModelTier = ModelTier.pro
    tool_names: list[str] = Field(default_factory=list)
    response_format: dict[str, Any] | None = None
    max_turns: int | None = None
    timeout_seconds: float | None = None
    max_parallel_tool_calls: int | None = None


class HumanTriggerNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[NodeKind.human_trigger] = NodeKind.human_trigger


class AgentNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[NodeKind.agent] = NodeKind.agent
    agent_id: str


class ApprovalGateNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[NodeKind.approval_gate] = NodeKind.approval_gate
    title: str
    instructions: str
    approve_edge: str | None = None
    reject_edge: str | None = None


class ToolCallNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[NodeKind.tool_call] = NodeKind.tool_call
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class MessageNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[NodeKind.message] = NodeKind.message
    message: str


class SubagentNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[NodeKind.subagent] = NodeKind.subagent
    agent: AgentDefinition
    objective: str
    timeout_seconds: float | None = None


class FleetChild(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: str
    objective: str
    agent: AgentDefinition
    timeout_seconds: float | None = None


class FleetNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[NodeKind.fleet] = NodeKind.fleet
    children: list[FleetChild]
    max_concurrency: int | None = None
    failure_policy: Literal["fail_fast", "collect_completed"] = "collect_completed"


class JoinNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[NodeKind.join_node] = NodeKind.join_node


class TerminalNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[NodeKind.terminal] = NodeKind.terminal


NodeConfig = (
    HumanTriggerNode
    | AgentNode
    | ApprovalGateNode
    | ToolCallNode
    | MessageNode
    | SubagentNode
    | FleetNode
    | JoinNode
    | TerminalNode
)


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    label: str
    config: NodeConfig = Field(discriminator="kind")


class NodeEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    from_node_id: str
    to_node_id: str
    condition: str = "default"


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    name: str
    start_node_id: str
    nodes: list[WorkflowNode]
    edges: list[NodeEdge]
    agents: list[AgentDefinition] = Field(default_factory=list)


class NodeRunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    status: NodeStatus = NodeStatus.pending
    input_payload: dict[str, Any] | None = None
    output_payload: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(default_factory=lambda: new_id("appr"))
    node_id: str
    session_id: str
    run_id: str
    status: ApprovalStatus = ApprovalStatus.pending
    title: str
    instructions: str
    payload: dict[str, Any]
    reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class WorkflowRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    run_id: str
    workflow: WorkflowDefinition
    status: RunStatus = RunStatus.created
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    current_node_id: str | None = None
    node_states: dict[str, NodeRunState] = Field(default_factory=dict)
    approvals: dict[str, ApprovalRecord] = Field(default_factory=dict)
    usage: list[TokenUsage] = Field(default_factory=list)
    attempt: int = 1
    parent_run_id: str | None = None


class SessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: new_id("evt"))
    session_id: str
    run_id: str | None = None
    node_id: str | None = None
    agent_id: str | None = None
    event_type: str
    timestamp: datetime = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)


class StreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: new_id("sse"))
    event_type: str
    session_id: str
    run_id: str
    node_id: str | None = None
    agent_id: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> str:
        return (
            f"id: {self.event_id}\n"
            f"event: {self.event_type}\n"
            f"data: {self.model_dump_json()}\n\n"
        )


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(default_factory=lambda: new_id("chk"))
    session_id: str
    run_id: str
    node_id: str | None = None
    event_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    run_state: WorkflowRun


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = "FireGuard Intelligence Session"
    metadata: dict[str, Any] = Field(default_factory=dict)


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    workflow_id: str = "fireguard_intelligence"
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RestartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str | None = None
    event_id: str | None = None
    node_id: str | None = None


class ChatRestartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    event_id: str | None = None
    node_id: str | None = None
    user_message: str | None = None
