import {
  Bot,
  FileCheck2,
  MessageSquareText,
  Paintbrush,
  PenLine,
  Search,
  UserRound,
  type LucideIcon,
} from "lucide-react";

/** Per-tool accent color (overrides generic fireguard accent) */
export const TOOL_ACCENT_COLORS: Record<string, string> = {
  fireguard_search_zones:       "#8b5cf6",
  fireguard_search_shelters:    "#10b981",
  fireguard_search_road_events: "#f59e0b",
  fireguard_search_events:      "#ef4444",
  fireguard_evaluate_route:     "#3b82f6",
  fireguard_map_annotation:     "#06b6d4",
  fireguard_bcws_context:       "#6366f1",
  fireguard_stats:              "#64748b",
};

/** Platform badge label per tool — shown as a small chip on the node */
export const TOOL_PLATFORM_BADGE: Record<string, string> = {
  fireguard_search_zones:       "Elastic",
  fireguard_search_shelters:    "Elastic",
  fireguard_search_road_events: "Elastic",
  fireguard_search_events:      "NASA FIRMS",
  fireguard_evaluate_route:     "Elastic",
  fireguard_map_annotation:     "MapAnnotate",
  fireguard_bcws_context:       "Elastic",
  fireguard_stats:              "Elastic",
  exa_search:                   "Exa",
};
import type { XYPosition } from "@xyflow/react";

export const NODE_ORDER = [
  "human_trigger",
  "chat_agent",
  "research_agent",
  "writer_agent",
  "style_agent",
  "terminal",
];

export const PRIMARY_EDGE_IDS = new Set([
  "edge_trigger_to_chat",
  "edge_chat_to_research",
  "edge_research_to_writer",
  "edge_writer_to_style",
  "edge_style_to_terminal",
]);

export const CLICKABLE_EDGE_IDS = new Set([
  "edge_chat_to_research",
  "edge_research_to_writer",
  "edge_writer_to_style",
]);

export const NODE_ICONS: Record<string, LucideIcon> = {
  human_trigger: UserRound,
  chat_agent: MessageSquareText,
  research_agent: Search,
  writer_agent: PenLine,
  style_agent: Paintbrush,
  terminal: FileCheck2,
};

export const FALLBACK_ICON = Bot;

export const RERUNNABLE_NODES = new Set([
  "chat_agent",
  "research_agent",
  "writer_agent",
  "style_agent",
]);

export const ACCENT_COLORS: Record<string, string> = {
  human_trigger: "#6366f1",
  chat_agent: "#3b82f6",
  research_agent: "#8b5cf6",
  writer_agent: "#f59e0b",
  style_agent: "#14b8a6",
  terminal: "#10b981",
  subagent: "#06b6d4",
  fleet: "#06b6d4",
  exa_search: "#f97316",
  sandbox: "#ec4899",
  fireguard: "#14b8a6",
};

/** Border/glow color per status */
export const STATUS_BORDER: Record<string, string> = {
  running: "#3b82f6",
  completed: "#10b981",
  failed: "#ef4444",
  rejected: "#ef4444",
  waiting: "#f59e0b",
  pending: "#1e2d3d",
  skipped: "#1e2d3d",
};

/** Text color per status */
export const STATUS_TEXT: Record<string, string> = {
  running: "#93c5fd",
  completed: "#6ee7b7",
  failed: "#fca5a5",
  rejected: "#fca5a5",
  waiting: "#fcd34d",
  pending: "#4b6278",
  skipped: "#4b6278",
};

/** Fixed positions for the primary pipeline column (top-to-bottom) */
export const PRIMARY_POSITIONS: Record<string, XYPosition> = {
  human_trigger: { x: 90, y:   20 },
  chat_agent:    { x: 90, y:  160 },
  research_agent:{ x: 90, y:  300 },
  writer_agent:  { x: 90, y:  440 },
  style_agent:   { x: 90, y:  580 },
  terminal:      { x: 90, y:  720 },
};
