export type RunStatus =
  | "created"
  | "running"
  | "waiting_for_approval"
  | "completed"
  | "failed"
  | "rejected"
  | "stopped";

export type NodeStatus =
  | "pending"
  | "running"
  | "waiting"
  | "completed"
  | "failed"
  | "rejected"
  | "skipped";

export type NodeKind =
  | "human_trigger"
  | "agent"
  | "approval_gate"
  | "tool_call"
  | "message"
  | "search"
  | "subagent"
  | "fleet"
  | "join"
  | "terminal";

export interface SessionRecord {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface SessionListItem extends SessionRecord {
  latest_run: WorkflowRun | null;
}

export interface WorkflowNode {
  node_id: string;
  label: string;
  config: { kind: NodeKind; [key: string]: unknown };
}

export interface NodeEdge {
  edge_id: string;
  from_node_id: string;
  to_node_id: string;
  condition: string;
}

export interface WorkflowDefinition {
  workflow_id: string;
  name: string;
  start_node_id: string;
  nodes: WorkflowNode[];
  edges: NodeEdge[];
}

export interface NodeRunState {
  node_id: string;
  status: NodeStatus;
  input_payload: Record<string, unknown> | null;
  output_payload: Record<string, unknown> | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface ApprovalRecord {
  approval_id: string;
  node_id: string;
  session_id: string;
  run_id: string;
  status: "pending" | "approved" | "rejected";
  title: string;
  instructions: string;
  payload: Record<string, unknown>;
  reason: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface TokenUsage {
  model: string;
  model_tier: "light" | "pro";
  call_type: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  reasoning_tokens: number | null;
  cached_tokens: number | null;
  cost: number | null;
}

export interface RuntimeSettings {
  provider: string;
  base_url: string;
  light_model: string;
  pro_model: string;
  max_completion_tokens: number;
  max_agent_turns: number;
  google_project_configured: boolean;
  google_cloud_location: string;
  fireguard_data_configured: boolean;
  fireguard_index_prefix: string;
  fireguard_data_bootstrap_enabled: boolean;
}

export interface WorkflowRun {
  session_id: string;
  run_id: string;
  workflow: WorkflowDefinition;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  current_node_id: string | null;
  node_states: Record<string, NodeRunState>;
  approvals: Record<string, ApprovalRecord>;
  usage: TokenUsage[];
  attempt: number;
  parent_run_id: string | null;
}

export interface StreamEvent {
  event_id: string;
  event_type: string;
  session_id: string;
  run_id: string;
  node_id: string | null;
  agent_id: string | null;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface NodeDetail {
  node: WorkflowNode;
  state: NodeRunState | null;
  agent_id: string | null;
  history: Record<string, unknown>[];
  transcript: Record<string, unknown>[];
  events: Record<string, unknown>[];
  trace: Record<string, unknown>[];
}

export interface ChatAnnotation {
  type: string;
  event_id?: string;
  node_id?: string | null;
  agent_id?: string | null;
  tool_name?: string;
  args?: Record<string, unknown>;
  output?: Record<string, unknown>;
  ok?: boolean;
  [key: string]: unknown;
}

export interface ChatAttachment {
  id: string;
  name: string;
  media_type: string;
  size: number;
  data_url: string;
  text?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: ChatAttachment[];
  annotations: ChatAnnotation[];
  agent_id?: string | null;
  run_id?: string | null;
  node_id?: string | null;
}

export interface ChatHistory {
  session_id: string;
  run_id: string;
  messages: ChatMessage[];
  events: StreamEvent[];
}

export interface EdgePayload {
  from_node_id: string;
  to_node_id: string;
  condition: string;
  payload: Record<string, unknown>;
}

export type ActionPriority = "immediate" | "urgent" | "monitor";

export interface ActionItem {
  id: string;
  priority: ActionPriority;
  title: string;
  detail?: string;
  owner?: string;
}

export interface ActionPlan {
  summary: string;
  actions: ActionItem[];
}

export type MapMarkerType = "hotspot" | "shelter_open" | "shelter_closed" | "zone" | "blockage" | "alternate";

export interface MapAnnotationMarker {
  lat: number;
  lon: number;
  type: MapMarkerType;
  label: string;
  detail?: string;
}

export interface MapAnnotationRoute {
  from_lat: number;
  from_lon: number;
  to_lat: number;
  to_lon: number;
  status: "safe" | "blocked" | "alternate";
  label: string;
  distance_km?: number;
  duration_minutes?: number;
}

export interface MapAnnotation {
  message: string;
  markers: MapAnnotationMarker[];
  routes: MapAnnotationRoute[];
}
