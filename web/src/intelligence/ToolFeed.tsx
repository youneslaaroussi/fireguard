import { logoForTool } from "./logos";
import type { ChatMessage, StreamEvent } from "./types";

const TOOL_LABELS: Record<string, string> = {
  fireguard_search_zones:       "Search zones",
  fireguard_search_shelters:    "Search shelters",
  fireguard_search_road_events: "Search road events",
  fireguard_search_events:      "Search detections",
  fireguard_evaluate_route:     "Evaluate route",
  fireguard_map_annotation:     "Map annotation",
  fireguard_bcws_context:       "BCWS context",
  fireguard_stats:              "Stats",
  exa_search:                   "Web search",
};

export interface ToolCall {
  invocationId: string;
  toolName: string;
  status: "running" | "done" | "failed";
  label: string;
  nodeId: string | null;
  agentId: string | null;
  runId: string | null;
}

export function buildAllToolCalls(events: StreamEvent[]): ToolCall[] {
  const map = new Map<string, ToolCall>();
  for (const ev of events) {
    if (
      ev.event_type !== "tool.started" &&
      ev.event_type !== "tool.completed" &&
      ev.event_type !== "tool.failed"
    ) continue;
    const toolName = typeof ev.data.tool_name === "string" ? ev.data.tool_name : null;
    const invId = typeof ev.data.invocation_id === "string" ? ev.data.invocation_id : null;
    if (!toolName || !invId) continue;
    map.set(invId, {
      invocationId: invId,
      toolName,
      label: TOOL_LABELS[toolName] ?? toolName.replace(/_/g, " "),
      nodeId: ev.node_id,
      agentId: ev.agent_id,
      runId: ev.run_id,
      status:
        ev.event_type === "tool.started" ? "running"
        : ev.event_type === "tool.completed" ? "done"
        : "failed",
    });
  }
  return Array.from(map.values());
}

export function toolCallsForMessage(all: ToolCall[], message: ChatMessage): ToolCall[] {
  return all.filter((c) => {
    if (message.run_id && c.runId !== message.run_id) return false;
    const msgNode = message.node_id ?? message.agent_id ?? null;
    const callNode = c.nodeId ?? c.agentId ?? null;
    return msgNode !== null && callNode !== null && msgNode === callNode;
  });
}

function ToolChip({ call }: { call: ToolCall }) {
  const logo = logoForTool(call.toolName);
  return (
    <div className={`toolChip toolChip--${call.status}`} title={call.toolName}>
      <span className="toolChipLogo">
        {logo ? (
          <img src={logo.src} alt={logo.label} width={11} height={11} />
        ) : (
          <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
            <rect x="1" y="1" width="9" height="9" rx="2" stroke="#4b5563" strokeWidth="1.1"/>
          </svg>
        )}
      </span>
      <span className="toolChipLabel">{call.label}</span>
      <span className="toolChipStatus">
        {call.status === "running" && (
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
            <circle cx="4" cy="4" r="3" stroke="#60a5fa" strokeWidth="1.3" strokeDasharray="4 3" className="toolChipSpinner"/>
          </svg>
        )}
        {call.status === "done" && (
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
            <path d="M1.5 4L3.5 6l3-3.5" stroke="#4ade80" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        )}
        {call.status === "failed" && (
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
            <path d="M2 2l4 4M6 2L2 6" stroke="#f87171" strokeWidth="1.3" strokeLinecap="round"/>
          </svg>
        )}
      </span>
    </div>
  );
}

interface Props {
  calls: ToolCall[];
}

export function MessageToolCalls({ calls }: Props) {
  if (calls.length === 0) return null;
  const running = calls.filter((c) => c.status === "running");
  const rest = calls.filter((c) => c.status !== "running");
  return (
    <div className="messageToolCalls">
      {running.map((c) => <ToolChip key={c.invocationId} call={c} />)}
      {rest.map((c) => <ToolChip key={c.invocationId} call={c} />)}
    </div>
  );
}
