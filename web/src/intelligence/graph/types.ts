import type { LucideIcon } from "lucide-react";

export interface FlowNodeData extends Record<string, unknown> {
  label: string;
  status: string;
  accentColor: string;
  NodeIcon: LucideIcon;
  selected: boolean;
  compact: boolean;
  onRestart: (() => void) | null;
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
  status: string;
  tool_name: string;
}
