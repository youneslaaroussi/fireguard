"use client";

import {
  Button,
  Callout,
  Classes,
  Dialog,
  Icon,
  Intent,
  ProgressBar,
  Spinner,
  Tag,
} from "@blueprintjs/core";
import { useEffect, useMemo, useRef, useState } from "react";
import { Toaster, toast } from "sonner";

import { MapPanel } from "@/components/MapPanel";
import { ReasoningGraph } from "@/components/ReasoningGraph";
import {
  approveBundle,
  executeBundle,
  getCurrentIncident,
  resetDemo,
  streamAssessment,
} from "@/lib/api";
import type { SlimContext } from "@/lib/api";
import type { ActionItem, AssessmentResult, FireHotspot, IncidentContext, Zone } from "@/lib/types";

type DemoStage = "incident" | "assessing" | "reasoning" | "approving" | "executed";

function intentForRisk(level: string): Intent {
  if (level === "CRITICAL" || level === "HIGH") return Intent.DANGER;
  if (level === "MODERATE") return Intent.WARNING;
  return Intent.SUCCESS;
}

function intentForStatus(status: string): Intent {
  if (["executed", "sent", "approved"].includes(status)) return Intent.SUCCESS;
  if (["failed", "rejected", "error"].includes(status)) return Intent.DANGER;
  if (["pending", "queued"].includes(status)) return Intent.WARNING;
  return Intent.NONE;
}

function shortText(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}

function stringify(value: unknown, fallback = "unknown"): string {
  if (value === undefined || value === null || value === "") return fallback;
  return String(value);
}

function inferStage(assessment: AssessmentResult | null, actions: ActionItem[], busy: string | null): DemoStage {
  if (busy === "assessment") return "assessing";
  if (!assessment) return "incident";
  const executedCount = actions.filter((a) => ["executed", "sent"].includes(a.status)).length;
  if (executedCount > 0) return "executed";
  if (assessment.approval.status === "approved") return "executed";
  if (assessment) return assessment.plan.requires_approval ? "approving" : "reasoning";
  return "reasoning";
}

export default function Home() {
  const [context, setContext] = useState<IncidentContext | null>(null);
  const [assessment, setAssessment] = useState<AssessmentResult | null>(null);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamingEvents, setStreamingEvents] = useState<Record<string, unknown>[]>([]);
  const [streamingStep, setStreamingStep] = useState<string | null>(null);
  const [slimContext, setSlimContext] = useState<SlimContext | null>(null);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [initialLoadHold, setInitialLoadHold] = useState(true);
  const [revealed, setRevealed] = useState({ fires: 0, roads: 0, zones: false, button: false });
  const revealTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const stage = useMemo(() => inferStage(assessment, actions, busy), [assessment, actions, busy]);

  useEffect(() => {
    getCurrentIncident()
      .then(setContext)
      .catch(() => setError("Could not load incident data."));
  }, []);

  useEffect(() => {
    const t = window.setTimeout(() => setInitialLoadHold(false), 1200);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    if (!context) return;
    revealTimersRef.current.forEach(clearTimeout);
    revealTimersRef.current = [];
    setRevealed({ fires: 0, roads: 0, zones: false, button: false });
    toast.dismiss();

    const schedule = (fn: () => void, ms: number) => {
      const t = setTimeout(fn, ms);
      revealTimersRef.current.push(t);
    };

    const firesToShow = Math.min(context.fires.length, 3);
    const roadsToShow = Math.min(context.road_events.length, 2);

    // Fires — staggered reveal, 300 ms apart
    for (let i = 0; i < firesToShow; i++) {
      const idx = i;
      schedule(() => {
        setRevealed((r) => ({ ...r, fires: idx + 1 }));
        if (idx === 0) {
          toast.error("Wildfire incident active", {
            id: "incident-alert",
            description: `${context.fires.length} hotspots · ${context.road_events.length} road events · ${context.zones.length} zones`,
            duration: 6000,
          });
        }
      }, 200 + idx * 300);
    }

    // Roads
    const roadStart = 200 + firesToShow * 300 + 150;
    for (let i = 0; i < roadsToShow; i++) {
      const idx = i;
      schedule(() => {
        setRevealed((r) => ({ ...r, roads: idx + 1 }));
        toast.warning(shortText(context.road_events[idx].title, 48), {
          description: context.road_events[idx].road_name,
          duration: 4000,
        });
      }, roadStart + idx * 300);
    }

    // Zones + button
    const zonesStart = roadStart + roadsToShow * 300 + 150;
    schedule(() => setRevealed((r) => ({ ...r, zones: true })), zonesStart);
    schedule(() => setRevealed((r) => ({ ...r, button: true })), zonesStart + 200);

    return () => {
      revealTimersRef.current.forEach(clearTimeout);
    };
  }, [context]);

  async function runWithBusy(key: string, task: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await task();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Operation failed.");
    } finally {
      setBusy(null);
    }
  }

  async function handleReset() {
    await runWithBusy("reset", async () => {
      await resetDemo();
      setAssessment(null);
      setActions([]);
      setApprovalOpen(false);
      setTraceOpen(false);
      const nextContext = await getCurrentIncident();
      setContext(nextContext);
    });
  }

  async function handleAssessment() {
    toast.dismiss("incident-alert");
    setBusy("assessment");
    setError(null);
    setStreamingEvents([]);
    setStreamingStep(null);
    setSlimContext(null);
    try {
      const result = await streamAssessment((event) => {
        if (event.type === "step") {
          setStreamingEvents((prev) => [...prev, event.event]);
          setStreamingStep((event.event.step as string) ?? null);
          if (event.slim_context) setSlimContext(event.slim_context);
        } else if (event.type === "thinking") {
          setStreamingStep(event.step);
        }
      });
      setAssessment(result);
      setContext(result.context);
      setActions(result.actions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assessment failed.");
    } finally {
      setBusy(null);
    }
  }

  async function handleApprove() {
    if (!assessment) return;
    await runWithBusy("approve", async () => {
      const result = await approveBundle(assessment.approval.approval_id);
      setActions(result.actions);
      setAssessment({ ...assessment, approval: result.approval, actions: result.actions });
      setApprovalOpen(false);
    });
  }

  async function handleExecute() {
    if (!assessment) return;
    await runWithBusy("execute", async () => {
      const result = await executeBundle(assessment.bundle_id);
      const nextActions = [...result.executed, ...result.failed, ...(result.skipped || [])];
      setActions(nextActions);
      setAssessment({ ...assessment, actions: nextActions });
    });
  }

  const executedCount = actions.filter((action) => ["executed", "sent"].includes(action.status)).length;
  const showInitialLoader = !error && (!context || initialLoadHold);
  const showGraph = assessment !== null || busy === "assessment" || streamingEvents.length > 0;

  return (
    <main className="h-screen overflow-hidden bg-[#0f171f] text-[#f5f8fa]">
      {showInitialLoader ? <InitialLoadingOverlay /> : null}

      <Topbar
        stage={stage}
        assessment={assessment}
        busy={busy}
        streamingStep={streamingStep}
        onReset={handleReset}
        onOpenTrace={() => setTraceOpen(true)}
      />

      <div className="mt-14 flex h-[calc(100vh-56px)] min-h-0 flex-row overflow-hidden">
        <aside className="h-[calc(100vh-56px)] w-[360px] flex-shrink-0 overflow-y-auto border-r border-[#293742] bg-[#1c2127]">
          {error ? (
            <div className="sticky top-0 z-20 bg-[#1c2127]">
              <Callout intent={Intent.DANGER} title="Error" className="m-3 text-xs">
                {shortText(error, 120)}
              </Callout>
            </div>
          ) : null}

          {stage === "incident" ? (
            <IncidentPanel
              context={context}
              assessment={assessment}
              busy={busy}
              revealed={revealed}
              onRunAssessment={handleAssessment}
            />
          ) : null}

          {stage === "assessing" ? (
            <AssessingPanel
              currentStep={streamingStep}
              repairDetected={streamingEvents.some((e) => (e.step as string) === "repair")}
            />
          ) : null}

          {stage === "reasoning" || stage === "approving" ? (
            <PlanPanel
              assessment={assessment}
              actions={actions}
              busy={busy}
              onOpenApproval={() => setApprovalOpen(true)}
              onExecute={handleExecute}
            />
          ) : null}

          {stage === "executed" ? (
            <ExecutedPanel actions={actions} busy={busy} onReset={handleReset} />
          ) : null}
        </aside>

        <section
          className="flex min-w-0 flex-1 bg-[#0b1117]"
          style={{ flexDirection: showGraph ? "row" : "column", height: "calc(100vh - 56px)" }}
        >
          {/* Map — always visible; narrower when graph is active */}
          <div
            className="relative min-h-0 overflow-hidden"
            style={{ width: showGraph ? "42%" : "100%", height: "100%", flexShrink: 0 }}
          >
            <MapPanel context={context} assessment={assessment} />
          </div>

          {/* Reasoning graph — fills remaining space side-by-side */}
          {showGraph ? (
            <div
              style={{
                flex: 1,
                minHeight: 0,
                minWidth: 0,
                display: "flex",
                flexDirection: "column",
                borderLeft: "1px solid #1a2530",
              }}
            >
              <ReasoningGraph
                assessment={assessment}
                streamingEvents={streamingEvents}
                slimContext={slimContext}
                busy={busy}
              />
            </div>
          ) : null}
        </section>
      </div>

      <ApprovalDialog
        isOpen={approvalOpen}
        assessment={assessment}
        actions={actions}
        busy={busy}
        onClose={() => setApprovalOpen(false)}
        onApprove={handleApprove}
      />

      <TraceDialog
        isOpen={traceOpen}
        assessment={assessment}
        onClose={() => setTraceOpen(false)}
      />

      <Toaster
        theme="dark"
        position="bottom-right"
        richColors
        toastOptions={{
          style: { fontFamily: "inherit" },
        }}
      />
    </main>
  );
}

function InitialLoadingOverlay() {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#1c2127]">
      <div className="text-center">
        <Spinner size={40} intent={Intent.DANGER} />
        <p className="m-0 mt-4 text-sm text-gray-400">Loading FireGuard...</p>
      </div>
    </div>
  );
}

type PartnerState = "idle" | "connected" | "active";

function PartnerBadge({ name, color, state }: { name: string; color: string; state: PartnerState }) {
  const dotColor = state === "idle" ? "#1e2d3d" : color;
  const textColor = state === "idle" ? "#293742" : state === "active" ? "#c0ccd8" : "#5c7080";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <span style={{
        width: 5, height: 5, borderRadius: "50%", background: dotColor, display: "inline-block", flexShrink: 0,
        animation: state === "active" ? "fg-blink 1.2s ease-in-out infinite" : "none",
      }} />
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.07em", color: textColor, userSelect: "none" }}>{name}</span>
    </div>
  );
}

function Topbar({
  stage,
  assessment,
  busy,
  streamingStep,
  onReset,
  onOpenTrace,
}: {
  stage: DemoStage;
  assessment: AssessmentResult | null;
  busy: string | null;
  streamingStep: string | null;
  onReset: () => void;
  onOpenTrace: () => void;
}) {
  const STEP_ORDER = ["observe", "retrieve", "assess", "route", "brief", "reason", "repair", "validate", "plan", "act", "approval", "compile"];
  const stepIdx = streamingStep ? STEP_ORDER.indexOf(streamingStep) : -1;
  const pastRetrieve = stepIdx > STEP_ORDER.indexOf("retrieve");

  const elasticState: PartnerState = busy === "assessment"
    ? (streamingStep === "retrieve" ? "active" : pastRetrieve ? "connected" : "idle")
    : assessment ? "connected" : "idle";

  const arizeState: PartnerState = assessment ? "active" : "idle";
  const fivetranState: PartnerState = "connected";

  return (
    <header className="fixed inset-x-0 top-0 z-40 flex h-14 items-center border-b border-[#293742] bg-[#1c2127] px-4">
      <div className="flex min-w-[300px] items-center gap-2">
        <Icon icon="shield" size={18} color="#e05a5a" />
        <span className="text-sm font-bold uppercase tracking-widest text-white">FireGuard</span>
        <span className="text-gray-700">·</span>
        <span className="text-xs text-gray-400">Wildfire Evacuation Agent</span>
        <span className="text-gray-700">·</span>
        <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "#4a7cbb" }}>Google Agent Builder</span>
      </div>

      <div className="flex flex-1 justify-center">
        <StepPills stage={stage} />
      </div>

      <div className="flex items-center justify-end gap-3">
        {/* Partner integration badges */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, paddingRight: 10, borderRight: "1px solid #1a2530" }}>
          <PartnerBadge name="Elastic" color="#00a1e0" state={elasticState} />
          <PartnerBadge name="Fivetran" color="#0073e6" state={fivetranState} />
          <PartnerBadge name="Arize" color="#9d4dce" state={arizeState} />
        </div>

        {assessment ? (
          <button
            onClick={onOpenTrace}
            style={{
              display: "flex", alignItems: "center", gap: 5,
              background: "#0e0520", border: "1px solid #4a2070", borderRadius: 3,
              color: "#c090ff", fontSize: 11, fontWeight: 700, letterSpacing: "0.06em",
              padding: "4px 9px", cursor: "pointer",
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
            Arize Trace
          </button>
        ) : null}

        {busy ? (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Spinner size={14} />
          </div>
        ) : null}

        <Button minimal small icon="refresh" text="Reset" onClick={onReset} disabled={Boolean(busy)} />
      </div>
    </header>
  );
}

function StepPills({ stage }: { stage: DemoStage }) {
  const currentStep = stage === "incident" ? 1 : stage === "assessing" ? 2 : (stage === "reasoning" || stage === "approving") ? 3 : 4;
  const steps = [
    { number: 1, label: "Incident" },
    { number: 2, label: "Assess" },
    { number: 3, label: "Respond" },
  ];

  return (
    <div className="flex items-center gap-0" aria-label="Steps">
      {steps.map((step, index) => {
        const active = currentStep === step.number;
        const completed = currentStep > step.number;
        const upcoming = !active && !completed;
        const circleClass = active
          ? "border-[#e05a5a] bg-[#e05a5a] text-white"
          : completed
            ? "border-[#394b59] bg-[#394b59] text-[#8a9ba8]"
            : "border-[#394b59] bg-transparent text-[#5c7080]";
        const labelClass = active ? "text-white" : completed ? "text-[#8a9ba8]" : "text-[#5c7080]";

        return (
          <div key={step.number} className="flex items-center">
            <div className="fg-step-pill">
              <span className={`fg-step-circle ${circleClass}`}>{step.number}</span>
              <span className={`text-xs uppercase tracking-wider ${labelClass}`}>{step.label}</span>
            </div>
            {index < steps.length - 1 ? (
              <span
                className={`fg-step-line ${completed ? "completed" : ""}`}
                style={{ background: upcoming ? "#293742" : completed || active ? "#394b59" : "#293742" }}
                aria-hidden="true"
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function IncidentPanel({
  context,
  assessment,
  busy,
  revealed,
  onRunAssessment,
}: {
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
  busy: string | null;
  revealed: { fires: number; roads: number; zones: boolean; button: boolean };
  onRunAssessment: () => void;
}) {
  const zoneRisks = assessment?.plan.zone_risks || [];
  const totalPop = (context?.zones || []).reduce((s, z) => s + z.population, 0);
  const totalVuln = (context?.zones || []).reduce((s, z) => s + z.vulnerable_count, 0);

  return (
    <div>
      <div className="fg-section-label !pt-6">Incident</div>

      {context && totalPop > 0 ? (
        <div style={{
          margin: "4px 20px 0",
          padding: "8px 12px",
          background: "#0e1820",
          border: "1px solid #1a2530",
          borderLeft: "2px solid #e05a5a",
          borderRadius: 3,
          display: "flex",
          gap: 16,
        }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, color: "#edf5ff", lineHeight: 1 }}>
              {totalPop >= 1000 ? `${(totalPop / 1000).toFixed(1)}k` : totalPop}
            </div>
            <div style={{ fontSize: 9, color: "#4a5c6a", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", marginTop: 2 }}>residents at risk</div>
          </div>
          <div style={{ width: 1, background: "#1a2530" }} />
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, color: "#f2b824", lineHeight: 1 }}>{totalVuln}</div>
            <div style={{ fontSize: 9, color: "#4a5c6a", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", marginTop: 2 }}>vulnerable</div>
          </div>
          <div style={{ width: 1, background: "#1a2530" }} />
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, color: "#c0a0ff", lineHeight: 1 }}>{context.zones.length}</div>
            <div style={{ fontSize: 9, color: "#4a5c6a", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", marginTop: 2 }}>zones</div>
          </div>
        </div>
      ) : null}

      <div className="space-y-3 px-5 pt-2">
        {(context?.fires || []).slice(0, revealed.fires).map((fire) => (
          <div key={fire.external_id} className="flex min-w-0 items-start gap-3 fg-reveal-item">
            <div className="mt-0.5 flex w-5 flex-shrink-0 items-center justify-center">
              <FireHotspotIcon />
            </div>
            <div className="min-w-0">
              <p className="m-0 text-sm font-medium text-white">Active hotspot</p>
              <p className="m-0 truncate text-xs text-gray-400">{fire.source} · FRP {fire.frp.toFixed(1)} MW</p>
            </div>
          </div>
        ))}
        {(context?.fires.length || 0) > 3 && revealed.fires >= 3 ? (
          <p className="m-0 text-xs text-gray-500 fg-reveal-item">+{(context?.fires.length || 0) - 3} more hotspots</p>
        ) : null}
      </div>

      <div className="mt-5 space-y-3 px-5">
        {(context?.road_events || []).slice(0, revealed.roads).map((event) => (
          <div key={event.external_id} className="flex min-w-0 items-start gap-3 fg-reveal-item">
            <div className="mt-0.5 flex w-5 flex-shrink-0 items-center justify-center">
              <Icon icon="warning-sign" size={14} color="#f2b824" />
            </div>
            <div className="min-w-0">
              <p className="m-0 truncate text-sm font-medium text-white">{shortText(event.title, 42)}</p>
              <p className="m-0 truncate text-xs text-gray-400">{event.road_name}</p>
            </div>
          </div>
        ))}
      </div>

      {revealed.zones ? (
        <div className="mt-5 space-y-3 px-5 fg-reveal-item">
          {(context?.zones || []).map((zone) => {
            const risk = zoneRisks.find((item) => item.zone_id === zone.zone_id);
            return (
              <div key={zone.zone_id} className="flex min-w-0 items-start gap-3">
                <div className="mt-0.5 flex w-5 flex-shrink-0 items-center justify-center">
                  <Icon icon="map-marker" size={13} color="#c0a0ff" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="m-0 truncate text-sm font-medium text-white">{zone.name}</p>
                    {risk ? (
                      <Tag className="!min-h-0 !px-1.5 !py-0 text-[10px]" intent={intentForRisk(risk.risk_level)}>
                        {risk.risk_level}
                      </Tag>
                    ) : null}
                  </div>
                  <p className="m-0 mt-0.5 text-xs text-gray-500">
                    Pop: {zone.population} · Vuln: {zone.vulnerable_count}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}

      <hr className="mx-5 my-4 border-gray-700" />

      {revealed.button ? (
        <div className="px-5 pb-6 fg-reveal-item">
          <Button
            large
            fill
            intent={Intent.DANGER}
            icon="predictive-analysis"
            text="Run Gemini Assessment"
            loading={busy === "assessment"}
            disabled={Boolean(busy) || !context}
            onClick={onRunAssessment}
          />
          <p className="m-0 mt-2 text-center text-xs text-gray-500">
            Gemini will reason from fire, route, shelter, and zone data
          </p>
        </div>
      ) : null}
    </div>
  );
}

function FireHotspotIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <path
        d="M12 2C9.5 5.5 9 8.5 11 12c-3-.5-4.5-3.5-3-6.5C5.5 8 4.5 12.5 6.5 16 8 18.5 10 20.5 12 20.5s5-3 5-7.5c0-3.5-2.5-7-5-11z"
        fill="#e05a5a"
      />
      <path
        d="M12 8.5c-.8 2-.5 4.5.5 5.5-2.5-.8-3-3-1.5-5 .5 1.5 1 3 1 3s2-2 0-3.5z"
        fill="#ffb366"
      />
    </svg>
  );
}

const STEP_LABELS: Record<string, string> = {
  observe: "Loading incident context...",
  retrieve: "Searching operational memory...",
  assess: "Computing zone risks...",
  route: "Computing evacuation routes...",
  brief: "Building operational brief...",
  reason: "Gemini is reasoning...",
  repair: "Repairing plan...",
  validate: "Validating plan...",
  plan: "Drafting evacuation plan...",
  act: "Creating action bundle...",
  approval: "Preparing approval request...",
  compile: "Compiling actions...",
};

const STEP_PARTNER: Record<string, { label: string; partner?: string; color?: string }> = {
  observe:  { label: "Reading incident context" },
  retrieve: { label: "Searching operational memory", partner: "Elastic", color: "#00a1e0" },
  assess:   { label: "Computing zone risk scores" },
  route:    { label: "Computing evacuation routes" },
  brief:    { label: "Building operational brief" },
  reason:   { label: "Gemini reasoning...", partner: "Gemini", color: "#8abbff" },
  repair:   { label: "Self-correcting plan", partner: "Gemini", color: "#f2b824" },
  validate: { label: "Validating plan constraints" },
  plan:     { label: "Drafting evacuation plan" },
  act:      { label: "Creating action bundle" },
  approval: { label: "Preparing commander approval" },
  compile:  { label: "Compiling final actions" },
};

function AssessingPanel({ currentStep, repairDetected }: { currentStep: string | null; repairDetected: boolean }) {
  const stepInfo = currentStep ? (STEP_PARTNER[currentStep] ?? { label: currentStep }) : null;
  return (
    <div className="px-5 pt-10">
      <div className="flex flex-col items-center text-center">
        <Spinner size={44} intent={Intent.DANGER} />
        <p className="m-0 mt-4 text-sm font-medium text-white">
          {currentStep === "reason" || currentStep === "repair" ? "Gemini is reasoning..." : "Agent running..."}
        </p>

        {stepInfo ? (
          <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 6 }}>
            <p className="m-0 text-xs text-gray-400">{stepInfo.label}</p>
            {stepInfo.partner ? (
              <span style={{
                fontSize: 9, fontWeight: 800, letterSpacing: "0.07em",
                color: stepInfo.color, background: `${stepInfo.color}15`,
                border: `1px solid ${stepInfo.color}40`,
                borderRadius: 2, padding: "1px 5px",
                animation: "fg-blink 1.2s ease-in-out infinite",
              }}>
                {stepInfo.partner}
              </span>
            ) : null}
          </div>
        ) : (
          <p className="m-0 mt-2 text-xs text-gray-600">Starting assessment...</p>
        )}

        {repairDetected ? (
          <div style={{
            marginTop: 12, display: "flex", alignItems: "center", gap: 5,
            background: "#0d1a0d", border: "1px solid #1a3a1a", borderRadius: 3,
            padding: "5px 10px",
          }}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#45d483" strokeWidth="2.5">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <span style={{ fontSize: 10, fontWeight: 700, color: "#45d483", letterSpacing: "0.06em" }}>
              Plan self-corrected
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

const RISK_ZONE_COLOR: Record<string, string> = {
  CRITICAL: "#db3737", HIGH: "#c87328", MODERATE: "#f2b824", LOW: "#3dcc91",
};

function ZoneMinimap({ zone, fires, riskLevel }: { zone: Zone; fires: FireHotspot[]; riskLevel?: string }) {
  const ring = zone?.geometry?.coordinates?.[0] as [number, number][] | undefined;
  if (!ring || ring.length < 3) return null;

  const W = 84, H = 58;
  const lons = ring.map((c) => c[0]);
  const lats = ring.map((c) => c[1]);
  const minLon = Math.min(...lons), maxLon = Math.max(...lons);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const lonRange = maxLon - minLon || 0.01;
  const latRange = maxLat - minLat || 0.01;
  const pad = 0.22;
  const vMinLon = minLon - lonRange * pad, vMaxLon = maxLon + lonRange * pad;
  const vMinLat = minLat - latRange * pad, vMaxLat = maxLat + latRange * pad;

  const px = (lon: number) => ((lon - vMinLon) / (vMaxLon - vMinLon)) * W;
  const py = (lat: number) => ((vMaxLat - lat) / (vMaxLat - vMinLat)) * H;

  const d = ring.map((c, i) => `${i === 0 ? "M" : "L"}${px(c[0]).toFixed(1)},${py(c[1]).toFixed(1)}`).join(" ") + " Z";
  const accent = RISK_ZONE_COLOR[riskLevel ?? ""] ?? "#7c4dce";

  const nearFires = fires.filter(
    (f) => f.location.lon >= vMinLon && f.location.lon <= vMaxLon && f.location.lat >= vMinLat && f.location.lat <= vMaxLat,
  );

  return (
    <svg
      width={W} height={H}
      style={{ flexShrink: 0, borderRadius: 3, border: `1px solid ${accent}50`, background: "#060b0f" }}
    >
      {/* Grid lines */}
      <line x1="0" y1={H / 2} x2={W} y2={H / 2} stroke="#0e1820" strokeWidth="0.5" />
      <line x1={W / 2} y1="0" x2={W / 2} y2={H} stroke="#0e1820" strokeWidth="0.5" />
      {/* Zone fill */}
      <path d={d} fill={`${accent}18`} stroke={accent} strokeWidth="1.2" strokeLinejoin="round" />
      {/* Fire dots */}
      {nearFires.slice(0, 12).map((f) => (
        <circle
          key={f.external_id}
          cx={px(f.location.lon).toFixed(1)}
          cy={py(f.location.lat).toFixed(1)}
          r="2.2"
          fill="#e05a5a"
          opacity="0.85"
        />
      ))}
      {/* Centroid pin */}
      <circle cx={px(zone.centroid.lon).toFixed(1)} cy={py(zone.centroid.lat).toFixed(1)} r="2.5" fill={accent} opacity="0.7" />
    </svg>
  );
}

function PlanPanel({
  assessment,
  actions,
  busy,
  onOpenApproval,
  onExecute,
}: {
  assessment: AssessmentResult | null;
  actions: ActionItem[];
  busy: string | null;
  onOpenApproval: () => void;
  onExecute: () => void;
}) {
  if (!assessment) return null;

  const confidence = assessment.plan.confidence;
  const confidenceIntent = confidence >= 0.8 ? Intent.SUCCESS : confidence >= 0.6 ? Intent.WARNING : Intent.DANGER;
  const confidenceClass = confidence >= 0.8 ? "text-green-400" : confidence >= 0.6 ? "text-yellow-400" : "text-red-400";
  const pendingApprovalCount = actions.filter((action) => action.requires_human_approval).length;
  const executedCount = actions.filter((action) => ["executed", "sent"].includes(action.status)).length;
  const strategy = {
    staged_evacuation: "Staged Evacuation",
    evacuate_now: "Evacuate Now",
    shelter_in_place: "Shelter in Place",
    monitor: "Monitor",
    dispatch_assisted: "Dispatch Assisted",
  }[assessment.plan.recommended_strategy] || assessment.plan.recommended_strategy.replaceAll("_", " ");

  const rejectedAlts = (assessment.plan.rejected_alternatives ?? []).slice(0, 3);
  const dataGaps: string[] = Array.isArray(assessment.gemini_decision?.data_gaps)
    ? (assessment.gemini_decision!.data_gaps as unknown[]).filter((g): g is string => typeof g === "string").slice(0, 3)
    : [];

  return (
    <div>
      <div className="fg-section-label !pt-6">Gemini Plan</div>

      <div className="px-5 pt-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="m-0 text-xl font-bold text-white">{strategy}</h2>
          <div className="flex items-center gap-2">
            <PlanningModeTag mode={assessment.planning_mode} />
            <span className={`text-xl font-bold ${confidenceClass}`}>{Math.round(confidence * 100)}%</span>
          </div>
        </div>
        <ProgressBar className="mt-1.5 h-1" value={confidence} intent={confidenceIntent} stripes={false} animate={false} />
      </div>

      <hr className="mx-5 my-4 border-gray-700" />

      <div className="px-5">
        {assessment.plan.steps.map((step) => {
          const zone = assessment.context.zones.find((z) => z.zone_id === step.zone_id);
          const risk = assessment.plan.zone_risks.find((r) => r.zone_id === step.zone_id);
          return (
            <div key={step.step_id} className="fg-step-card">
              <div className="flex items-start gap-3">
                {/* Minimap */}
                {zone ? (
                  <ZoneMinimap zone={zone} fires={assessment.context.fires} riskLevel={risk?.risk_level} />
                ) : null}
                {/* Text content */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="m-0 truncate text-sm font-medium text-white">{step.zone_id}</p>
                    <StrategyTag strategy={step.strategy} />
                  </div>
                  <p className="m-0 mt-1 text-xs text-gray-400">
                    {shortText(step.message.replace(/\[DEMO - FireGuard\] ?/g, ""), 68)}
                  </p>
                  {step.rationale?.[0] ? (
                    <p className="m-0 mt-1 text-xs italic text-gray-600">↳ {shortText(step.rationale[0], 60)}</p>
                  ) : null}
                  {step.start_after_minutes > 0 ? (
                    <p className="m-0 mt-1 text-xs text-blue-400">Starts +{step.start_after_minutes} min</p>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {rejectedAlts.length > 0 ? (
        <>
          <hr className="mx-5 my-3 border-gray-700" />
          <div className="px-5">
            <p className="m-0 mb-2 text-[10px] font-semibold uppercase tracking-widest text-gray-600">Considered &amp; Rejected</p>
            {rejectedAlts.map((alt, i) => (
              <div key={i} className="fg-rejected-row">
                <p className="m-0 font-mono text-xs text-red-400">
                  {stringify(alt.origin_id)} → {stringify(alt.destination_id, "none")}
                </p>
                <p className="m-0 mt-0.5 text-xs text-gray-500">{shortText(stringify(alt.reason ?? "", ""), 72)}</p>
              </div>
            ))}
          </div>
        </>
      ) : null}

      {dataGaps.length > 0 ? (
        <>
          <hr className="mx-5 my-3 border-gray-700" />
          <div className="px-5">
            <p className="m-0 mb-2 text-[10px] font-semibold uppercase tracking-widest text-gray-600">Data Gaps</p>
            {dataGaps.map((gap) => (
              <p key={gap} className="m-0 mb-1 flex items-start gap-1.5 text-xs text-yellow-600">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }}><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                {gap}
              </p>
            ))}
          </div>
        </>
      ) : null}

      <hr className="mx-5 my-4 border-gray-700" />

      <div className="px-5 pb-6">
        {assessment.plan.requires_approval && assessment.approval.status === "pending" ? (
          <>
            <Button
              fill
              intent={Intent.WARNING}
              icon="tick-circle"
              text="Review & Approve"
              loading={busy === "approve"}
              disabled={Boolean(busy)}
              onClick={onOpenApproval}
            />
            <p className="m-0 mt-1 text-center text-xs text-gray-500">
              {pendingApprovalCount} actions awaiting commander approval
            </p>
          </>
        ) : null}

        {assessment.approval.status === "approved" && executedCount === 0 ? (
          <Button
            fill
            intent={Intent.SUCCESS}
            icon="play"
            text="Execute Approved Actions"
            loading={busy === "execute"}
            disabled={Boolean(busy)}
            onClick={onExecute}
          />
        ) : null}
      </div>
    </div>
  );
}

function ExecutedPanel({
  actions,
  busy,
  onReset,
}: {
  actions: ActionItem[];
  busy: string | null;
  onReset: () => void;
}) {
  return (
    <div>
      <div className="fg-section-label !pt-6">Mission Complete</div>
      <div className="px-5 pt-8 text-center">
        <Icon icon="tick-circle" size={32} color="#3dcc91" />
        <p className="m-0 mt-3 text-lg font-bold text-white">Actions Dispatched</p>
        <p className="m-0 mt-2 text-xs text-gray-400">Commander-approved actions have been executed</p>
      </div>

      <div className="mt-6 space-y-3 px-5">
        {actions.map((action) => (
          <div key={action.action_id} className="flex items-center gap-3 border-b border-[#252e38] pb-3 last:border-b-0">
            <ActionTypeIcon actionType={action.action_type} />
            <div className="min-w-0 flex-1">
              <p className="m-0 truncate text-xs text-gray-300">{action.action_type}</p>
              <p className="m-0 truncate text-xs text-gray-500">{action.target}</p>
            </div>
            <Tag className="!min-h-0 !px-1.5 !py-0 text-[10px]" intent={intentForStatus(action.status)}>
              {action.status}
            </Tag>
          </div>
        ))}
      </div>

      <hr className="mx-5 my-4 border-gray-700" />

      <div className="px-5 pb-6">
        <Button minimal icon="refresh" text="Reset" onClick={onReset} disabled={Boolean(busy)} />
      </div>
    </div>
  );
}

function ApprovalDialog({
  isOpen,
  assessment,
  actions,
  busy,
  onClose,
  onApprove,
}: {
  isOpen: boolean;
  assessment: AssessmentResult | null;
  actions: ActionItem[];
  busy: string | null;
  onClose: () => void;
  onApprove: () => void;
}) {
  const approvalActions = actions.filter((action) => action.requires_human_approval);

  return (
    <Dialog
      className="bp6-dark"
      icon="tick-circle"
      isOpen={isOpen}
      onClose={onClose}
      title="Commander Approval Required"
      style={{ width: "540px" }}
    >
      <div className={Classes.DIALOG_BODY}>
        <Callout intent={Intent.WARNING} title="Public-facing actions require your approval">
          <p className="m-0 text-sm">
            The following actions will be dispatched to residents, shelters, and road operations upon approval. This cannot be undone.
          </p>
        </Callout>

        {assessment ? (
          <p className="m-0 mt-4 text-sm text-gray-300">{assessment.plan.summary}</p>
        ) : null}

        <div className="mt-4">
          {approvalActions.map((action) => (
            <div key={action.action_id} className="flex gap-3 border-b border-[#293742] py-2 last:border-b-0">
              <div className="pt-1">
                <ActionTypeIcon actionType={action.action_type} color="#5c7080" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="m-0 text-xs font-medium uppercase text-white">{action.action_type}</p>
                <p className="m-0 text-xs text-gray-400">→ {action.target}</p>
                <p
                  className="m-0 mt-1 text-xs text-gray-500"
                  style={{
                    display: "-webkit-box",
                    WebkitBoxOrient: "vertical",
                    WebkitLineClamp: 2,
                    overflow: "hidden",
                  }}
                >
                  {action.message.replace(/\[DEMO - FireGuard\] ?/g, "")}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className={Classes.DIALOG_FOOTER}>
        <div className={Classes.DIALOG_FOOTER_ACTIONS}>
          <Button minimal text="Cancel" onClick={onClose} disabled={Boolean(busy)} />
          <Button
            intent={Intent.WARNING}
            icon="tick"
            text="Approve and Proceed"
            loading={busy === "approve"}
            disabled={Boolean(busy)}
            onClick={onApprove}
          />
        </div>
      </div>
    </Dialog>
  );
}

const TRACE_STEP_META: Record<string, { label: string; partner?: string; color: string }> = {
  observe:  { label: "get_incident_context",        color: "#2d72d2" },
  retrieve: { label: "search_operational_memory",   partner: "Elastic", color: "#00a1e0" },
  assess:   { label: "compute_zone_risk",            color: "#f2b824" },
  route:    { label: "compute_routes",               color: "#48aff0" },
  brief:    { label: "operational_brief",            color: "#5c7080" },
  reason:   { label: "gemini_plan_decision",         partner: "Gemini", color: "#9d4dce" },
  repair:   { label: "gemini_repair",                partner: "Gemini", color: "#f2b824" },
  validate: { label: "plan_validation",              color: "#5c7080" },
  plan:     { label: "draft_evacuation_plan",        color: "#2a7a48" },
  act:      { label: "create_action_bundle",         color: "#2a7a48" },
  approval: { label: "request_human_approval",       color: "#c87328" },
  compile:  { label: "action_bundle_compile",        color: "#5c7080" },
};

function TraceDialog({
  isOpen,
  assessment,
  onClose,
}: {
  isOpen: boolean;
  assessment: AssessmentResult | null;
  onClose: () => void;
}) {
  if (!assessment) return null;

  const dec = assessment.gemini_decision ?? {};
  const incidentSummary = typeof dec.incident_summary === "string" ? dec.incident_summary : "";
  const toolCalls = assessment.gemini_tool_calls ?? [];
  const dataGaps: string[] = Array.isArray(dec.data_gaps)
    ? (dec.data_gaps as unknown[]).filter((g): g is string => typeof g === "string")
    : [];
  const risksIfWrong = assessment.plan.risks_if_wrong ?? [];
  const modelLabel = typeof (assessment.context.provider_status?.gemini as Record<string, unknown> | undefined)?.model === "string"
    ? String((assessment.context.provider_status.gemini as Record<string, unknown>).model)
    : "gemini-2.0-flash";
  const traceEvents = assessment.trace ?? [];
  const repaired = assessment.planning_mode === "gemini_repaired";

  return (
    <Dialog
      className="bp6-dark"
      isOpen={isOpen}
      onClose={onClose}
      title=""
      style={{ width: "720px", maxHeight: "85vh", padding: 0 }}
    >
      {/* Arize-branded header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "14px 20px 12px",
        background: "#0a0514",
        borderBottom: "1px solid #2a1850",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#9d4dce", animation: "fg-blink 2s ease-in-out infinite" }} />
          <span style={{ fontSize: 13, fontWeight: 800, color: "#edf5ff", letterSpacing: "0.02em" }}>Arize</span>
          <span style={{ fontSize: 11, color: "#5c7080" }}>AI Observability · LLM Trace</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 10, fontFamily: "monospace", color: "#4a2070", background: "#0e0520", border: "1px solid #2a1050", borderRadius: 2, padding: "2px 6px" }}>{modelLabel}</span>
          <span style={{ fontSize: 10, fontFamily: "monospace", color: "#1e3045", background: "#040a10", border: "1px solid #0e1c28", borderRadius: 2, padding: "2px 6px" }}>incident/{assessment.incident_id.slice(0, 12)}</span>
        </div>
      </div>

      <div className={Classes.DIALOG_BODY} style={{ maxHeight: "calc(85vh - 140px)", overflowY: "auto", padding: "16px 20px" }}>

        {/* Eval summary row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 20 }}>
          {[
            { label: "TRACE STEPS", value: String(traceEvents.length), color: "#48aff0" },
            { label: "TOOL CALLS", value: String(toolCalls.length), color: "#9d4dce" },
            { label: "CONFIDENCE", value: `${Math.round(assessment.plan.confidence * 100)}%`, color: assessment.plan.confidence >= 0.75 ? "#45d483" : "#f2b824" },
            { label: "PLAN STATUS", value: repaired ? "self-corrected" : "direct", color: repaired ? "#45d483" : "#48aff0" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ background: "#04080e", border: "1px solid #0e1820", borderRadius: 3, padding: "8px 12px" }}>
              <div style={{ fontSize: 8, fontWeight: 800, letterSpacing: "0.12em", color: "#293742", textTransform: "uppercase", marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 16, fontWeight: 800, color }}>{value}</div>
            </div>
          ))}
        </div>

        {/* Trace spans */}
        <div style={{ marginBottom: 4, fontSize: 9, fontWeight: 800, letterSpacing: "0.1em", color: "#293742", textTransform: "uppercase" }}>Trace Spans</div>
        <div style={{ border: "1px solid #0e1820", borderRadius: 3, overflow: "hidden", marginBottom: 20 }}>
          {traceEvents.map((event, i) => {
            const step = String(event.step ?? "");
            const tool = String(event.tool ?? step);
            const meta = TRACE_STEP_META[step] ?? { label: tool, color: "#293742" };
            const evidenceCount = Array.isArray(event.evidence_ids) ? (event.evidence_ids as unknown[]).length : 0;
            return (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "7px 12px",
                borderBottom: i < traceEvents.length - 1 ? "1px solid #080d12" : "none",
                background: i % 2 === 0 ? "#04080e" : "transparent",
              }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: meta.color, flexShrink: 0 }} />
                <span style={{ fontSize: 10, fontFamily: "monospace", color: "#c0ccd8", minWidth: 200 }}>{meta.label}</span>
                {meta.partner ? (
                  <span style={{ fontSize: 9, fontWeight: 700, color: meta.color, background: `${meta.color}15`, border: `1px solid ${meta.color}40`, borderRadius: 2, padding: "1px 5px", letterSpacing: "0.06em" }}>
                    {meta.partner}
                  </span>
                ) : null}
                <span style={{ marginLeft: "auto", fontSize: 10, color: "#293742", fontFamily: "monospace" }}>
                  {evidenceCount > 0 ? `${evidenceCount} refs` : ""}
                </span>
              </div>
            );
          })}
        </div>

        {/* Gemini assessment */}
        {incidentSummary ? (
          <>
            <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.1em", color: "#293742", textTransform: "uppercase", marginBottom: 6 }}>Gemini Assessment</div>
            <p className="m-0 mb-5 text-sm leading-relaxed text-gray-300">{incidentSummary}</p>
          </>
        ) : null}

        {/* Tool calls */}
        {toolCalls.length > 0 ? (
          <>
            <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.1em", color: "#293742", textTransform: "uppercase", marginBottom: 6 }}>Tool Calls</div>
            <div className="fg-tool-timeline mb-5">
              {toolCalls.map((tool, i) => (
                <div key={`${tool}-${i}`} className="fg-tool-item pb-3">
                  <span className="fg-tool-dot" />
                  <span className="font-mono text-xs text-blue-300">{tool}</span>
                </div>
              ))}
            </div>
          </>
        ) : null}

        {/* Data gaps */}
        {dataGaps.length > 0 ? (
          <>
            <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.1em", color: "#293742", textTransform: "uppercase", marginBottom: 6 }}>Data Gaps Identified</div>
            <div className="space-y-1 mb-5">
              {dataGaps.map((gap) => (
                <p key={gap} className="m-0 flex items-start gap-1.5 text-xs text-yellow-600">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }}><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                  {gap}
                </p>
              ))}
            </div>
          </>
        ) : null}

        {/* Risks if wrong */}
        {risksIfWrong.length > 0 ? (
          <>
            <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.1em", color: "#293742", textTransform: "uppercase", marginBottom: 6 }}>Risks if Wrong</div>
            <div className="space-y-1">
              {risksIfWrong.slice(0, 4).map((risk) => (
                <p key={risk} className="m-0 text-xs text-gray-500">· {risk}</p>
              ))}
            </div>
          </>
        ) : null}

        {assessment.validation_errors?.length ? (
          <>
            <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.1em", color: "#293742", textTransform: "uppercase", marginBottom: 6, marginTop: 16 }}>Validation Notes</div>
            <div className="space-y-1">
              {assessment.validation_errors.map((e) => (
                <p key={e} className="m-0 text-xs text-yellow-600">· {e}</p>
              ))}
            </div>
          </>
        ) : null}
      </div>
    </Dialog>
  );
}


function PlanningModeTag({ mode }: { mode?: AssessmentResult["planning_mode"] }) {
  if (mode === "gemini_selected") return <Tag minimal intent={Intent.SUCCESS}>Gemini</Tag>;
  if (mode === "gemini_repaired") return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      fontSize: 10, fontWeight: 700, color: "#45d483",
      background: "#0d2b1e", border: "1px solid #1a4a30",
      borderRadius: 3, padding: "2px 6px",
    }}>
      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12" /></svg>
      self-corrected
    </span>
  );
  return <Tag minimal intent={Intent.NONE}>fallback</Tag>;
}

function StrategyTag({ strategy }: { strategy: string }) {
  const intent = ["evacuate_now", "staged_evacuation"].includes(strategy)
    ? Intent.DANGER
    : ["shelter_in_place", "dispatch_assisted", "shelter_in_place_dispatch_assisted"].includes(strategy)
      ? Intent.WARNING
      : Intent.NONE;

  return (
    <Tag className="!min-h-0 !px-1.5 !py-0 text-[10px]" intent={intent}>
      {strategy}
    </Tag>
  );
}

function ActionTypeIcon({ actionType, color = "#cbd4dd" }: { actionType: string; color?: string }) {
  const icon =
    actionType === "resident_sms"
      ? "mobile-phone"
      : actionType === "shelter_notify"
        ? "home"
        : actionType === "road_ops_task"
          ? "road"
          : actionType === "dispatch_task"
            ? "drive-time"
            : "dot";

  return <Icon icon={icon as any} size={16} color={color} />;
}
