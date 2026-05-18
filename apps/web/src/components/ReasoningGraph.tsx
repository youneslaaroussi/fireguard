"use client";

import { useEffect, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Edge,
  Handle,
  MiniMap,
  Node,
  NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";

import type { AssessmentResult } from "@/lib/types";

// ─── node data ────────────────────────────────────────────────────────────────
type RKind =
  | "context"
  | "fire" | "zone-input" | "road"
  | "tool"
  | "decision"
  | "thought"
  | "zone-risk"
  | "planstep"
  | "rejected"
  | "gap"
  | "risk"
  | "fallback";

interface RNodeData extends Record<string, unknown> {
  kind: RKind;
  label: string;
  sublabel?: string;
  detail?: unknown;
  riskLevel?: string;
}
type RNode = Node<RNodeData>;

// ─── visual styles ────────────────────────────────────────────────────────────
const KIND_STYLE: Record<RKind, { border: string; bg: string; accent: string; badge: string }> = {
  context:    { border: "#2d72d2", bg: "#06101e", accent: "#8abbff", badge: "CTX" },
  fire:       { border: "#c85020", bg: "#130600", accent: "#ff7040", badge: "FIRE" },
  "zone-input":{ border: "#7c4dce", bg: "#0d0618", accent: "#c0a0ff", badge: "ZONE" },
  road:       { border: "#856f00", bg: "#0e0a00", accent: "#f2b824", badge: "ROAD" },
  tool:       { border: "#1e5c9e", bg: "#040e1a", accent: "#48aff0", badge: "TOOL" },
  decision:   { border: "#9d4dce", bg: "#0e0520", accent: "#d4a0ff", badge: "GEMINI" },
  thought:    { border: "#293742", bg: "#080d12", accent: "#5c7080", badge: "THINK" },
  "zone-risk":{ border: "#7a5800", bg: "#0e0900", accent: "#f2b824", badge: "RISK" },
  planstep:   { border: "#2a7a48", bg: "#020d06", accent: "#45d483", badge: "STEP" },
  rejected:   { border: "#6a2020", bg: "#100404", accent: "#d47070", badge: "REJ" },
  gap:        { border: "#5a4a00", bg: "#0c0900", accent: "#c0a060", badge: "GAP" },
  risk:       { border: "#6a2828", bg: "#0e0404", accent: "#c07070", badge: "RISK" },
  fallback:   { border: "#2a4a5a", bg: "#040a0e", accent: "#6090a8", badge: "FALLBACK" },
};

const RISK_BORDER: Record<string, string> = {
  CRITICAL: "#db3737", HIGH: "#c87328", MODERATE: "#856f00", LOW: "#2a7a48",
};

// ─── node component ───────────────────────────────────────────────────────────
function RNode({ data, selected }: NodeProps) {
  const d = data as RNodeData;
  let s = KIND_STYLE[d.kind] ?? KIND_STYLE.thought;
  if (d.kind === "zone-risk" && d.riskLevel) {
    s = { ...s, border: RISK_BORDER[d.riskLevel] ?? s.border, accent: RISK_BORDER[d.riskLevel] ?? s.accent };
  }

  const isThought = d.kind === "thought" || d.kind === "gap" || d.kind === "risk" || d.kind === "fallback";
  const isDecision = d.kind === "decision";

  return (
    <div
      style={{
        background: s.bg,
        border: `1px solid ${selected ? s.accent : s.border}`,
        borderLeft: isDecision ? `3px solid ${s.accent}` : `1px solid ${selected ? s.accent : s.border}`,
        boxShadow: selected
          ? `0 0 0 2px ${s.accent}55, 0 6px 24px rgba(0,0,0,0.8)`
          : isDecision
            ? `0 4px 24px rgba(0,0,0,0.6), 0 0 0 1px ${s.border}44`
            : "0 2px 8px rgba(0,0,0,0.5)",
        borderRadius: 3,
        padding: isThought ? "6px 10px" : "8px 12px",
        minWidth: isThought ? 120 : isDecision ? 160 : 138,
        maxWidth: isThought ? 200 : isDecision ? 210 : 182,
        cursor: "pointer",
        opacity: 1,
        transition: "border-color 0.12s, box-shadow 0.12s",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: s.accent, width: 5, height: 5, border: "none", opacity: 0.6 }} />

      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: isThought ? 2 : 3 }}>
        <span
          style={{
            display: "inline-block",
            padding: "1px 4px",
            background: `${s.accent}20`,
            border: `1px solid ${s.accent}40`,
            borderRadius: 2,
            color: s.accent,
            fontSize: 8,
            fontWeight: 800,
            letterSpacing: "0.08em",
            lineHeight: 1.4,
          }}
        >
          {s.badge}
        </span>
        </div>

      <div
        style={{
          color: isThought ? "#9daab5" : "#edf5ff",
          fontSize: isThought ? 10 : 12,
          fontWeight: isThought ? 400 : 700,
          lineHeight: 1.35,
          wordBreak: "break-word",
          fontStyle: isThought ? "italic" : "normal",
        }}
      >
        {d.label}
      </div>

      {d.sublabel ? (
        <div style={{ color: "#4a5c6a", fontSize: 9, marginTop: 3, lineHeight: 1.2 }}>{d.sublabel}</div>
      ) : null}

      <Handle type="source" position={Position.Right} style={{ background: s.accent, width: 5, height: 5, border: "none", opacity: 0.6 }} />
    </div>
  );
}

const NODE_TYPES = { rn: RNode };

// ─── edge factory ─────────────────────────────────────────────────────────────
function mkEdge(id: string, src: string, tgt: string, opts: { dashed?: boolean; dim?: boolean; color?: string } = {}): Edge {
  return {
    id, source: src, target: tgt, animated: false,
    style: {
      stroke: opts.color ?? (opts.dim ? "#1a2530" : "#1e3045"),
      strokeWidth: opts.dim ? 1 : 1.5,
      strokeDasharray: opts.dashed ? "5 4" : undefined,
    },
  };
}

// ─── layout helpers ───────────────────────────────────────────────────────────
function colY(count: number, i: number, centerY: number): number {
  const spacing = 96;
  return centerY - ((count - 1) * spacing) / 2 + i * spacing;
}

// ─── full rich graph ──────────────────────────────────────────────────────────
function buildRichGraph(assessment: AssessmentResult): { nodes: RNode[]; edges: Edge[] } {
  const nodes: RNode[] = [];
  const edges: Edge[] = [];

  // Extract decision data from trace
  const reasonTrace = (assessment.trace ?? []).find(
    (r: Record<string, unknown>) => r.step === "reason",
  );
  const reasonOut = (reasonTrace?.output ?? {}) as Record<string, unknown>;
  const decision = (reasonOut.decision ?? assessment.gemini_decision ?? {}) as Record<string, unknown>;
  const toolCalls: string[] = Array.isArray(reasonOut.tool_calls)
    ? (reasonOut.tool_calls as string[])
    : (assessment.gemini_tool_calls ?? []);

  const summary = String(decision.incident_summary ?? assessment.plan.summary ?? "");
  const dataGaps: string[] = Array.isArray(decision.data_gaps) ? (decision.data_gaps as string[]) : [];
  const risksIfWrong: string[] = Array.isArray(decision.risks_if_wrong)
    ? (decision.risks_if_wrong as string[])
    : (assessment.plan.risks_if_wrong ?? []);
  const fallback = String(decision.fallback_plan ?? assessment.plan.fallback_plan ?? "");

  const COL = [60, 280, 510, 740, 990, 1240, 1490];
  const CY = 220;

  // ── Col 0: Incident Context ──────────────────────────────────────────────
  nodes.push({
    id: "ctx", type: "rn",
    position: { x: COL[0], y: CY },
    data: {
      kind: "context",
      label: "Incident Context",
      sublabel: `${assessment.context.fires.length} fires · ${assessment.context.zones.length} zones · ${assessment.context.road_events.length} road events`,
      detail: { incident_id: assessment.incident_id, mode: assessment.context.mode },
    } as RNodeData,
  });

  // ── Col 1: Input Data (fires, zones, roads) ──────────────────────────────
  const inputs: Array<{ id: string; kind: RKind; label: string; sublabel: string; detail: unknown }> = [];

  assessment.context.fires.slice(0, 3).forEach((f, i) => {
    inputs.push({ id: `fi${i}`, kind: "fire", label: `Hotspot ${i + 1}`, sublabel: `FRP ${f.frp.toFixed(1)} MW · ${f.source}`, detail: f });
  });
  assessment.context.zones.forEach((z, i) => {
    inputs.push({ id: `zi${i}`, kind: "zone-input", label: z.name, sublabel: `Pop ${z.population} · Vuln ${z.vulnerable_count}`, detail: z });
  });
  assessment.context.road_events.slice(0, 2).forEach((r, i) => {
    inputs.push({ id: `ri${i}`, kind: "road", label: r.road_name, sublabel: r.title.slice(0, 38), detail: r });
  });

  inputs.forEach(({ id, kind, label, sublabel, detail }, i) => {
    nodes.push({ id, type: "rn", position: { x: COL[1], y: colY(inputs.length, i, CY) }, data: { kind, label, sublabel, detail } as RNodeData });
    edges.push(mkEdge(`ctx-${id}`, "ctx", id));
  });

  // ── Col 2: Tool calls ────────────────────────────────────────────────────
  const tools = toolCalls.length ? toolCalls : ["get_operational_brief", "inspect_route_options"];
  tools.forEach((tool, i) => {
    const id = `t${i}`;
    nodes.push({ id, type: "rn", position: { x: COL[2], y: colY(tools.length, i, CY) }, data: { kind: "tool", label: tool, sublabel: `tool call ${i + 1}`, detail: { tool, sequence: i + 1 } } as RNodeData });
    edges.push(mkEdge(`ctx-t${i}`, "ctx", id));
  });

  // ── Col 3: Gemini Decision ───────────────────────────────────────────────
  const strat = (assessment.plan.recommended_strategy ?? "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const conf = Math.round((assessment.plan.confidence ?? 0) * 100);

  nodes.push({
    id: "dec", type: "rn",
    position: { x: COL[3], y: CY - 60 },
    data: {
      kind: "decision",
      label: strat || "Gemini Decision",
      sublabel: `${conf}% confidence · ${assessment.planning_mode?.replace(/_/g, " ") ?? ""}`,
      detail: decision,
    } as RNodeData,
  });
  tools.forEach((_, i) => edges.push(mkEdge(`t${i}-dec`, `t${i}`, "dec")));

  // Gemini's incident summary as a "thought" node
  if (summary) {
    nodes.push({
      id: "summary", type: "rn",
      position: { x: COL[3], y: CY + 80 },
      data: { kind: "thought", label: summary.slice(0, 90) + (summary.length > 90 ? "…" : ""), sublabel: "Gemini assessment", detail: { full_text: summary } } as RNodeData,
    });
    edges.push(mkEdge("dec-sum", "dec", "summary", { dashed: true, color: "#3a2a5a" }));
  }

  // ── Col 4: Zone risks ────────────────────────────────────────────────────
  const zones = assessment.plan.zone_risks ?? [];
  const ZONE_SPACING = 190;
  const zoneStartY = CY - ((zones.length - 1) * ZONE_SPACING) / 2;

  zones.forEach((zone, i) => {
    const zid = `zr${i}`;
    const zy = zoneStartY + i * ZONE_SPACING;
    nodes.push({
      id: zid, type: "rn",
      position: { x: COL[4], y: zy },
      data: { kind: "zone-risk", label: zone.zone_id, sublabel: `${zone.risk_level} · ${zone.score.toFixed(2)} score · ${zone.urgency_minutes}min`, riskLevel: zone.risk_level, detail: zone } as RNodeData,
    });
    edges.push(mkEdge(`dec-${zid}`, "dec", zid));

    // Reasoning factor sub-nodes (thought bubbles)
    (zone.reasoning_factors ?? []).slice(0, 2).forEach((factor, j) => {
      const fid = `f${i}${j}`;
      nodes.push({
        id: fid, type: "rn",
        position: { x: COL[4] + 18, y: zy + 85 + j * 80 },
        data: { kind: "thought", label: String(factor).slice(0, 65), sublabel: "reasoning factor", detail: { factor, zone_id: zone.zone_id } } as RNodeData,
      });
      edges.push(mkEdge(`${zid}-${fid}`, zid, fid, { dashed: true, color: "#2a2010", dim: true }));
    });
  });

  // ── Col 5: Plan steps ────────────────────────────────────────────────────
  const steps = assessment.plan.steps ?? [];
  const STEP_SPACING = 190;
  const stepStartY = CY - ((steps.length - 1) * STEP_SPACING) / 2;

  steps.forEach((step, i) => {
    const sid = `ps${i}`;
    const sy = stepStartY + i * STEP_SPACING;
    nodes.push({
      id: sid, type: "rn",
      position: { x: COL[5], y: sy },
      data: { kind: "planstep", label: step.zone_id, sublabel: step.strategy.replace(/_/g, " ") + (step.start_after_minutes > 0 ? ` · +${step.start_after_minutes}min` : ""), detail: step } as RNodeData,
    });
    const srcZone = zones.findIndex((z) => z.zone_id === step.zone_id);
    edges.push(mkEdge(`${srcZone >= 0 ? `zr${srcZone}` : "dec"}-${sid}`, srcZone >= 0 ? `zr${srcZone}` : "dec", sid));

    // Rationale thought node
    const rationale = step.rationale?.[0];
    if (rationale) {
      const rid = `rat${i}`;
      nodes.push({
        id: rid, type: "rn",
        position: { x: COL[5] + 18, y: sy + 85 },
        data: { kind: "thought", label: rationale.slice(0, 65), sublabel: "rationale", detail: { rationale, zone_id: step.zone_id } } as RNodeData,
      });
      edges.push(mkEdge(`${sid}-${rid}`, sid, rid, { dashed: true, color: "#0a1c10", dim: true }));
    }
  });

  // ── Col 6: Rejected alternatives, data gaps, risks, fallback ────────────
  let y6 = 30;

  (assessment.plan.rejected_alternatives ?? []).slice(0, 4).forEach((alt, i) => {
    const id = `rej${i}`;
    nodes.push({
      id, type: "rn",
      position: { x: COL[6], y: y6 },
      data: { kind: "rejected", label: `${String(alt.origin_id ?? "?")} → ${String(alt.destination_id ?? "×")}`, sublabel: String(alt.reason ?? "").slice(0, 55), detail: alt } as RNodeData,
    });
    edges.push(mkEdge(`dec-${id}`, "dec", id, { dashed: true }));
    y6 += 95;
  });

  y6 += 10;
  dataGaps.slice(0, 3).forEach((gap, i) => {
    const id = `gap${i}`;
    nodes.push({ id, type: "rn", position: { x: COL[6], y: y6 }, data: { kind: "gap", label: String(gap).slice(0, 60), sublabel: "data gap", detail: { gap } } as RNodeData });
    edges.push(mkEdge(`dec-${id}`, "dec", id, { dashed: true, dim: true }));
    y6 += 85;
  });

  y6 += 10;
  risksIfWrong.slice(0, 3).forEach((risk, i) => {
    const id = `risk${i}`;
    nodes.push({ id, type: "rn", position: { x: COL[6], y: y6 }, data: { kind: "risk", label: String(risk).slice(0, 60), sublabel: "risk if wrong", detail: { risk } } as RNodeData });
    edges.push(mkEdge(`dec-${id}`, "dec", id, { dashed: true, dim: true }));
    y6 += 85;
  });

  if (fallback) {
    nodes.push({ id: "fb", type: "rn", position: { x: COL[6], y: y6 + 10 }, data: { kind: "fallback", label: fallback.slice(0, 70), sublabel: "fallback plan", detail: { fallback_plan: fallback } } as RNodeData });
    edges.push(mkEdge("dec-fb", "dec", "fb", { dashed: true, dim: true }));
  }

  return { nodes, edges };
}

// ─── detail panel ─────────────────────────────────────────────────────────────
function NodeDetail({ data, onClose }: { data: RNodeData; onClose: () => void }) {
  const s = KIND_STYLE[data.kind] ?? KIND_STYLE.thought;
  const d = data.detail as Record<string, unknown> | null;

  // Render structured detail for decision node
  const isDecision = data.kind === "decision";
  const decisionData = isDecision && d ? d : null;

  return (
    <div style={{ position: "absolute", top: 0, right: 0, width: 290, height: "100%", background: "#08111a", borderLeft: `1px solid ${s.border}`, display: "flex", flexDirection: "column", zIndex: 20 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid #111e2a", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, flexShrink: 0 }}>
        <div>
          <span style={{ display: "inline-block", padding: "2px 6px", background: `${s.accent}18`, border: `1px solid ${s.accent}40`, borderRadius: 2, color: s.accent, fontSize: 9, fontWeight: 800, letterSpacing: "0.1em" }}>
            {s.badge}
          </span>
          <div style={{ color: "#edf5ff", fontSize: 13, fontWeight: 700, marginTop: 5, lineHeight: 1.3 }}>{data.label}</div>
          {data.sublabel ? <div style={{ color: "#4a5c6a", fontSize: 11, marginTop: 2 }}>{data.sublabel}</div> : null}
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "#4a5c6a", fontSize: 14, cursor: "pointer", padding: "2px 4px", flexShrink: 0 }}>✕</button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "10px 14px" }}>
        {/* Structured view for decision node */}
        {decisionData ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {decisionData.incident_summary ? (
              <DetailSection label="Gemini Assessment" accent={s.accent}>
                <p style={{ margin: 0, fontSize: 11, color: "#c0ccd8", lineHeight: 1.5 }}>{String(decisionData.incident_summary)}</p>
              </DetailSection>
            ) : null}
            {Array.isArray(decisionData.data_gaps) && (decisionData.data_gaps as string[]).length ? (
              <DetailSection label="Data Gaps" accent="#c0a060">
                {(decisionData.data_gaps as string[]).map((g, i) => <BulletLine key={i} text={g} color="#c0a060" />)}
              </DetailSection>
            ) : null}
            {Array.isArray(decisionData.risks_if_wrong) && (decisionData.risks_if_wrong as string[]).length ? (
              <DetailSection label="Risks if Wrong" accent="#c07070">
                {(decisionData.risks_if_wrong as string[]).map((r, i) => <BulletLine key={i} text={r} color="#c07070" />)}
              </DetailSection>
            ) : null}
            {decisionData.fallback_plan ? (
              <DetailSection label="Fallback Plan" accent="#6090a8">
                <p style={{ margin: 0, fontSize: 11, color: "#c0ccd8", lineHeight: 1.5 }}>{String(decisionData.fallback_plan)}</p>
              </DetailSection>
            ) : null}
            <DetailSection label="Raw Decision" accent="#293742">
              <JsonBlock data={decisionData} />
            </DetailSection>
          </div>
        ) : (
          <JsonBlock data={d} />
        )}
      </div>
    </div>
  );
}

function DetailSection({ label, accent, children }: { label: string; accent: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.12em", textTransform: "uppercase", color: accent, marginBottom: 5 }}>{label}</div>
      {children}
    </div>
  );
}

function BulletLine({ text, color }: { text: string; color: string }) {
  return <p style={{ margin: "0 0 3px 0", fontSize: 11, color: "#9daab5", lineHeight: 1.4 }}>
    <span style={{ color, marginRight: 4 }}>›</span>{text}
  </p>;
}

function JsonBlock({ data }: { data: unknown }) {
  if (!data) return <p style={{ color: "#3a4a58", fontSize: 11, margin: 0 }}>No data.</p>;
  return (
    <pre style={{ margin: 0, fontSize: 9.5, color: "#607080", background: "#040a10", padding: 8, borderRadius: 3, border: "1px solid #0e1c28", whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.5, overflow: "auto", maxHeight: 320 }}>
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

// ─── inner flow ───────────────────────────────────────────────────────────────
function GraphInner({
  assessment,
  loading,
}: {
  assessment: AssessmentResult | null;
  loading: boolean;
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState<RNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selected, setSelected] = useState<RNodeData | null>(null);

  useEffect(() => {
    if (!assessment) return;
    const { nodes: n, edges: e } = buildRichGraph(assessment);
    setNodes(n); setEdges(e);
  }, [assessment, setNodes, setEdges]);

  if (loading && !assessment) {
    return (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14, background: "#0b1117" }}>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" style={{ animation: "fg-blink 1.4s ease-in-out infinite" }}>
          <circle cx="12" cy="12" r="10" stroke="#1e3045" strokeWidth="2" />
          <path d="M12 6v6l4 2" stroke="#8abbff" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <p style={{ margin: 0, color: "#4a5c6a", fontSize: 12, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>
          Gemini is reasoning
        </p>
        <p style={{ margin: 0, color: "#2a3a48", fontSize: 11 }}>
          Trace graph will appear here when complete
        </p>
      </div>
    );
  }

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={NODE_TYPES}
        onNodeClick={(_, node) => {
          const d = node.data as RNodeData;
          setSelected((prev) => (prev?.label === d.label && prev?.kind === d.kind ? null : d));
        }}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.15}
        maxZoom={3}
        proOptions={{ hideAttribution: true }}
        style={{ background: "#0b1117" }}
      >
        <Background color="#0e1820" gap={32} variant={BackgroundVariant.Dots} />
        <Controls style={{ bottom: 12, right: selected ? 298 : 12, left: "auto", top: "auto" }} showInteractive={false} />
        <MiniMap
          style={{ bottom: 12, left: 12, background: "#06090d", border: "1px solid #1a2530" }}
          nodeColor={(n) => {
            const d = n.data as RNodeData;
            return (KIND_STYLE[d.kind] ?? KIND_STYLE.thought).accent + "99";
          }}
          maskColor="rgba(0,0,0,0.6)"
        />
      </ReactFlow>

      {selected ? <NodeDetail data={selected} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}

// ─── public export ────────────────────────────────────────────────────────────
export function ReasoningGraph({
  assessment,
  busy,
}: {
  assessment: AssessmentResult | null;
  busy: string | null;
}) {
  const loading = busy === "assessment";
  if (!assessment && !loading) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%", background: "#0b1117" }}>
      {/* header bar */}
      <div className="fg-reasoning-header">
        <div className="fg-reasoning-title">
          Gemini Reasoning Trace
        </div>
        {assessment ? (
          <div className="fg-reasoning-meta">
            <span>{(assessment.trace ?? []).length} trace steps</span>
            <span className="fg-reasoning-meta-sep">·</span>
            <span>{assessment.gemini_tool_calls?.length ?? 0} tool calls</span>
            <span className="fg-reasoning-meta-sep">·</span>
            <span>{assessment.plan.zone_risks?.length ?? 0} zones</span>
            <span className="fg-reasoning-meta-sep">·</span>
            <span>{assessment.plan.rejected_alternatives?.length ?? 0} rejected</span>
            <span className="fg-reasoning-meta-sep">·</span>
            <span>{(assessment.plan.risks_if_wrong?.length ?? 0) + (Array.isArray((assessment.gemini_decision as Record<string,unknown> | null)?.data_gaps) ? ((assessment.gemini_decision as Record<string,unknown>).data_gaps as unknown[]).length : 0)} risks/gaps</span>
          </div>
        ) : null}
        <div className="fg-reasoning-meta" style={{ marginLeft: "auto", color: "#1e2d3d" }}>
          {assessment ? "scroll · pan · click nodes" : ""}
        </div>
      </div>

      {/* graph area */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <ReactFlowProvider>
          <GraphInner assessment={assessment} loading={loading} />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
