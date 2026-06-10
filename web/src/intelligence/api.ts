import type {
  ApprovalRecord,
  ChatAttachment,
  ChatHistory,
  NodeDetail,
  RuntimeSettings,
  SessionListItem,
  SessionRecord,
  StreamEvent,
  WorkflowRun,
} from "./types";

const API_BASE = "/api/intelligence";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return (await response.json()) as T;
}

export async function getSettings(): Promise<RuntimeSettings> {
  return requestJson<RuntimeSettings>("/settings");
}

export async function createSession(
  title: string,
  metadata: Record<string, unknown> = {},
): Promise<SessionRecord> {
  return requestJson<SessionRecord>("/sessions", {
    method: "POST",
    body: JSON.stringify({ title, metadata }),
  });
}

export async function listSessions(): Promise<SessionListItem[]> {
  return requestJson<SessionListItem[]>("/sessions");
}

export async function getLatestRun(sessionId: string): Promise<WorkflowRun | null> {
  return requestJson<WorkflowRun | null>(`/sessions/${sessionId}/runs/latest`);
}

export async function startRun(sessionId: string, prompt: string): Promise<WorkflowRun> {
  return requestJson<WorkflowRun>(`/sessions/${sessionId}/workflows/runs`, {
    method: "POST",
    body: JSON.stringify({ prompt, payload: { source: "ui" } }),
  });
}

export async function startChatRun(
  sessionId: string,
  prompt: string,
  attachments: ChatAttachment[] = [],
  sessionContext: Record<string, unknown> | null = null,
): Promise<WorkflowRun> {
  const payload: Record<string, unknown> = { source: "chat", attachments };
  if (sessionContext !== null) payload.session_context = sessionContext;
  return requestJson<WorkflowRun>(`/sessions/${sessionId}/chat/runs`, {
    method: "POST",
    body: JSON.stringify({ prompt, payload }),
  });
}

export async function getRun(sessionId: string, runId: string): Promise<WorkflowRun> {
  return requestJson<WorkflowRun>(`/sessions/${sessionId}/runs/${runId}`);
}

function ancestorQuery(includeAncestors: boolean): string {
  return includeAncestors ? "?include_ancestors=true" : "";
}

export async function getEvents(
  sessionId: string,
  runId: string,
  includeAncestors = false,
): Promise<StreamEvent[]> {
  return requestJson<StreamEvent[]>(
    `/sessions/${sessionId}/runs/${runId}/events${ancestorQuery(includeAncestors)}`,
  );
}

export async function getNodeDetail(
  sessionId: string,
  runId: string,
  nodeId: string,
  includeAncestors = false,
): Promise<NodeDetail> {
  return requestJson<NodeDetail>(
    `/sessions/${sessionId}/runs/${runId}/nodes/${nodeId}${ancestorQuery(includeAncestors)}`,
  );
}

export async function getRunHistory(
  sessionId: string,
  runId: string,
  includeAncestors = false,
): Promise<Record<string, unknown>[]> {
  return requestJson<Record<string, unknown>[]>(
    `/sessions/${sessionId}/runs/${runId}/history${ancestorQuery(includeAncestors)}`,
  );
}

export async function getChatHistory(
  sessionId: string,
  runId: string,
  includeAncestors = false,
): Promise<ChatHistory> {
  return requestJson<ChatHistory>(
    `/sessions/${sessionId}/runs/${runId}/chat${ancestorQuery(includeAncestors)}`,
  );
}

export async function resolveApproval(
  approval: ApprovalRecord,
  approve: boolean,
  reason: string,
): Promise<WorkflowRun> {
  return requestJson<WorkflowRun>(
    `/sessions/${approval.session_id}/runs/${approval.run_id}/approvals/${approval.approval_id}`,
    {
      method: "POST",
      body: JSON.stringify({ approve, reason, payload: { source: "ui" } }),
    },
  );
}

export async function restartRun(sessionId: string, runId: string): Promise<WorkflowRun> {
  return requestJson<WorkflowRun>(`/sessions/${sessionId}/runs/${runId}/restart`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function restartChatFrom(
  sessionId: string,
  runId: string,
  nodeId: string | null,
  eventId: string | null,
  userMessage: string | null,
): Promise<WorkflowRun> {
  return requestJson<WorkflowRun>(`/sessions/${sessionId}/chat/restart`, {
    method: "POST",
    body: JSON.stringify({
      run_id: runId,
      node_id: nodeId,
      event_id: eventId,
      user_message: userMessage,
    }),
  });
}

export async function stopRun(sessionId: string, runId: string): Promise<WorkflowRun> {
  return requestJson<WorkflowRun>(`/sessions/${sessionId}/runs/${runId}/stop`, {
    method: "POST",
  });
}

export function streamRun(
  sessionId: string,
  runId: string,
  onEvent: (event: StreamEvent) => void,
  onError: (error: Event) => void,
): EventSource {
  const source = new EventSource(`${API_BASE}/sessions/${sessionId}/runs/${runId}/stream`);
  const eventTypes = [
    "run.started",
    "sandbox.starting",
    "sandbox.ready",
    "sandbox.failed",
    "sandbox.terminated",
    "project_data.starting",
    "project_data.ready",
    "project_data.failed",
    "workflow.node.started",
    "workflow.node.completed",
    "workflow.node.failed",
    "workflow.error.routed",
    "workflow.handoff.created",
    "agent.started",
    "agent.message.delta",
    "agent.message.completed",
    "agent.tool_calls.requested",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "subagent.started",
    "subagent.completed",
    "subagent.failed",
    "fleet.started",
    "fleet.child.started",
    "fleet.child.completed",
    "fleet.completed",
    "approval.requested",
    "approval.resolved",
    "checkpoint.created",
    "retry.scheduled",
    "usage.updated",
    "run.completed",
    "run.failed",
    "run.stopped",
  ];
  for (const type of eventTypes) {
    source.addEventListener(type, (message) => {
      onEvent(JSON.parse((message as MessageEvent).data) as StreamEvent);
    });
  }
  source.onerror = onError;
  return source;
}
