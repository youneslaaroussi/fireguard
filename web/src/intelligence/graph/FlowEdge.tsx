import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type Edge,
  type EdgeProps,
} from "@xyflow/react";
import { FileText } from "lucide-react";
import type { FlowEdgeData } from "./types";

export function FlowEdge(props: EdgeProps<Edge<FlowEdgeData>>) {
  const { sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition } = props;
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
  });

  const data = props.data;
  const stroke = data?.strokeColor ?? "#1e3a5f";

  return (
    <>
      <BaseEdge
        path={edgePath}
        markerEnd={props.markerEnd}
        style={{ ...props.style, stroke, strokeWidth: props.animated ? 2 : 1.5 }}
      />
      {data?.clickable === true && (
        <EdgeLabelRenderer>
          <button
            className={`gflow-edge-btn${data.hasPayload ? " ready" : ""}`}
            style={{ transform: `translate(-50%,-50%) translate(${labelX}px,${labelY}px)` }}
            type="button"
            title={data.title}
            onClick={(e) => { e.stopPropagation(); data.onSelectEdge(props.id); }}
          >
            <FileText size={13} strokeWidth={2.2} aria-hidden />
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
