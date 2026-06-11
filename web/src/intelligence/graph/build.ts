import type { Edge, Node, XYPosition } from "@xyflow/react";
import type { StreamEvent, WorkflowRun, EdgePayload } from "../types";
import {
  ACCENT_COLORS,
  CLICKABLE_EDGE_IDS,
  FALLBACK_ICON,
  NODE_ICONS,
  NODE_ORDER,
  PRIMARY_EDGE_IDS,
  PRIMARY_POSITIONS,
  RERUNNABLE_NODES,
  STATUS_BORDER,
  TOOL_ACCENT_COLORS,
  TOOL_PLATFORM_BADGE,
} from "./constants";
import type { FlowEdgeData, FlowNodeData, SubagentGraphNode, ToolGraphNode } from "./types";
import {
  AlertTriangle,
  Bot,
  Database,
  Flame,
  House,
  MapPin,
  Navigation,
  Search,
  SquareTerminal,
} from "lucide-react";

// Public

export function buildGraphSignature(
  run: WorkflowRun | null,
  selectedNodeId: string | null,
  edgePayloads: Record<string, EdgePayload>,
  events: StreamEvent[],
): string {
  if (run === null) return "empty";
  const statuses = run.workflow.nodes
    .map((n) => `${n.node_id}:${run.node_states[n.node_id]?.status ?? "pending"}`)
    .join("|");
  const subs = subagentsFromEvents(events).map((n) => `${n.node_id}:${n.status}`).join("|");
  const tools = toolsFromEvents(events).map((n) => `${n.node_id}:${n.status}`).join("|");
  const payloads = Object.keys(edgePayloads).sort().join("|");
  return `${run.run_id}::${run.status}::${selectedNodeId ?? ""}::${statuses}::${subs}::${tools}::${payloads}`;
}

export function buildGraphModel(
  run: WorkflowRun,
  selectedNodeId: string | null,
  edgePayloads: Record<string, EdgePayload>,
  events: StreamEvent[],
  onSelectEdge: (id: string) => void,
  onRestartFromNode: ((nodeId: string) => void) | null,
): { nodes: Node<FlowNodeData>[]; edges: Edge<FlowEdgeData>[] } {
  const subagentList = subagentsFromEvents(events);
  const toolList = toolsFromEvents(events);

  const subagentPositions = new Map<string, XYPosition>();
  const subagentNodes = buildSubagentNodes(subagentList, selectedNodeId, subagentPositions);
  const toolNodes = buildToolNodes(toolList, selectedNodeId, subagentPositions);

  return {
    nodes: [
      ...buildPrimaryNodes(run, selectedNodeId, onRestartFromNode),
      ...subagentNodes,
      ...toolNodes,
    ],
    edges: [
      ...buildPrimaryEdges(run, edgePayloads, onSelectEdge),
      ...buildSubagentEdges(subagentNodes, edgePayloads, onSelectEdge),
      ...buildToolEdges(toolList, edgePayloads, onSelectEdge),
    ],
  };
}

// Node builders

function buildPrimaryNodes(
  run: WorkflowRun,
  selectedNodeId: string | null,
  onRestartFromNode: ((nodeId: string) => void) | null,
) {
  return [...run.workflow.nodes]
    .sort((a, b) => NODE_ORDER.indexOf(a.node_id) - NODE_ORDER.indexOf(b.node_id))
    .map((node): Node<FlowNodeData> => {
      const status = run.node_states[node.node_id]?.status ?? "pending";
      const toolName = node.config.tool_name;
      const accentColor =
        typeof toolName === "string" && toolName === "exa_search"
          ? ACCENT_COLORS.exa_search
          : typeof toolName === "string" && toolName.startsWith("sandbox_")
            ? ACCENT_COLORS.sandbox
            : ACCENT_COLORS[node.node_id] ?? ACCENT_COLORS[node.config.kind as string] ?? "#6366f1";
      const canRestart =
        onRestartFromNode !== null &&
        RERUNNABLE_NODES.has(node.node_id) &&
        (status === "completed" || status === "failed");
      return {
        id: node.node_id,
        type: "workflow",
        position: PRIMARY_POSITIONS[node.node_id] ?? { x: 30, y: 120 },
        data: {
          label: node.label,
          status,
          accentColor,
          NodeIcon: NODE_ICONS[node.node_id] ?? FALLBACK_ICON,
          selected: selectedNodeId === node.node_id,
          compact: false,
          onRestart: canRestart ? () => onRestartFromNode(node.node_id) : null,
        },
      };
    });
}

function buildSubagentNodes(
  list: SubagentGraphNode[],
  selectedNodeId: string | null,
  positions: Map<string, XYPosition>,
): Node<FlowNodeData>[] {
  return list.map((sub, i) => {
    const pos = subagentPosition(i, list.length);
    positions.set(sub.node_id, pos);
    return {
      id: sub.node_id,
      type: "workflow",
      position: pos,
      data: {
        label: sub.label,
        status: sub.status,
        accentColor: ACCENT_COLORS.subagent,
        NodeIcon: Bot,
        selected: selectedNodeId === sub.node_id,
        compact: false,
        onRestart: null,
      },
    };
  });
}

function buildToolNodes(
  list: ToolGraphNode[],
  selectedNodeId: string | null,
  subPositions: Map<string, XYPosition>,
): Node<FlowNodeData>[] {
  const siblingCount = new Map<string, number>();
  return list.map((tool) => {
    const idx = siblingCount.get(tool.parent_id) ?? 0;
    siblingCount.set(tool.parent_id, idx + 1);
    return {
      id: tool.node_id,
      type: "workflow",
      position: toolPosition(subPositions.get(tool.parent_id), idx),
      data: {
        label: tool.label,
        status: tool.status,
        accentColor: toolAccent(tool.tool_name),
        NodeIcon: toolIcon(tool.tool_name),
        selected: selectedNodeId === tool.node_id,
        compact: true,
        onRestart: null,
        platformBadge: TOOL_PLATFORM_BADGE[tool.tool_name] ?? null,
      },
    };
  });
}

// Edge builders

function buildPrimaryEdges(
  run: WorkflowRun,
  edgePayloads: Record<string, EdgePayload>,
  onSelectEdge: (id: string) => void,
): Edge<FlowEdgeData>[] {
  return run.workflow.edges
    .filter((e) => PRIMARY_EDGE_IDS.has(e.edge_id))
    .map((edge) => {
      const clickable = CLICKABLE_EDGE_IDS.has(edge.edge_id);
      const hasPayload = edgePayloads[edge.edge_id] !== undefined;
      const targetStatus = run.node_states[edge.to_node_id]?.status ?? "pending";
      const strokeColor = hasPayload ? "#10b981" : STATUS_BORDER[targetStatus] ?? "#1e3a5f";
      return makeEdge({
        id: edge.edge_id,
        source: edge.from_node_id,
        target: edge.to_node_id,
        clickable,
        hasPayload,
        title: "View handoff payload",
        onSelectEdge,
        animated: run.status === "running" && targetStatus === "running",
        strokeColor,
      });
    });
}

function buildSubagentEdges(
  subNodes: Node<FlowNodeData>[],
  edgePayloads: Record<string, EdgePayload>,
  onSelectEdge: (id: string) => void,
): Edge<FlowEdgeData>[] {
  return subNodes.map((sub) => {
    const id = `edge_${sub.id}_to_research_agent`;
    const status = sub.data.status as string;
    const strokeColor = status === "completed" ? "#10b981" : status === "running" ? "#06b6d4" : "#1e3a5f";
    return makeEdge({
      id,
      source: sub.id,
      target: "research_agent",
      clickable: true,
      hasPayload: edgePayloads[id] !== undefined,
      title: "View subagent result",
      onSelectEdge,
      animated: status === "running",
      dashed: true,
      strokeColor,
    });
  });
}

function buildToolEdges(
  list: ToolGraphNode[],
  edgePayloads: Record<string, EdgePayload>,
  onSelectEdge: (id: string) => void,
): Edge<FlowEdgeData>[] {
  return list.map((tool) => {
    const id = `edge_${tool.node_id}_to_${tool.parent_id}`;
    const strokeColor = tool.status === "completed" ? "#10b981" : tool.status === "running" ? "#f97316" : "#1e3a5f";
    return makeEdge({
      id,
      source: tool.node_id,
      target: tool.parent_id,
      clickable: true,
      hasPayload: edgePayloads[id] !== undefined,
      title: `View ${tool.tool_name} result`,
      onSelectEdge,
      animated: tool.status === "running",
      dashed: true,
      strokeColor,
    });
  });
}

// Positioning

function subagentPosition(index: number, total: number): XYPosition {
  // Two-column grid below research_agent (x:90, y:300); each column 192px wide, centered at x=90.
  const cols = Math.min(total, 2);
  const col = index % cols;
  const row = Math.floor(index / cols);
  const nodeWidth = 172;
  const gap = 20;
  const totalWidth = cols * nodeWidth + (cols - 1) * gap;
  const startX = 90 - totalWidth / 2;
  return { x: startX + col * (nodeWidth + gap), y: 440 + row * 140 };
}

function toolPosition(parentPos: XYPosition | undefined, siblingIndex: number): XYPosition {
  const p = parentPos ?? { x: 90, y: 440 };
  // Stack tools vertically below their parent subagent.
  return { x: p.x, y: p.y + 130 + siblingIndex * 110 };
}

// Event parsing

export function subagentsFromEvents(events: StreamEvent[]): SubagentGraphNode[] {
  const map = new Map<string, SubagentGraphNode>();
  for (const ev of events) {
    if (ev.agent_id === null) continue;
    if (ev.event_type === "subagent.started" || ev.event_type === "fleet.child.started") {
      const childId = ev.data.child_id;
      map.set(ev.agent_id, {
        node_id: ev.agent_id,
        label: typeof childId === "string" ? childId : shortLabel(ev.agent_id),
        status: "running",
      });
    }
    if (ev.event_type === "subagent.completed" || ev.event_type === "fleet.child.completed") {
      const existing = map.get(ev.agent_id);
      map.set(ev.agent_id, {
        node_id: ev.agent_id,
        label: existing?.label ?? shortLabel(ev.agent_id),
        status: ev.data.ok === false ? "failed" : "completed",
      });
    }
    if (ev.event_type === "subagent.failed") {
      const existing = map.get(ev.agent_id);
      map.set(ev.agent_id, {
        node_id: ev.agent_id,
        label: existing?.label ?? shortLabel(ev.agent_id),
        status: "failed",
      });
    }
  }
  return Array.from(map.values());
}

export function toolsFromEvents(events: StreamEvent[]): ToolGraphNode[] {
  const map = new Map<string, ToolGraphNode>();
  for (const ev of events) {
    if (ev.agent_id === null) continue;
    if (
      ev.event_type !== "tool.started" &&
      ev.event_type !== "tool.completed" &&
      ev.event_type !== "tool.failed"
    ) continue;
    const toolName = ev.data.tool_name;
    if (!isGraphTool(toolName)) continue;
    const invId = ev.data.invocation_id;
    if (typeof invId !== "string" || invId.length === 0) continue;
    const nodeId = `tool_${ev.agent_id}_${invId}`;
    const existing = map.get(nodeId);
    map.set(nodeId, {
      node_id: nodeId,
      parent_id: ev.agent_id,
      label: toolLabel(ev, existing?.label),
      status: ev.event_type === "tool.started" ? "running" : ev.event_type === "tool.completed" ? "completed" : "failed",
      tool_name: typeof toolName === "string" ? toolName : "tool",
    });
  }
  return Array.from(map.values());
}

// Helpers

function makeEdge({
  id, source, target, clickable, hasPayload, title, onSelectEdge, animated, dashed = false, strokeColor,
}: {
  id: string; source: string; target: string;
  clickable: boolean; hasPayload: boolean; title: string;
  onSelectEdge: (id: string) => void;
  animated: boolean; dashed?: boolean; strokeColor: string;
}): Edge<FlowEdgeData> {
  return {
    id,
    type: "workflow",
    source,
    target,
    animated,
    data: { clickable, hasPayload, title, strokeColor, onSelectEdge },
    style: { stroke: strokeColor, strokeWidth: animated ? 2 : 1.5, strokeDasharray: dashed ? "6 4" : undefined },
    markerEnd: { type: "arrowclosed", color: strokeColor, width: 14, height: 14 },
  };
}

function toolLabel(ev: StreamEvent, fallback = "tool"): string {
  const args = ev.data.args;
  if (isObj(args) && typeof args.query === "string") return trunc(args.query);
  if (isObj(args) && Array.isArray(args.command)) return trunc(args.command.join(" "));
  const out = ev.data.output;
  if (isObj(out) && typeof out.query === "string") return trunc(out.query);
  const t = ev.data.tool_name;
  if (typeof t === "string") return t.replace(/^sandbox_/, "sandbox ").replace(/^fireguard_/, "FireGuard ");
  return fallback;
}

function isGraphTool(toolName: unknown): toolName is string {
  return (
    toolName === "exa_search" ||
    (typeof toolName === "string" &&
      (toolName.startsWith("sandbox_") || toolName.startsWith("fireguard_")))
  );
}

function toolAccent(toolName: string): string {
  if (TOOL_ACCENT_COLORS[toolName]) return TOOL_ACCENT_COLORS[toolName];
  if (toolName === "exa_search") return ACCENT_COLORS.exa_search;
  if (toolName.startsWith("fireguard_")) return ACCENT_COLORS.fireguard;
  return ACCENT_COLORS.sandbox;
}

function toolIcon(toolName: string) {
  if (toolName === "fireguard_search_zones") return MapPin;
  if (toolName === "fireguard_search_shelters") return House;
  if (toolName === "fireguard_search_road_events") return AlertTriangle;
  if (toolName === "fireguard_search_events") return Flame;
  if (toolName === "fireguard_evaluate_route") return Navigation;
  if (toolName === "fireguard_map_annotation") return MapPin;
  if (toolName === "exa_search") return Search;
  if (toolName.startsWith("fireguard_")) return Database;
  return SquareTerminal;
}

function shortLabel(id: string): string {
  return id.replace(/^subagent_/, "").replace(/^fleet_/, "Fleet ").slice(0, 20);
}

function trunc(s: string, max = 22): string {
  return s.length > max ? `${s.slice(0, max - 3)}...` : s;
}

function isObj(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}
