import { EdgeEvent, Graph as G6Graph, NodeEvent, type GraphOptions } from "@antv/g6";
import type { IElementEvent } from "@antv/g6";
import { useEffect, useMemo, useRef } from "react";
import type { EdgePayload, StreamEvent, WorkflowRun } from "./types";
import { buildGraphModel, buildGraphSignature } from "./graph/build";
import type { FlowEdgeData, FlowNodeData } from "./graph/types";
import { STATUS_TEXT } from "./graph/constants";
import { LOGOS } from "./logos";
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
  summary: string;
  status: string;
  accentColor: string;
  compact: boolean;
  importance: number;
  cluster: string;
  layer: string;
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
    autoFit: "view",
    padding: 48,
    node: { type: "rect" },
    edge: {
      type: "line",
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
  const positions = networkPositions(graphModel);
  return {
    nodes: graphModel.nodes.map((node) => {
        const data = node.data as FlowNodeData;
        const status = String(data.status);
        const compact = Boolean(data.compact);
        const importance = typeof data.importance === "number" ? data.importance : compact ? 62 : 78;
        const cluster = typeof data.cluster === "string" ? data.cluster : compact ? node.id : "workflow";
        const layer = typeof data.layer === "string" ? data.layer : compact ? "entity" : "workflow";
        const summary = typeof data.summary === "string" ? data.summary : "";
        const [width, height] = nodeSize(compact, summary, importance);
        const labelText = summary ? `${data.label}\n${summary}` : data.label;
        const [x, y] = positions.get(node.id) ?? [0, 0];
        return {
          id: node.id,
          data: {
            label: data.label,
            summary,
            status,
            accentColor: data.accentColor,
            compact,
            importance,
            cluster,
            layer,
            platformBadge: data.platformBadge ?? null,
            canRestart: data.onRestart !== null,
          } satisfies G6NodeData,
          style: {
            x,
            y,
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
            labelText,
            labelFill: "#e5edf7",
            labelFontSize: compact ? (importance >= 78 ? 10 : 9) : 12,
            labelFontWeight: 700,
            labelLineHeight: compact ? (importance >= 78 ? 14 : 13) : 16,
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
                    text: (LOGOS[data.platformBadge]?.label ?? data.platformBadge).toUpperCase(),
                    placement: "right-top" as const,
                    fill: "#06111d",
                    stroke: LOGOS[data.platformBadge]?.color ?? data.accentColor,
                    color: LOGOS[data.platformBadge]?.color ?? "#a7f3d0",
                    fontSize: 7,
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

function networkPositions(graphModel: ReturnType<typeof buildGraphModel>): Map<string, [number, number]> {
  const positions = new Map<string, [number, number]>();
  const nodeData = new Map(graphModel.nodes.map((node) => [node.id, node.data as FlowNodeData]));
  const children = new Map<string, string[]>();
  for (const edge of graphModel.edges) {
    const list = children.get(edge.source) ?? [];
    list.push(edge.target);
    children.set(edge.source, list);
  }

  const workflowOrder = ["human_trigger", "research_agent", "response_agent"];
  workflowOrder.forEach((id, index) => {
    if (nodeData.has(id)) positions.set(id, [-520 + index * 520, 0]);
  });

  const researchChildren = (children.get("research_agent") ?? [])
    .filter((id) => {
      const layer = nodeData.get(id)?.layer;
      return layer === "tool" || layer === "subagent";
    });
  placeWideGrid(researchChildren, positions, 760, 520, 0, -360);

  for (const id of graphModel.nodes.map((node) => node.id)) {
    if (positions.has(id)) continue;
    const parent = graphModel.edges.find((edge) => edge.target === id)?.source;
    if (parent === undefined) continue;
    ensureChildrenPlaced(parent, children, nodeData, positions, 0);
  }

  for (const node of graphModel.nodes) {
    if (!positions.has(node.id)) positions.set(node.id, [0, 0]);
  }
  return positions;
}

function placeWideGrid(
  ids: string[],
  positions: Map<string, [number, number]>,
  gapX: number,
  gapY: number,
  centerX: number,
  centerY: number,
) {
  if (ids.length === 0) return;
  const cols = Math.max(1, Math.ceil(Math.sqrt(ids.length * 2.2)));
  const rows = Math.ceil(ids.length / cols);
  ids.forEach((id, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    positions.set(id, [
      centerX + (col - (cols - 1) / 2) * gapX,
      centerY + (row - (rows - 1) / 2) * gapY,
    ]);
  });
}

function ensureChildrenPlaced(
  parentId: string,
  children: Map<string, string[]>,
  nodeData: Map<string, FlowNodeData>,
  positions: Map<string, [number, number]>,
  depth: number,
) {
  const parentPos = positions.get(parentId);
  if (parentPos === undefined) return;
  const ids = (children.get(parentId) ?? []).filter((id) => !positions.has(id));
  if (ids.length === 0) return;
  const entityIds = ids.filter((id) => nodeData.get(id)?.layer === "entity");
  const otherIds = ids.filter((id) => nodeData.get(id)?.layer !== "entity");
  placeRing(entityIds, parentPos, positions, depth);
  placeRing(otherIds, parentPos, positions, depth);
  for (const id of ids) ensureChildrenPlaced(id, children, nodeData, positions, depth + 1);
}

function placeRing(
  ids: string[],
  [cx, cy]: [number, number],
  positions: Map<string, [number, number]>,
  depth: number,
) {
  const count = ids.length;
  if (count === 0) return;
  const base = depth === 0 ? 210 : 120;
  const step = depth === 0 ? 58 : 44;
  ids.forEach((id, index) => {
    const angle = index * 2.399963229728653;
    const radius = base + Math.sqrt(index) * step;
    const xScale = depth === 0 ? 1.28 : 1.05;
    const yScale = depth === 0 ? 0.62 : 0.82;
    positions.set(id, [
      cx + Math.cos(angle) * radius * xScale,
      cy + Math.sin(angle) * radius * yScale,
    ]);
  });
}

function nodeSize(compact: boolean, summary: string, importance: number): [number, number] {
  if (!compact) return [200, 74];
  if (importance >= 86) return [230, summary ? 90 : 70];
  if (importance >= 68) return [196, summary ? 76 : 62];
  if (importance >= 48) return [164, summary ? 64 : 54];
  return [132, summary ? 52 : 44];
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
