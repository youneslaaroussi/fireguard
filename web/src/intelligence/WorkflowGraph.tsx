import { EdgeEvent, Graph as G6Graph, NodeEvent, type GraphOptions } from "@antv/g6";
import type { IElementEvent } from "@antv/g6";
import { useEffect, useMemo, useRef } from "react";
import type { EdgePayload, StreamEvent, WorkflowRun } from "./types";
import { buildGraphModel, buildGraphSignature } from "./graph/build";
import type { FlowEdgeData, FlowNodeData } from "./graph/types";
import { STATUS_TEXT } from "./graph/constants";
import "./styles/graph.css";

interface WorkflowGraphProps {
  run: WorkflowRun | null;
  selectedNodeId: string | null;
  edgePayloads: Record<string, EdgePayload>;
  events: StreamEvent[];
  onSelectNode: (nodeId: string) => void;
  onSelectEdge: (edgeId: string) => void;
  onRestartFromNode: ((nodeId: string) => void) | null;
}

type G6NodeData = {
  label: string;
  status: string;
  accentColor: string;
  compact: boolean;
  platformBadge: string | null;
  canRestart: boolean;
};

type G6EdgeData = {
  strokeColor: string;
  clickable: boolean;
  hasPayload: boolean;
  animated: boolean;
};

export function WorkflowGraph({
  run,
  selectedNodeId,
  edgePayloads,
  events,
  onSelectNode,
  onSelectEdge,
  onRestartFromNode,
}: WorkflowGraphProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<G6Graph | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const onSelectNodeRef = useRef(onSelectNode);
  const onSelectEdgeRef = useRef(onSelectEdge);
  const onRestartFromNodeRef = useRef(onRestartFromNode);

  useEffect(() => {
    onSelectNodeRef.current = onSelectNode;
  }, [onSelectNode]);

  useEffect(() => {
    onSelectEdgeRef.current = onSelectEdge;
  }, [onSelectEdge]);

  useEffect(() => {
    onRestartFromNodeRef.current = onRestartFromNode;
  }, [onRestartFromNode]);

  const graphModel = useMemo(() => {
    if (run === null) return null;
    return buildGraphModel(run, selectedNodeId, edgePayloads, events, onSelectEdge, onRestartFromNode);
  }, [run, selectedNodeId, edgePayloads, events, onSelectEdge, onRestartFromNode]);

  const sig = buildGraphSignature(run, selectedNodeId, edgePayloads, events);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null || run === null) return;
    const graph = new G6Graph({
      container,
      ...baseG6Options(),
    });

    graph.on(NodeEvent.CLICK, (event) => {
      const pointerEvent = event as IElementEvent;
      const id = elementId(pointerEvent.target);
      if (id !== null) onSelectNodeRef.current(id);
    });

    graph.on(NodeEvent.DBLCLICK, (event) => {
      const pointerEvent = event as IElementEvent;
      const id = elementId(pointerEvent.target);
      if (id === null) return;
      const node = graph.getNodeData(id);
      const canRestart = Boolean((node.data as G6NodeData | undefined)?.canRestart);
      if (canRestart) onRestartFromNodeRef.current?.(id);
    });

    graph.on(EdgeEvent.CLICK, (event) => {
      const pointerEvent = event as IElementEvent;
      const id = elementId(pointerEvent.target);
      if (id === null) return;
      const edge = graph.getEdgeData(id);
      const data = edge.data as G6EdgeData | undefined;
      if (data?.clickable || data?.hasPayload) onSelectEdgeRef.current(id);
    });

    const resizeObserver = new ResizeObserver(() => graph.resize());
    resizeObserver.observe(container);
    resizeObserverRef.current = resizeObserver;
    graphRef.current = graph;

    return () => {
      resizeObserver.disconnect();
      graph.destroy();
      if (graphRef.current === graph) graphRef.current = null;
      if (resizeObserverRef.current === resizeObserver) resizeObserverRef.current = null;
    };
  }, [run?.run_id]);

  useEffect(() => {
    const graph = graphRef.current;
    if (graph === null || graphModel === null) return;
    const next = toG6Data(graphModel, selectedNodeId);
    graph.setData(next);
    graph.setLayout(graphLayout());
    void graph.render();
  }, [sig, graphModel, selectedNodeId]);

  if (run === null) {
    return <div className="workflow-graph empty">Open or start a session to see the workflow.</div>;
  }

  return (
    <div className="workflow-graph workflow-graph--g6">
      <div ref={containerRef} className="g6-canvas" />
      {graphModel !== null && (
        <div className="g6-count">
          {graphModel.nodes.length} nodes · {graphModel.edges.length} edges
        </div>
      )}
      <div className="g6-hint">Click nodes for details · Click highlighted edges for payloads</div>
    </div>
  );
}

function baseG6Options(): GraphOptions {
  return {
    animation: false,
    data: { nodes: [], edges: [] },
    layout: graphLayout(),
    node: { type: "rect" },
    edge: {
      type: "cubic-horizontal",
      style: {
        cursor: "pointer",
        label: false,
      },
    },
    behaviors: [
      "drag-canvas",
      "zoom-canvas",
      "drag-element",
      "hover-activate",
      {
        type: "click-select",
        degree: 1,
        state: "selected",
      },
    ],
    plugins: [
      {
        type: "background",
        key: "background",
        background: "#07111d",
      },
      {
        type: "grid-line",
        key: "grid-line",
        size: 24,
        stroke: "rgba(84, 124, 172, 0.13)",
      },
      {
        type: "minimap",
        key: "minimap",
        size: [120, 78],
        position: "right-bottom",
        padding: 10,
        className: "g6-minimap",
        maskStyle: {
          background: "rgba(15, 23, 42, 0.42)",
          border: "1px solid rgba(96, 165, 250, 0.48)",
        },
        containerStyle: {
          background: "#081827",
          border: "1px solid #1e3a5f",
          borderRadius: "8px",
          overflow: "hidden",
        },
      },
    ],
    transforms: ["process-parallel-edges"],
  };
}

function toG6Data(
  graphModel: ReturnType<typeof buildGraphModel>,
  selectedNodeId: string | null,
): NonNullable<GraphOptions["data"]> {
  return {
    nodes: graphModel.nodes.map((node) => {
        const data = node.data as FlowNodeData;
        const status = String(data.status);
        const compact = Boolean(data.compact);
        const width = compact ? 164 : 190;
        const height = compact ? 58 : 72;
        return {
          id: node.id,
          data: {
            label: data.label,
            status,
            accentColor: data.accentColor,
            compact,
            platformBadge: data.platformBadge ?? null,
            canRestart: data.onRestart !== null,
          } satisfies G6NodeData,
          style: {
            size: [width, height],
            radius: compact ? 9 : 12,
            fill: nodeFill(status, compact),
            stroke: selectedNodeId === node.id ? "#e0f2fe" : data.accentColor,
            lineWidth: selectedNodeId === node.id ? 2.8 : 1.4,
            shadowColor: status === "running" ? data.accentColor : "rgba(0,0,0,0.45)",
            shadowBlur: status === "running" ? 24 : 14,
            shadowOffsetY: 4,
            halo: status === "running" || selectedNodeId === node.id,
            haloStroke: data.accentColor,
            haloLineWidth: status === "running" ? 16 : 10,
            haloStrokeOpacity: status === "running" ? 0.18 : 0.14,
            labelText: data.label,
            labelFill: "#e5edf7",
            labelFontSize: compact ? 10 : 12,
            labelFontWeight: 700,
            labelPlacement: "center",
            labelTextBaseline: "middle",
            labelMaxWidth: width - 26,
            labelWordWrap: true,
            badge: true,
            badges: [
              {
                text: status.toUpperCase(),
                placement: "bottom",
                fill: "#06111d",
                stroke: statusColor(status),
                color: STATUS_TEXT[status] ?? "#94a3b8",
                fontSize: 8,
                padding: [1, 5],
              },
              ...(data.platformBadge
                ? [{
                    text: data.platformBadge,
                    placement: "right-top" as const,
                    fill: "#081827",
                    stroke: data.accentColor,
                    color: "#a7f3d0",
                    fontSize: 8,
                    padding: [1, 5],
                  }]
                : []),
            ],
            ports: [
              { key: "left", placement: [0, 0.5], r: 3, fill: data.accentColor, stroke: "#07101c" },
              { key: "right", placement: [1, 0.5], r: 3, fill: data.accentColor, stroke: "#07101c" },
            ],
          },
        };
      }),
    edges: graphModel.edges.map((edge) => {
        const data = edge.data as FlowEdgeData;
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          data: {
            strokeColor: data.strokeColor,
            clickable: Boolean(data.clickable),
            hasPayload: Boolean(data.hasPayload),
            animated: Boolean(edge.animated),
          } satisfies G6EdgeData,
          style: {
            stroke: data.strokeColor,
            lineWidth: data.hasPayload ? 2.4 : 1.5,
            opacity: data.hasPayload ? 0.95 : 0.58,
            lineDash: edge.style?.strokeDasharray ? [6, 5] : undefined,
            endArrow: true,
            endArrowFill: data.strokeColor,
            endArrowStroke: data.strokeColor,
            halo: data.hasPayload || edge.animated,
            haloStroke: data.strokeColor,
            haloLineWidth: edge.animated ? 14 : 8,
            haloStrokeOpacity: edge.animated ? 0.18 : 0.12,
            badge: data.hasPayload,
            badgeText: data.hasPayload ? "payload" : "",
            badgeFill: "#06111d",
            badgeStroke: data.strokeColor,
            badgeColor: "#dbeafe",
            badgeFontSize: 8,
          },
        };
    }),
  };
}

function graphLayout(): NonNullable<GraphOptions["layout"]> {
  return {
    type: "dagre",
    rankdir: "LR",
    align: "UL",
    nodesep: 28,
    ranksep: 74,
    ranker: "network-simplex",
    controlPoints: true,
    nodeSize: (node) => {
      const data = node.data as G6NodeData | undefined;
      return data?.compact ? [164, 58] : [190, 72];
    },
  };
}

function nodeFill(status: string, compact: boolean) {
  if (status === "completed") return compact ? "#0e221d" : "#10231e";
  if (status === "running") return "#10213a";
  if (status === "failed" || status === "rejected") return "#2a1216";
  if (status === "waiting") return "#2a2111";
  return compact ? "#101824" : "#111c2b";
}

function statusColor(status: string) {
  if (status === "completed") return "#10b981";
  if (status === "running") return "#60a5fa";
  if (status === "failed" || status === "rejected") return "#f87171";
  if (status === "waiting") return "#f59e0b";
  return "#475569";
}

function elementId(target: unknown): string | null {
  if (target === null || typeof target !== "object") return null;
  const id = (target as { id?: unknown }).id;
  return typeof id === "string" ? id : null;
}
