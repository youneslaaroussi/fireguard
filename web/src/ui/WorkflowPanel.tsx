import { useState } from "react";
import { WorkflowGraph } from "../intelligence/WorkflowGraph";
import type { NodeRunState, RunStatus, StreamEvent, WorkflowRun } from "../intelligence/types";

type Props = {
  run: WorkflowRun | null;
  events: StreamEvent[];
  onClose: () => void;
};

const STATUS_COLOR: Record<RunStatus, string> = {
  created:              "#4a7aaa",
  running:              "#3ab870",
  waiting_for_approval: "#f0a840",
  completed:            "#2a8850",
  failed:               "#e04040",
  rejected:             "#a04040",
  stopped:              "#5a6a7a",
};

const NODE_STATUS_DOT: Record<string, string> = {
  running:   "#3ab870",
  completed: "#2a6840",
  failed:    "#e04040",
  waiting:   "#f0a840",
  pending:   "#1a3352",
  skipped:   "#2a3a4a",
  rejected:  "#803030",
};

export function WorkflowPanel({ run, events, onClose }: Props) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const statusColor = run ? (STATUS_COLOR[run.status] ?? "#4a7aaa") : "#1a3352";
  const nodeStates: Record<string, NodeRunState> = run?.node_states ?? {};
  const nodes = run?.workflow.nodes ?? [];

  // Summary counts
  const running   = nodes.filter((n) => nodeStates[n.node_id]?.status === "running").length;
  const completed = nodes.filter((n) => nodeStates[n.node_id]?.status === "completed").length;
  const failed    = nodes.filter((n) => nodeStates[n.node_id]?.status === "failed").length;

  return (
    <div className="wfPanel">
      {/* Header */}
      <div className="wfPanelHeader">
        <div className="wfPanelTitle">
          <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden="true">
            <circle cx="5.5" cy="5.5" r="4.5" stroke={statusColor} strokeWidth="1.2"/>
            <circle cx="5.5" cy="5.5" r="2" fill={statusColor}/>
          </svg>
          WORKFLOW
          {run && (
            <span className="wfRunStatus" style={{ color: statusColor }}>
              {run.status.replace(/_/g, " ").toUpperCase()}
            </span>
          )}
        </div>

        {/* Node status mini-pills */}
        {run && (
          <div className="wfNodeCounts">
            {running   > 0 && <span style={{ color: "#3ab870" }}>{running}▶</span>}
            {completed > 0 && <span style={{ color: "#2a6840" }}>{completed}✓</span>}
            {failed    > 0 && <span style={{ color: "#e04040" }}>{failed}✗</span>}
          </div>
        )}

        <button className="wfPanelClose" onClick={onClose}>✕</button>
      </div>

      {/* Node list (compact, above graph) */}
      {run && nodes.length > 0 && (
        <div className="wfNodeList">
          {nodes.map((node) => {
            const state = nodeStates[node.node_id];
            const status = state?.status ?? "pending";
            const isActive = node.node_id === run.current_node_id;
            const dotColor = NODE_STATUS_DOT[status] ?? "#1a3352";
            return (
              <button
                key={node.node_id}
                className={`wfNodeItem${isActive ? " wfNodeItem--active" : ""}${selectedNodeId === node.node_id ? " wfNodeItem--selected" : ""}`}
                onClick={() => setSelectedNodeId((id) => id === node.node_id ? null : node.node_id)}
              >
                <span className="wfNodeDot" style={{ background: dotColor, boxShadow: isActive ? `0 0 6px ${dotColor}` : "none" }} />
                <span className="wfNodeLabel">{node.label}</span>
                <span className="wfNodeStatus">{status}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* React Flow graph — needs agenticIntelligence scope for graph.css */}
      <div className="wfGraphBody agenticIntelligence">
        <WorkflowGraph
          run={run}
          selectedNodeId={selectedNodeId}
          edgePayloads={{}}
          events={events}
          onSelectNode={setSelectedNodeId}
          onSelectEdge={() => {}}
          onRestartFromNode={null}
        />
      </div>
    </div>
  );
}
