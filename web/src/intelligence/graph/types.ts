import type { LucideIcon } from "lucide-react";

export interface FlowNodeData extends Record<string, unknown> {
  label: string;
  summary?: string;
  status: string;
  accentColor: string;
  NodeIcon: LucideIcon;
  selected: boolean;
  compact: boolean;
  importance?: number;
  cluster?: string;
  layer?: "workflow" | "subagent" | "tool" | "entity";
  onRestart: (() => void) | null;
  platformBadge?: string | null;
}

export interface FlowEdgeData extends Record<string, unknown> {
  clickable: boolean;
  hasPayload: boolean;
  title: string;
  strokeColor: string;
  onSelectEdge: (edgeId: string) => void;
}

export interface SubagentGraphNode {
  node_id: string;
  label: string;
  status: string;
}

export interface ToolGraphNode {
  node_id: string;
  parent_id: string;
  label: string;
  summary?: string;
  status: string;
  tool_name: string;
  output?: Record<string, unknown>;
}

export interface EntityGraphNode {
  node_id: string;
  parent_id: string;
  label: string;
  summary?: string;
  status: string;
  accentColor: string;
  importance: number;
  platformBadge?: string | null;
}
