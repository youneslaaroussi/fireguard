import { EdgeEvent, Graph as G6Graph, NodeEvent, type GraphOptions } from "@antv/g6";
import type { IElementEvent } from "@antv/g6";
import { useEffect, useMemo, useRef } from "react";
import type { EdgePayload, StreamEvent, WorkflowRun } from "./types";
import { buildGraphModel, buildGraphSignature } from "./graph/build";
import type { FlowEdgeData, FlowNodeData } from "./graph/types";
import { STATUS_TEXT } from "./graph/constants";
import "./styles/graph.css";
import { LOGOS } from "./logos";

export type ClickedNodeInfo = { id: string } & G6NodeData;

interface WorkflowGraphProps {
  run: WorkflowRun | null;
  selectedNodeId: string | null;
  edgePayloads: Record<string, EdgePayload>;
  events: StreamEvent[];
  onSelectNode: (nodeId: string) => void;
  onSelectGraphNode?: (node: ClickedNodeInfo) => void;
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

const NOOP_SELECT_EDGE = () => undefined;
const NOOP_RESTART_NODE = () => undefined;

function LegendRow({ glyph, dot, color, label }: { glyph?: string; dot?: boolean; color: string; label: string }) {
  return (
    <div className="g6-legend-row">
      <span className="g6-legend-icon" style={{ color }}>
        {dot ? "●" : glyph}
      </span>
      <span className="g6-legend-label">{label}</span>
    </div>
  );
}

export function WorkflowGraph({
  run,
  selectedNodeId,
  edgePayloads,
  events,
  onSelectNode,
  onSelectGraphNode,
  onSelectEdge,
  onRestartFromNode,
}: WorkflowGraphProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<G6Graph | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const onSelectNodeRef = useRef(onSelectNode);
  const onSelectGraphNodeRef = useRef(onSelectGraphNode);
  const onSelectEdgeRef = useRef(onSelectEdge);
  const onRestartFromNodeRef = useRef(onRestartFromNode);
  const selectedNodeIdRef = useRef(selectedNodeId);
  const previousSelectedNodeIdRef = useRef<string | null>(null);

  useEffect(() => { onSelectNodeRef.current = onSelectNode; }, [onSelectNode]);
  useEffect(() => { onSelectGraphNodeRef.current = onSelectGraphNode; }, [onSelectGraphNode]);
  useEffect(() => { onSelectEdgeRef.current = onSelectEdge; }, [onSelectEdge]);

  useEffect(() => {
    onRestartFromNodeRef.current = onRestartFromNode;
  }, [onRestartFromNode]);

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
  }, [selectedNodeId]);

  const canRestartFromNode = onRestartFromNode !== null;
  const graphModel = useMemo(() => {
    if (run === null) return null;
    return buildGraphModel(
      run,
      null,
      edgePayloads,
      events,
      NOOP_SELECT_EDGE,
      canRestartFromNode ? NOOP_RESTART_NODE : null,
    );
  }, [run, edgePayloads, events, canRestartFromNode]);

  const sig = buildGraphSignature(run, edgePayloads, events);

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
      if (id === null) return;
      onSelectNodeRef.current(id);
      const nodeData = graph.getNodeData(id)?.data as G6NodeData | undefined;
      if (nodeData && onSelectGraphNodeRef.current) {
        onSelectGraphNodeRef.current({ id, ...nodeData });
      }
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
    const next = toG6Data(graphModel, selectedNodeIdRef.current);
    graph.setData(next);
    void graph.render().then(() => {
      previousSelectedNodeIdRef.current = selectedNodeIdRef.current;
    });
  }, [sig, graphModel]);

  useEffect(() => {
    const graph = graphRef.current;
    if (graph === null) return;
    const previous = previousSelectedNodeIdRef.current;
    if (previous === selectedNodeId) return;

    const patches = [previous, selectedNodeId]
      .filter((id): id is string => id !== null)
      .map((id) => selectedNodePatch(graph, id, id === selectedNodeId))
      .filter((patch): patch is NonNullable<ReturnType<typeof selectedNodePatch>> => patch !== null);

    previousSelectedNodeIdRef.current = selectedNodeId;
    if (patches.length === 0) return;
    graph.updateNodeData(patches);
    void graph.draw();
  }, [selectedNodeId]);

  if (run === null) {
    return <div className="workflow-graph empty">Open or start a session to see the workflow.</div>;
  }

  return (
    <div className="workflow-graph workflow-graph--g6">
      <div ref={containerRef} className="g6-canvas" />
      <div className="g6-gemini-watermark">
        <img src={LOGOS.gemini.src} alt="Gemini" className="g6-gemini-logo" />
        <span className="g6-gemini-label">GEMINI</span>
      </div>
      {graphModel !== null && (
        <div className="g6-count">
          {graphModel.nodes.length} nodes · {graphModel.edges.length} edges
        </div>
      )}
      <div className="g6-hint">Hover for details · Scroll to zoom</div>
      <div className="g6-legend">
        <div className="g6-legend-title">LEGEND</div>
        <div className="g6-legend-section">NODES</div>
        <LegendRow glyph="▶" color="#6366f1" label="Trigger" />
        <LegendRow glyph="◈" color="#8b5cf6" label="Data Checks" />
        <LegendRow glyph="✎" color="#f59e0b" label="Evac Brief" />
        <LegendRow glyph="✔" color="#10b981" label="Response" />
        <LegendRow glyph="⬡" color="#8b5cf6" label="Evac Zone" />
        <LegendRow glyph="⌂" color="#10b981" label="Shelter" />
        <LegendRow glyph="⚠" color="#f59e0b" label="Road Event" />
        <LegendRow glyph="✦" color="#ef4444" label="Fire Hotspot" />
        <LegendRow glyph="→" color="#3b82f6" label="Route" />
        <div className="g6-legend-section">STATUS</div>
        <LegendRow dot color="#60a5fa" label="Running" />
        <LegendRow dot color="#34d399" label="Done" />
        <LegendRow dot color="#f87171" label="Failed" />
        <LegendRow dot color="#374151" label="Pending" />
      </div>
    </div>
  );
}

function baseG6Options(): GraphOptions {
  return {
    animation: false,
    data: { nodes: [], edges: [] },
    autoFit: "view",
    devicePixelRatio: Math.min(globalThis.devicePixelRatio ?? 1, 1.5),
    padding: 32,
    node: { type: "circle" },
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
      {
        type: "optimize-viewport-transform",
        debounce: 120,
        shapes: {
          node: ["key"],
          edge: ["key"],
        },
      },
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
      {
        type: "tooltip",
        key: "tooltip",
        trigger: "pointerenter",
        enterable: false,
        getContent: (_e: unknown, items: unknown[]) => {
          const item = items[0] as { data?: G6NodeData } | undefined;
          const d = item?.data;
          if (!d) return document.createElement("div");
          return buildTooltipEl(d);
        },
        style: {
          background: "transparent",
          border: "none",
          padding: "0",
          boxShadow: "none",
          pointerEvents: "none",
          zIndex: 999,
        },
      },
    ],
    transforms: ["process-parallel-edges"],
  };
}

function selectedNodePatch(graph: G6Graph, id: string, selected: boolean) {
  const node = graph.getNodeData(id);
  if (node === undefined) return null;
  const data = node.data as G6NodeData | undefined;
  const status = data?.status ?? "pending";
  const accentColor = data?.accentColor ?? "#6366f1";
  return {
    id,
    style: {
      stroke: selected ? "#e0f2fe" : accentColor,
      lineWidth: selected ? 2.5 : 1.2,
      halo: status === "running" || selected,
      haloLineWidth: status === "running" ? 14 : 8,
      haloStrokeOpacity: status === "running" ? 0.22 : selected ? 0.12 : 0,
    },
  };
}

// Map node/tool types to a single emoji/symbol shown inside the circle
function nodeGlyph(data: FlowNodeData): string {
  const badge = data.platformBadge as string | null | undefined;
  if (badge === "elastic")    return "⬡";
  if (badge === "nasa")       return "✦";
  if (badge === "googlemaps") return "◎";
  if (badge === "zone")       return "⬡";
  if (badge === "shelter_open" || badge === "open") return "⌂";
  if (badge === "shelter_closed" || badge === "closed") return "⌂";
  if (badge === "road")       return "⚠";
  if (badge === "hotspot")    return "✦";
  if (badge === "route")      return "→";
  if (badge === "weather")    return "~";
  // primary node by id
  const id = data.label.toLowerCase();
  if (id.includes("trigger"))   return "▶";
  if (id.includes("data") || id.includes("research")) return "◈";
  if (id.includes("evacuation") || id.includes("brief")) return "✎";
  if (id.includes("formatter") || id.includes("style")) return "✧";
  if (id.includes("response") || id.includes("terminal")) return "✔";
  if (id.includes("router") || id.includes("chat")) return "⇌";
  if (id.includes("route")) return "→";
  if (id.includes("zone"))    return "⬡";
  if (id.includes("shelter")) return "⌂";
  if (id.includes("road"))    return "⚠";
  if (id.includes("detect") || id.includes("fire")) return "✦";
  if (id.includes("annotate") || id.includes("map")) return "◎";
  if (id.includes("search"))  return "◈";
  return "●";
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
      const r = compact ? Math.round(13 + (importance - 45) * 0.2) : 22;
      const diameter = r * 2;
      const glyph = nodeGlyph(data);
      const [x, y] = positions.get(node.id) ?? [0, 0];
      const selected = selectedNodeId === node.id;
      const running = status === "running";
      const done = status === "completed";
      const failed = status === "failed" || status === "rejected";
      const shortLabel = compact
        ? String(data.label).slice(0, 18)
        : String(data.label).split(" ").slice(0, 2).join(" ");
      const glyphColor = done ? data.accentColor : running ? "#ffffff" : failed ? "#fca5a5" : "#8aa4be";
      const labelColor = done ? "#6ee7b7" : running ? "#93c5fd" : failed ? "#fca5a5" : "#5a7a8e";
      return {
        id: node.id,
        data: {
          label: data.label,
          summary: typeof data.summary === "string" ? data.summary : "",
          status,
          accentColor: data.accentColor,
          compact,
          importance,
          cluster: typeof data.cluster === "string" ? data.cluster : "workflow",
          layer: typeof data.layer === "string" ? data.layer : "workflow",
          platformBadge: data.platformBadge ?? null,
          canRestart: data.onRestart !== null,
        } satisfies G6NodeData,
        style: {
          x,
          y,
          size: diameter,
          fill: nodeFill(status, compact),
          stroke: selected ? "#e0f2fe" : data.accentColor,
          lineWidth: selected ? 3 : 2,
          shadowColor: running ? data.accentColor : done ? data.accentColor : "rgba(0,0,0,0.6)",
          shadowBlur: running ? 28 : done ? 10 : 8,
          shadowOffsetY: running ? 0 : 3,
          halo: running || selected,
          haloStroke: data.accentColor,
          haloLineWidth: running ? 18 : 12,
          haloStrokeOpacity: running ? 0.3 : 0.15,
          // glyph rendered by G6's icon system (center of circle)
          iconText: glyph,
          iconFill: glyphColor,
          iconFontSize: compact ? Math.round(r * 0.75) : 15,
          iconFontWeight: "bold",
          // name rendered below the circle
          labelText: shortLabel,
          labelFill: labelColor,
          labelFontSize: compact ? 8 : 10,
          labelFontWeight: 600,
          labelPlacement: "bottom",
          labelOffsetY: 3,
          badge: false,
          ports: [
            { key: "top",    placement: [0.5, 0], r: 3, fill: data.accentColor, stroke: "#07101c" },
            { key: "bottom", placement: [0.5, 1], r: 3, fill: data.accentColor, stroke: "#07101c" },
            { key: "left",   placement: [0, 0.5], r: 3, fill: data.accentColor, stroke: "#07101c" },
            { key: "right",  placement: [1, 0.5], r: 3, fill: data.accentColor, stroke: "#07101c" },
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
          lineWidth: data.hasPayload ? 2 : 1,
          opacity: data.hasPayload ? 0.9 : 0.45,
          lineDash: edge.style?.strokeDasharray ? [4, 4] : undefined,
          endArrow: true,
          endArrowFill: data.strokeColor,
          endArrowStroke: data.strokeColor,
          halo: Boolean(edge.animated),
          haloStroke: data.strokeColor,
          haloLineWidth: 10,
          haloStrokeOpacity: 0.15,
          badge: false,
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

function nodeFill(status: string, compact: boolean) {
  if (status === "completed") return compact ? "#0d2b22" : "#0f2820";
  if (status === "running") return "#0d1f3a";
  if (status === "failed" || status === "rejected") return "#2e1118";
  if (status === "waiting") return "#2c2010";
  return compact ? "#111d2c" : "#131f30";
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

function buildTooltipEl(d: Partial<G6NodeData>): HTMLElement {
  const STATUS_LABEL: Record<string, string> = {
    running: "RUNNING", completed: "DONE", failed: "FAILED",
    rejected: "REJECTED", waiting: "WAITING", pending: "PENDING", skipped: "SKIPPED",
  };
  const STATUS_COLOR: Record<string, string> = {
    running: "#60a5fa", completed: "#34d399", failed: "#f87171",
    rejected: "#f87171", waiting: "#fbbf24", pending: "#4b6278", skipped: "#4b6278",
  };

  const status = typeof d.status === "string" && d.status.length > 0 ? d.status : "pending";
  const label = typeof d.label === "string" && d.label.length > 0 ? d.label : "Node";
  const summary = typeof d.summary === "string" ? d.summary : "";
  const accent = d.accentColor ?? "#6366f1";
  const sc = STATUS_COLOR[status] ?? "#6b7280";
  const statusLabel = STATUS_LABEL[status] ?? status.toUpperCase();
  const badge = typeof d.platformBadge === "string" && d.platformBadge.length > 0 ? d.platformBadge : null;

  // outer wrapper
  const el = document.createElement("div");
  el.style.cssText = [
    "background:rgba(8,14,24,0.96)",
    "border:1px solid rgba(255,255,255,0.07)",
    "border-radius:8px",
    "overflow:hidden",
    "min-width:168px",
    "max-width:248px",
    `box-shadow:0 0 0 1px ${accent}28,0 12px 40px rgba(0,0,0,0.8),0 0 24px ${accent}18`,
    "font-family:'Courier New',monospace",
    "pointer-events:none",
  ].join(";");

  // top accent strip with gradient
  const strip = document.createElement("div");
  strip.style.cssText = `height:3px;background:linear-gradient(90deg,${accent},${accent}66,transparent)`;
  el.append(strip);

  // body
  const body = document.createElement("div");
  body.style.cssText = "padding:9px 12px 10px";
  el.append(body);

  // label + status chip row
  const header = document.createElement("div");
  header.style.cssText = "display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:5px";

  const labelEl = document.createElement("span");
  labelEl.style.cssText = "font-size:12px;font-weight:700;color:#ddeaf8;line-height:1.3;letter-spacing:0.02em";
  labelEl.textContent = label;

  const chip = document.createElement("span");
  chip.style.cssText = `flex-shrink:0;font-size:7px;font-weight:700;letter-spacing:0.16em;color:${sc};background:${sc}15;border:1px solid ${sc}35;padding:2px 5px;border-radius:99px;margin-top:2px`;
  chip.textContent = statusLabel;

  header.append(labelEl, chip);
  body.append(header);

  // summary
  if (summary) {
    const sumEl = document.createElement("div");
    sumEl.style.cssText = "font-size:10px;color:#4a6880;line-height:1.5;margin-bottom:4px";
    sumEl.textContent = summary;
    body.append(sumEl);
  }

  // platform badge row
  if (badge) {
    const row = document.createElement("div");
    row.style.cssText = `margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.05);display:flex;align-items:center;gap:5px`;
    const glow = document.createElement("span");
    glow.style.cssText = `width:6px;height:6px;border-radius:50%;background:${accent};box-shadow:0 0 6px ${accent};flex-shrink:0;display:inline-block`;
    const badgeEl = document.createElement("span");
    badgeEl.style.cssText = `font-size:9px;color:${accent}cc;letter-spacing:0.12em;font-weight:600;text-transform:uppercase`;
    badgeEl.textContent = badge;
    row.append(glow, badgeEl);
    body.append(row);
  }

  return el;
}
