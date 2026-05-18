"use client";

import { useEffect, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Edge,
  Handle,
  MiniMap,
  Node,
  NodeProps,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";

import type { AssessmentResult } from "@/lib/types";
import type { SlimContext } from "@/lib/api";

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

// ─── dagre auto-layout ────────────────────────────────────────────────────────
function applyDagreLayout(nodes: RNode[], edges: Edge[]): RNode[] {
  if (nodes.length === 0) return nodes;
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", ranksep: 90, nodesep: 44, marginx: 24, marginy: 24 });
  nodes.forEach((n) => g.setNode(n.id, { width: 190, height: 68 }));
  edges.forEach((e) => {
    try { g.setEdge(e.source, e.target); } catch { /* skip invalid */ }
  });
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    return pos ? { ...n, position: { x: pos.x - 95, y: pos.y - 34 } } : n;
  });
}

// ─── build full graph from completed assessment ───────────────────────────────
function buildRichGraph(assessment: AssessmentResult): { nodes: RNode[]; edges: Edge[] } {
  const nodes: RNode[] = [];
  const edges: Edge[] = [];

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

  const tools = toolCalls.length ? toolCalls : ["get_operational_brief", "inspect_route_options"];
  tools.forEach((tool, i) => {
    const id = `t${i}`;
    nodes.push({ id, type: "rn", position: { x: COL[2], y: colY(tools.length, i, CY) }, data: { kind: "tool", label: tool, sublabel: `tool call ${i + 1}`, detail: { tool, sequence: i + 1 } } as RNodeData });
    edges.push(mkEdge(`ctx-t${i}`, "ctx", id));
  });

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

  if (summary) {
    nodes.push({
      id: "summary", type: "rn",
      position: { x: COL[3], y: CY + 80 },
      data: { kind: "thought", label: summary.slice(0, 90) + (summary.length > 90 ? "…" : ""), sublabel: "Gemini assessment", detail: { full_text: summary } } as RNodeData,
    });
    edges.push(mkEdge("dec-sum", "dec", "summary", { dashed: true, color: "#3a2a5a" }));
  }

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
    (zone.reasoning_factors ?? []).slice(0, 2).forEach((factor, j) => {
      const fid = `f${i}${j}`;
      nodes.push({ id: fid, type: "rn", position: { x: COL[4] + 18, y: zy + 85 + j * 80 }, data: { kind: "thought", label: String(factor).slice(0, 65), sublabel: "reasoning factor", detail: { factor, zone_id: zone.zone_id } } as RNodeData });
      edges.push(mkEdge(`${zid}-${fid}`, zid, fid, { dashed: true, color: "#2a2010", dim: true }));
    });
  });

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
    const rationale = step.rationale?.[0];
    if (rationale) {
      const rid = `rat${i}`;
      nodes.push({ id: rid, type: "rn", position: { x: COL[5] + 18, y: sy + 85 }, data: { kind: "thought", label: rationale.slice(0, 65), sublabel: "rationale", detail: { rationale, zone_id: step.zone_id } } as RNodeData });
      edges.push(mkEdge(`${sid}-${rid}`, sid, rid, { dashed: true, color: "#0a1c10", dim: true }));
    }
  });

  let y6 = 30;
  (assessment.plan.rejected_alternatives ?? []).slice(0, 4).forEach((alt, i) => {
    const id = `rej${i}`;
    nodes.push({ id, type: "rn", position: { x: COL[6], y: y6 }, data: { kind: "rejected", label: `${String(alt.origin_id ?? "?")} → ${String(alt.destination_id ?? "×")}`, sublabel: String(alt.reason ?? "").slice(0, 55), detail: alt } as RNodeData });
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

// ─── build partial graph from streaming events ────────────────────────────────
function buildPartialGraph(
  events: Record<string, unknown>[],
  slimContext: SlimContext | null,
): { nodes: RNode[]; edges: Edge[] } {
  if (events.length === 0 && !slimContext) return { nodes: [], edges: [] };

  const nodes: RNode[] = [];
  const edges: Edge[] = [];

  // Last event per step (multiple validate events → keep last)
  const stepMap = new Map<string, Record<string, unknown>>();
  for (const e of events) {
    stepMap.set(e.step as string, e);
  }

  const COL = [60, 280, 510, 740, 990, 1240, 1490];
  const CY = 220;

  // ── Col 0: CTX ──────────────────────────────────────────────────────────────
  const sc = slimContext;
  nodes.push({
    id: "ctx", type: "rn",
    position: { x: COL[0], y: CY },
    data: {
      kind: "context",
      label: "Incident Context",
      sublabel: sc ? `${sc.fires.length} fires · ${sc.zones.length} zones · ${sc.road_events.length} road events` : "Loading...",
    } as RNodeData,
  });

  // ── Col 1: Input nodes from slim_context ─────────────────────────────────────
  if (sc) {
    const inputs: Array<{ id: string; kind: RKind; label: string; sublabel: string; detail: unknown }> = [];
    sc.fires.forEach((f, i) => inputs.push({ id: `fi${i}`, kind: "fire", label: `Hotspot ${i + 1}`, sublabel: `FRP ${f.frp.toFixed(1)} MW · ${f.source}`, detail: f }));
    sc.zones.forEach((z, i) => inputs.push({ id: `zi${i}`, kind: "zone-input", label: z.name, sublabel: `Pop ${z.population} · Vuln ${z.vulnerable_count}`, detail: z }));
    sc.road_events.forEach((r, i) => inputs.push({ id: `ri${i}`, kind: "road", label: r.road_name, sublabel: r.title.slice(0, 38), detail: r }));
    inputs.forEach(({ id, kind, label, sublabel, detail }, i) => {
      nodes.push({ id, type: "rn", position: { x: COL[1], y: colY(inputs.length, i, CY) }, data: { kind, label, sublabel, detail } as RNodeData });
      edges.push(mkEdge(`ctx-${id}`, "ctx", id));
    });
  }

  // ── Col 2 & 3: Tool calls + Gemini Decision (from reason step) ───────────────
  const reasonEvent = stepMap.get("reason");
  if (reasonEvent) {
    const output = (reasonEvent.output ?? {}) as Record<string, unknown>;
    const toolCalls: string[] = Array.isArray(output.tool_calls) ? (output.tool_calls as string[]) : ["get_operational_brief"];
    const decision = ((output.decision ?? {}) as Record<string, unknown>);

    toolCalls.forEach((tool, i) => {
      const id = `t${i}`;
      nodes.push({ id, type: "rn", position: { x: COL[2], y: colY(toolCalls.length, i, CY) }, data: { kind: "tool", label: tool, sublabel: `tool call ${i + 1}`, detail: { tool, sequence: i + 1 } } as RNodeData });
      edges.push(mkEdge(`ctx-t${i}`, "ctx", id));
    });

    const strat = (decision.recommended_strategy as string ?? "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    nodes.push({
      id: "dec", type: "rn",
      position: { x: COL[3], y: CY - 60 },
      data: { kind: "decision", label: strat || "Gemini Decision", sublabel: "reasoning complete", detail: decision } as RNodeData,
    });
    toolCalls.forEach((_, i) => edges.push(mkEdge(`t${i}-dec`, `t${i}`, "dec")));

    const summary = String(decision.incident_summary ?? "");
    if (summary) {
      nodes.push({ id: "summary", type: "rn", position: { x: COL[3], y: CY + 80 }, data: { kind: "thought", label: summary.slice(0, 90) + (summary.length > 90 ? "…" : ""), sublabel: "Gemini assessment" } as RNodeData });
      edges.push(mkEdge("dec-sum", "dec", "summary", { dashed: true, color: "#3a2a5a" }));
    }
  }

  // ── Col 4: Zone risks (from assess step) ─────────────────────────────────────
  const assessEvent = stepMap.get("assess");
  if (assessEvent) {
    const zoneRisks = Array.isArray(assessEvent.output) ? (assessEvent.output as Array<Record<string, unknown>>) : [];
    const ZONE_SPACING = 190;
    const zoneStartY = CY - ((zoneRisks.length - 1) * ZONE_SPACING) / 2;
    const hasDecision = nodes.some((n) => n.id === "dec");
    zoneRisks.forEach((zone, i) => {
      const zid = `zr${i}`;
      const zy = zoneStartY + i * ZONE_SPACING;
      nodes.push({
        id: zid, type: "rn",
        position: { x: COL[4], y: zy },
        data: { kind: "zone-risk", label: zone.zone_id as string, sublabel: `${zone.risk_level} · ${(zone.score as number).toFixed(2)} score · ${zone.urgency_minutes}min`, riskLevel: zone.risk_level as string, detail: zone } as RNodeData,
      });
      if (hasDecision) edges.push(mkEdge(`dec-${zid}`, "dec", zid));
      (Array.isArray(zone.reasoning_factors) ? zone.reasoning_factors as string[] : []).slice(0, 2).forEach((factor, j) => {
        const fid = `f${i}${j}`;
        nodes.push({ id: fid, type: "rn", position: { x: COL[4] + 18, y: zy + 85 + j * 80 }, data: { kind: "thought", label: String(factor).slice(0, 65), sublabel: "reasoning factor" } as RNodeData });
        edges.push(mkEdge(`${zid}-${fid}`, zid, fid, { dashed: true, color: "#2a2010", dim: true }));
      });
    });
  }

  // ── Col 5: Plan steps (from plan step) ───────────────────────────────────────
  const planEvent = stepMap.get("plan");
  if (planEvent) {
    const planOutput = (planEvent.output ?? {}) as { planning_mode: string; plan: Record<string, unknown> };
    const plan = planOutput.plan ?? {};
    const steps = Array.isArray(plan.steps) ? (plan.steps as Array<Record<string, unknown>>) : [];
    const zoneRisksFromPlan = Array.isArray(plan.zone_risks) ? (plan.zone_risks as Array<Record<string, unknown>>) : [];
    const STEP_SPACING = 190;
    const stepStartY = CY - ((steps.length - 1) * STEP_SPACING) / 2;
    steps.forEach((step, i) => {
      const sid = `ps${i}`;
      const sy = stepStartY + i * STEP_SPACING;
      nodes.push({
        id: sid, type: "rn",
        position: { x: COL[5], y: sy },
        data: { kind: "planstep", label: step.zone_id as string, sublabel: (step.strategy as string).replace(/_/g, " ") + (Number(step.start_after_minutes) > 0 ? ` · +${step.start_after_minutes}min` : ""), detail: step } as RNodeData,
      });
      const srcZone = zoneRisksFromPlan.findIndex((z) => z.zone_id === step.zone_id);
      edges.push(mkEdge(`${srcZone >= 0 ? `zr${srcZone}` : "dec"}-${sid}`, srcZone >= 0 ? `zr${srcZone}` : "dec", sid));
      const rationale = Array.isArray(step.rationale) ? (step.rationale as string[])[0] : null;
      if (rationale) {
        const rid = `rat${i}`;
        nodes.push({ id: rid, type: "rn", position: { x: COL[5] + 18, y: sy + 85 }, data: { kind: "thought", label: rationale.slice(0, 65), sublabel: "rationale" } as RNodeData });
        edges.push(mkEdge(`${sid}-${rid}`, sid, rid, { dashed: true, color: "#0a1c10", dim: true }));
      }
    });
  }

  // ── Col 6: Rejected, gaps, risks, fallback ────────────────────────────────────
  let y6 = 30;
  // Rejected alternatives from plan step
  if (planEvent) {
    const plan = ((planEvent.output as { plan?: Record<string, unknown> })?.plan ?? {});
    (Array.isArray(plan.rejected_alternatives) ? plan.rejected_alternatives as Array<Record<string, unknown>> : []).slice(0, 4).forEach((alt, i) => {
      const id = `rej${i}`;
      nodes.push({ id, type: "rn", position: { x: COL[6], y: y6 }, data: { kind: "rejected", label: `${String(alt.origin_id ?? "?")} → ${String(alt.destination_id ?? "×")}`, sublabel: String(alt.reason ?? "").slice(0, 55), detail: alt } as RNodeData });
      if (nodes.some((n) => n.id === "dec")) edges.push(mkEdge(`dec-${id}`, "dec", id, { dashed: true }));
      y6 += 95;
    });
    y6 += 10;
  }
  // Data gaps, risks, fallback from Gemini decision
  if (reasonEvent) {
    const decision = (((reasonEvent.output ?? {}) as Record<string, unknown>).decision ?? {}) as Record<string, unknown>;
    const dataGaps: string[] = Array.isArray(decision.data_gaps) ? (decision.data_gaps as string[]) : [];
    const risksIfWrong: string[] = Array.isArray(decision.risks_if_wrong) ? (decision.risks_if_wrong as string[]) : [];
    const fallback = String(decision.fallback_plan ?? "");
    dataGaps.slice(0, 3).forEach((gap, i) => {
      const id = `gap${i}`;
      nodes.push({ id, type: "rn", position: { x: COL[6], y: y6 }, data: { kind: "gap", label: String(gap).slice(0, 60), sublabel: "data gap" } as RNodeData });
      if (nodes.some((n) => n.id === "dec")) edges.push(mkEdge(`dec-${id}`, "dec", id, { dashed: true, dim: true }));
      y6 += 85;
    });
    y6 += 10;
    risksIfWrong.slice(0, 3).forEach((risk, i) => {
      const id = `risk${i}`;
      nodes.push({ id, type: "rn", position: { x: COL[6], y: y6 }, data: { kind: "risk", label: String(risk).slice(0, 60), sublabel: "risk if wrong" } as RNodeData });
      if (nodes.some((n) => n.id === "dec")) edges.push(mkEdge(`dec-${id}`, "dec", id, { dashed: true, dim: true }));
      y6 += 85;
    });
    if (fallback) {
      nodes.push({ id: "fb", type: "rn", position: { x: COL[6], y: y6 + 10 }, data: { kind: "fallback", label: fallback.slice(0, 70), sublabel: "fallback plan" } as RNodeData });
      if (nodes.some((n) => n.id === "dec")) edges.push(mkEdge("dec-fb", "dec", "fb", { dashed: true, dim: true }));
    }
  }

  return { nodes, edges };
}

// ─── node popup ───────────────────────────────────────────────────────────────
function NodePopup({ data, x, y, onClose }: { data: RNodeData; x: number; y: number; onClose: () => void }) {
  const s = KIND_STYLE[data.kind] ?? KIND_STYLE.thought;
  const d = data.detail as Record<string, unknown> | null;

  // Clamp to viewport
  const popupW = 320;
  const popupMaxH = 460;
  const left = Math.min(x + 14, (typeof window !== "undefined" ? window.innerWidth : 1200) - popupW - 8);
  const top = Math.min(Math.max(y - 30, 8), (typeof window !== "undefined" ? window.innerHeight : 800) - popupMaxH - 8);

  return (
    <div
      style={{
        position: "fixed", left, top, width: popupW, zIndex: 9999,
        background: "#08111a", border: `1px solid ${s.border}`,
        borderTop: `2px solid ${s.accent}`,
        borderRadius: 5, boxShadow: "0 12px 40px rgba(0,0,0,0.85), 0 0 0 1px rgba(0,0,0,0.4)",
        display: "flex", flexDirection: "column",
        maxHeight: popupMaxH, overflow: "hidden",
      }}
    >
      {/* Header */}
      <div style={{ padding: "10px 12px 8px", borderBottom: "1px solid #111e2a", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, flexShrink: 0 }}>
        <div style={{ minWidth: 0 }}>
          <span style={{ display: "inline-block", padding: "1px 5px", background: `${s.accent}20`, border: `1px solid ${s.accent}40`, borderRadius: 2, color: s.accent, fontSize: 9, fontWeight: 800, letterSpacing: "0.1em" }}>
            {s.badge}
          </span>
          <div style={{ color: "#edf5ff", fontSize: 12, fontWeight: 700, marginTop: 4, lineHeight: 1.3 }}>{data.label}</div>
          {data.sublabel ? <div style={{ color: "#4a5c6a", fontSize: 10, marginTop: 2, lineHeight: 1.3 }}>{data.sublabel}</div> : null}
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "#4a5c6a", fontSize: 13, cursor: "pointer", padding: "2px 4px", flexShrink: 0, lineHeight: 1, marginTop: 1 }}>✕</button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflow: "auto", padding: "10px 12px" }}>
        <PopupBody kind={data.kind} label={data.label} detail={d} accent={s.accent} riskLevel={data.riskLevel} />
      </div>
    </div>
  );
}

function PopupBody({ kind, label, detail: d, accent, riskLevel }: { kind: RKind; label: string; detail: Record<string, unknown> | null; accent: string; riskLevel?: string }) {
  const RISK_COLORS: Record<string, string> = { CRITICAL: "#db3737", HIGH: "#c87328", MODERATE: "#f2b824", LOW: "#45d483" };

  if (kind === "fire") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Row label="Radiative Power" value={d?.frp != null ? `${Number(d.frp).toFixed(1)} MW` : "—"} accent={accent} />
        <Row label="Source" value={String(d?.source ?? "—")} accent={accent} />
        {d?.location ? <Row label="Location" value={`${(d.location as {lat: number}).lat?.toFixed(4)}, ${(d.location as {lon: number}).lon?.toFixed(4)}`} accent={accent} /> : null}
        {d?.confidence ? <Row label="Confidence" value={String(d.confidence)} accent={accent} /> : null}
        {d?.external_id ? <Row label="External ID" value={String(d.external_id)} accent={accent} mono /> : null}
      </div>
    );
  }

  if (kind === "zone-input") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Row label="Population" value={d?.population != null ? String(d.population) : "—"} accent={accent} />
        <Row label="Vulnerable" value={d?.vulnerable_count != null ? String(d.vulnerable_count) : "—"} accent={accent} />
        {d?.households != null ? <Row label="Households" value={String(d.households)} accent={accent} /> : null}
        {d?.vehicle_access_score != null ? <Row label="Vehicle Access" value={`${Number(d.vehicle_access_score).toFixed(2)}`} accent={accent} /> : null}
        {d?.priority_notes ? <div><Label label="Notes" accent={accent} /><p style={{ margin: "4px 0 0", fontSize: 11, color: "#9daab5", lineHeight: 1.4 }}>{String(d.priority_notes)}</p></div> : null}
        {d?.zone_id ? <Row label="Zone ID" value={String(d.zone_id)} accent={accent} mono /> : null}
      </div>
    );
  }

  if (kind === "zone-risk") {
    const rl = riskLevel ?? String(d?.risk_level ?? "");
    const rlColor = RISK_COLORS[rl] ?? accent;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.08em", padding: "2px 6px", background: `${rlColor}18`, border: `1px solid ${rlColor}50`, borderRadius: 2, color: rlColor }}>{rl}</span>
          <span style={{ fontSize: 11, color: "#8a9ba8" }}>{d?.score != null ? `Score ${Number(d.score).toFixed(3)}` : ""}</span>
        </div>
        <Row label="Urgency" value={d?.urgency_minutes != null ? `${d.urgency_minutes} minutes` : "—"} accent={accent} />
        <Row label="Confidence" value={d?.confidence != null ? `${Math.round(Number(d.confidence) * 100)}%` : "—"} accent={accent} />
        {Array.isArray(d?.reasoning_factors) && (d.reasoning_factors as string[]).length ? (
          <div>
            <Label label="Reasoning Factors" accent={accent} />
            {(d.reasoning_factors as string[]).map((f, i) => <BulletLine key={i} text={f} color={accent} />)}
          </div>
        ) : null}
      </div>
    );
  }

  if (kind === "decision") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {d?.recommended_strategy ? <Row label="Strategy" value={String(d.recommended_strategy).replace(/_/g, " ")} accent={accent} /> : null}
        {d?.confidence != null ? <Row label="Confidence" value={`${Math.round(Number(d.confidence) * 100)}%`} accent={accent} /> : null}
        {d?.incident_summary ? (
          <div>
            <Label label="Assessment" accent={accent} />
            <p style={{ margin: "4px 0 0", fontSize: 11, color: "#c0ccd8", lineHeight: 1.5 }}>{String(d.incident_summary)}</p>
          </div>
        ) : null}
        {Array.isArray(d?.data_gaps) && (d.data_gaps as string[]).length ? (
          <div>
            <Label label="Data Gaps" accent="#c0a060" />
            {(d.data_gaps as string[]).map((g, i) => <BulletLine key={i} text={g} color="#c0a060" />)}
          </div>
        ) : null}
        {Array.isArray(d?.risks_if_wrong) && (d.risks_if_wrong as string[]).length ? (
          <div>
            <Label label="Risks if Wrong" accent="#c07070" />
            {(d.risks_if_wrong as string[]).map((r, i) => <BulletLine key={i} text={r} color="#c07070" />)}
          </div>
        ) : null}
        {d?.fallback_plan ? (
          <div>
            <Label label="Fallback Plan" accent="#6090a8" />
            <p style={{ margin: "4px 0 0", fontSize: 11, color: "#c0ccd8", lineHeight: 1.5 }}>{String(d.fallback_plan)}</p>
          </div>
        ) : null}
      </div>
    );
  }

  if (kind === "planstep") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Row label="Strategy" value={String(d?.strategy ?? "—").replace(/_/g, " ")} accent={accent} />
        {d?.destination_id ? <Row label="Destination" value={String(d.destination_id)} accent={accent} /> : null}
        <Row label="Timing" value={d?.start_after_minutes != null ? (Number(d.start_after_minutes) === 0 ? "Immediate" : `+${d.start_after_minutes} min`) : "—"} accent={accent} />
        {Array.isArray(d?.rationale) && (d.rationale as string[]).length ? (
          <div>
            <Label label="Rationale" accent={accent} />
            {(d.rationale as string[]).map((r, i) => <BulletLine key={i} text={r} color={accent} />)}
          </div>
        ) : null}
        {d?.message ? (
          <div>
            <Label label="Action Message" accent="#5c7080" />
            <p style={{ margin: "4px 0 0", fontSize: 11, color: "#9daab5", lineHeight: 1.4 }}>{String(d.message)}</p>
          </div>
        ) : null}
      </div>
    );
  }

  if (kind === "rejected") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Row label="Origin" value={String(d?.origin_id ?? "—")} accent={accent} />
        <Row label="Destination" value={String(d?.destination_id ?? "—")} accent={accent} />
        {d?.reason ? (
          <div>
            <Label label="Reason" accent={accent} />
            <p style={{ margin: "4px 0 0", fontSize: 11, color: "#9daab5", lineHeight: 1.4 }}>{String(d.reason)}</p>
          </div>
        ) : null}
      </div>
    );
  }

  if (kind === "road") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {d?.title ? (
          <div>
            <Label label="Title" accent={accent} />
            <p style={{ margin: "4px 0 0", fontSize: 11, color: "#c0ccd8", lineHeight: 1.4 }}>{String(d.title)}</p>
          </div>
        ) : null}
        {d?.event_type ? <Row label="Event Type" value={String(d.event_type)} accent={accent} /> : null}
        {d?.severity ? <Row label="Severity" value={String(d.severity)} accent={accent} /> : null}
        {d?.external_id ? <Row label="External ID" value={String(d.external_id)} accent={accent} mono /> : null}
      </div>
    );
  }

  if (kind === "tool") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div>
          <Label label="Tool Name" accent={accent} />
          <code style={{ display: "block", marginTop: 4, fontSize: 11, color: accent, background: `${accent}10`, border: `1px solid ${accent}30`, borderRadius: 3, padding: "4px 8px", fontFamily: "monospace" }}>{label}</code>
        </div>
        {d?.sequence != null ? <Row label="Sequence" value={`Call #${d.sequence}`} accent={accent} /> : null}
      </div>
    );
  }

  if (kind === "thought" || kind === "gap" || kind === "risk" || kind === "fallback") {
    const fullText = d ? (String(d.factor ?? d.gap ?? d.risk ?? d.fallback_plan ?? d.full_text ?? d.rationale ?? "")) : label;
    return (
      <div>
        <p style={{ margin: 0, fontSize: 11, color: "#c0ccd8", lineHeight: 1.55, fontStyle: "italic" }}>{fullText || label}</p>
      </div>
    );
  }

  // context + fallback
  return <JsonBlock data={d} />;
}

function Label({ label, accent }: { label: string; accent: string }) {
  return <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.1em", textTransform: "uppercase", color: accent }}>{label}</div>;
}

function Row({ label, value, accent, mono = false }: { label: string; value: string; accent: string; mono?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
      <span style={{ fontSize: 10, color: "#4a5c6a", flexShrink: 0 }}>{label}</span>
      <span style={{ fontSize: 11, color: "#c0ccd8", fontWeight: 600, textAlign: "right", fontFamily: mono ? "monospace" : "inherit" }}>{value}</span>
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
  streamingEvents,
  slimContext,
  loading,
}: {
  assessment: AssessmentResult | null;
  streamingEvents: Record<string, unknown>[];
  slimContext: SlimContext | null;
  loading: boolean;
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState<RNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selected, setSelected] = useState<{ data: RNodeData; x: number; y: number } | null>(null);
  const { fitView } = useReactFlow();
  const didInitialFit = useRef(false);

  // Build graph from completed assessment
  useEffect(() => {
    if (!assessment) return;
    const { nodes: n, edges: e } = buildRichGraph(assessment);
    setNodes(n);
    setEdges(e);
    didInitialFit.current = false;
  }, [assessment, setNodes, setEdges]);

  // Build partial graph while streaming
  useEffect(() => {
    if (assessment) return; // full assessment takes precedence
    const { nodes: n, edges: e } = buildPartialGraph(streamingEvents, slimContext);
    setNodes(n);
    setEdges(e);
    if (n.length > 0 && !didInitialFit.current) {
      didInitialFit.current = true;
      window.requestAnimationFrame(() => fitView({ padding: 0.12, duration: 300 }));
    }
  }, [assessment, streamingEvents, slimContext, setNodes, setEdges, fitView]);

  // Auto-fit when assessment completes
  useEffect(() => {
    if (!assessment) return;
    window.requestAnimationFrame(() => fitView({ padding: 0.12, duration: 400 }));
  }, [assessment, fitView]);

  function handleAutoOrganize() {
    const layouted = applyDagreLayout(nodes, edges);
    setNodes(layouted);
    window.requestAnimationFrame(() => fitView({ padding: 0.12, duration: 350 }));
  }

  if (loading && nodes.length === 0) {
    return (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14, background: "#0b1117" }}>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" style={{ animation: "fg-blink 1.4s ease-in-out infinite" }}>
          <circle cx="12" cy="12" r="10" stroke="#1e3045" strokeWidth="2" />
          <path d="M12 6v6l4 2" stroke="#8abbff" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <p style={{ margin: 0, color: "#4a5c6a", fontSize: 12, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>
          Gemini is reasoning
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
        onNodeClick={(event, node) => {
          const d = node.data as RNodeData;
          setSelected((prev) => (prev?.data.label === d.label && prev?.data.kind === d.kind ? null : { data: d, x: event.clientX, y: event.clientY }));
        }}
        onPaneClick={() => setSelected(null)}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.15}
        maxZoom={3}
        proOptions={{ hideAttribution: true }}
        style={{ background: "#0b1117" }}
      >
        <Background color="#0e1820" gap={32} variant={BackgroundVariant.Dots} />
        <Controls style={{ bottom: 12, right: 12, left: "auto", top: "auto" }} showInteractive={false} />
        <MiniMap
          style={{ bottom: 12, left: 12, background: "#06090d", border: "1px solid #1a2530" }}
          nodeColor={(n) => {
            const d = n.data as RNodeData;
            return (KIND_STYLE[d.kind] ?? KIND_STYLE.thought).accent + "99";
          }}
          maskColor="rgba(0,0,0,0.6)"
        />
        {nodes.length > 0 ? (
          <Panel position="top-right" style={{ margin: "8px 8px 0 0" }}>
            <button
              onClick={handleAutoOrganize}
              style={{
                background: "#0e1820",
                border: "1px solid #1e3045",
                borderRadius: 3,
                color: "#8abbff",
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: "0.06em",
                padding: "5px 10px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 5,
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
                <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
              </svg>
              Auto-organize
            </button>
          </Panel>
        ) : null}
      </ReactFlow>

      {selected ? <NodePopup data={selected.data} x={selected.x} y={selected.y} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}

// ─── public export ────────────────────────────────────────────────────────────
export function ReasoningGraph({
  assessment,
  streamingEvents,
  slimContext,
  busy,
}: {
  assessment: AssessmentResult | null;
  streamingEvents: Record<string, unknown>[];
  slimContext: SlimContext | null;
  busy: string | null;
}) {
  const loading = busy === "assessment";
  const hasContent = assessment !== null || streamingEvents.length > 0;
  if (!hasContent && !loading) return null;

  const traceStepCount = assessment ? (assessment.trace ?? []).length : streamingEvents.length;
  const toolCallCount = assessment?.gemini_tool_calls?.length ?? 0;
  const zoneCount = assessment?.plan.zone_risks?.length ?? 0;
  const rejectedCount = assessment?.plan.rejected_alternatives?.length ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%", background: "#0b1117" }}>
      <div className="fg-reasoning-header">
        <div className="fg-reasoning-title">
          Gemini Reasoning Trace
        </div>
        {hasContent ? (
          <div className="fg-reasoning-meta">
            <span>{traceStepCount} trace steps</span>
            <span className="fg-reasoning-meta-sep">·</span>
            <span>{toolCallCount} tool calls</span>
            <span className="fg-reasoning-meta-sep">·</span>
            <span>{zoneCount} zones</span>
            {assessment ? (
              <>
                <span className="fg-reasoning-meta-sep">·</span>
                <span>{rejectedCount} rejected</span>
              </>
            ) : null}
          </div>
        ) : null}
        <div className="fg-reasoning-meta" style={{ marginLeft: "auto", color: "#1e2d3d" }}>
          {hasContent ? "scroll · pan · click nodes" : ""}
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>
        <ReactFlowProvider>
          <GraphInner
            assessment={assessment}
            streamingEvents={streamingEvents}
            slimContext={slimContext}
            loading={loading}
          />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
