import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { RotateCcw } from "lucide-react";
import { STATUS_BORDER, STATUS_TEXT } from "./constants";
import type { FlowNodeData } from "./types";

const HANDLE_STYLE = {
  opacity: 0,
  width: 4,
  height: 4,
  background: "transparent",
  border: 0,
} as const;

export function FlowNode({ data }: NodeProps<Node<FlowNodeData>>) {
  const { label, status, accentColor, NodeIcon, selected, compact, onRestart, platformBadge } = data;
  const borderColor = selected ? "#818cf8" : (STATUS_BORDER[status] ?? "#1e2d3d");
  const textColor = STATUS_TEXT[status] ?? "#4b6278";
  const dotColor = STATUS_BORDER[status] ?? "#334155";
  const isRunning = status === "running";
  const iconSize = compact ? 28 : 38;
  const dim = status === "pending";

  return (
    <div
      className={`gflow-node${compact ? " compact" : ""}${isRunning ? " is-running" : ""}`}
      style={{ borderColor }}
    >
      <Handle type="target" position={Position.Left} style={HANDLE_STYLE} />

      <div
        className="gflow-node-icon"
        style={{
          width: iconSize,
          height: iconSize,
          minWidth: iconSize,
          background: accentColor,
          opacity: dim ? 0.4 : 1,
          borderRadius: compact ? 6 : 8,
        }}
      >
        <NodeIcon size={compact ? 13 : 18} color="#fff" strokeWidth={2.3} aria-hidden />
      </div>

      <div className="gflow-node-text" style={{ opacity: dim ? 0.6 : 1 }}>
        <span className="gflow-node-label">{label}</span>
        <span className="gflow-node-status-row" style={{ color: textColor }}>
          <span
            className={`gflow-status-dot${isRunning ? " is-running" : ""}`}
            style={{ background: dotColor }}
          />
          {status}
        </span>
        {platformBadge != null && (
          <span
            className="gflow-platform-badge"
            style={{ background: `${accentColor}22`, borderColor: `${accentColor}55`, color: accentColor }}
          >
            {platformBadge}
          </span>
        )}
      </div>

      {onRestart !== null && (
        <button
          className="gflow-node-rerun"
          title="Restart from this node"
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onRestart();
          }}
        >
          <RotateCcw size={11} strokeWidth={2.5} />
        </button>
      )}

      <Handle type="source" position={Position.Right} style={HANDLE_STYLE} />
    </div>
  );
}
