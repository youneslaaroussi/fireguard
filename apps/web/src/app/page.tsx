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
  runAssessment,
} from "@/lib/api";
import type { ActionItem, AssessmentResult, IncidentContext } from "@/lib/types";

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
    await runWithBusy("assessment", async () => {
      const result = await runAssessment();
      setAssessment(result);
      setContext(result.context);
      setActions(result.actions);
    });
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
  const showGraph = assessment !== null || busy === "assessment";

  return (
    <main className="h-screen overflow-hidden bg-[#0f171f] text-[#f5f8fa]">
      {showInitialLoader ? <InitialLoadingOverlay /> : null}

      <Topbar
        stage={stage}
        assessment={assessment}
        busy={busy}
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

          {stage === "assessing" ? <AssessingPanel /> : null}

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
              <ReasoningGraph assessment={assessment} busy={busy} />
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

function Topbar({
  stage,
  assessment,
  busy,
  onReset,
  onOpenTrace,
}: {
  stage: DemoStage;
  assessment: AssessmentResult | null;
  busy: string | null;
  onReset: () => void;
  onOpenTrace: () => void;
}) {
  const busyText: Record<string, string> = {
    reset: "Resetting...",
    assessment: "Gemini is reasoning...",
    approve: "Approving...",
    execute: "Executing...",
  };

  return (
    <header className="fixed inset-x-0 top-0 z-40 flex h-14 items-center border-b border-[#293742] bg-[#1c2127] px-4">
      <div className="flex min-w-[320px] items-center gap-2">
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

      <div className="flex min-w-[280px] items-center justify-end gap-2">
        {assessment ? (
          <Button minimal small icon="code-block" text="Trace" onClick={onOpenTrace} />
        ) : null}
        {busy ? (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Spinner size={16} />
            <span>{busyText[busy] || "Working..."}</span>
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
    <div className="flex items-center gap-0" aria-label="Demo steps">
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

  return (
    <div>
      <div className="fg-section-label !pt-6">Incident</div>

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

function AssessingPanel() {
  return (
    <div className="px-5 pt-10">
      <div className="flex flex-col items-center text-center">
        <Spinner size={44} intent={Intent.DANGER} />
        <p className="m-0 mt-4 text-sm font-medium text-white">Gemini is reasoning...</p>
        <p className="m-0 mt-2 text-xs text-gray-500">
          Fetching fire, route, shelter, and zone data
        </p>
        <p className="m-0 mt-1 text-xs text-gray-600">
          Reasoning trace will appear on the right
        </p>
      </div>
    </div>
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
        {assessment.plan.steps.map((step) => (
          <div key={step.step_id} className="fg-step-card">
            <div className="flex items-center justify-between gap-3">
              <p className="m-0 truncate text-sm font-medium text-white">{step.zone_id}</p>
              <StrategyTag strategy={step.strategy} />
            </div>
            <p className="m-0 mt-1 text-xs text-gray-400">
              {shortText(step.message.replace("[DEMO - FireGuard] ", ""), 72)}
            </p>
            {step.rationale?.[0] ? (
              <p className="m-0 mt-1 text-xs italic text-gray-600">↳ {shortText(step.rationale[0], 68)}</p>
            ) : null}
            {step.start_after_minutes > 0 ? (
              <p className="m-0 mt-1 text-xs text-blue-400">Starts +{step.start_after_minutes} min</p>
            ) : null}
          </div>
        ))}
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
              <p key={gap} className="m-0 mb-1 text-xs text-yellow-600">⚠ {gap}</p>
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
        <Button minimal icon="refresh" text="Reset Demo" onClick={onReset} disabled={Boolean(busy)} />
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
                  {action.message.replace("[DEMO - FireGuard] ", "")}
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
  const rejectedAlts = (assessment.plan.rejected_alternatives ?? []).slice(0, 5);
  const modelLabel = typeof (assessment.context.provider_status?.gemini as Record<string, unknown> | undefined)?.model === "string"
    ? String((assessment.context.provider_status.gemini as Record<string, unknown>).model)
    : "Gemini";

  return (
    <Dialog
      className="bp6-dark"
      isOpen={isOpen}
      onClose={onClose}
      title="Gemini Agent Trace"
      style={{ width: "720px", maxHeight: "80vh" }}
    >
      <div className={Classes.DIALOG_BODY} style={{ maxHeight: "calc(80vh - 120px)", overflowY: "auto" }}>
        {/* Header grid */}
        <div className="grid grid-cols-2 gap-4">
          <TraceSummaryItem label="Planning Mode">
            <PlanningModeTag mode={assessment.planning_mode} />
          </TraceSummaryItem>
          <TraceSummaryItem label="Model">
            <div className="flex items-center gap-2">
              <Tag minimal intent={Intent.PRIMARY}>{modelLabel}</Tag>
              <Tag minimal>Vertex AI</Tag>
            </div>
          </TraceSummaryItem>
          <TraceSummaryItem label="Confidence">
            <span className="text-sm">{Math.round(assessment.plan.confidence * 100)}%</span>
          </TraceSummaryItem>
          <TraceSummaryItem label="Validation">
            {assessment.plan_validation?.valid === true ? (
              <Tag intent={Intent.SUCCESS}>valid · {assessment.gemini_tool_calls?.length ?? 0} tool calls</Tag>
            ) : (
              <Tag intent={Intent.DANGER}>repair needed</Tag>
            )}
          </TraceSummaryItem>
        </div>

        {/* Incident summary */}
        {incidentSummary ? (
          <>
            <p className="m-0 mb-2 mt-5 text-[10px] font-semibold uppercase tracking-widest text-gray-500">Gemini Assessment</p>
            <p className="m-0 text-sm leading-relaxed text-gray-300">{incidentSummary}</p>
          </>
        ) : null}

        {/* Tool calls */}
        {toolCalls.length > 0 ? (
          <>
            <p className="m-0 mb-2 mt-5 text-[10px] font-semibold uppercase tracking-widest text-gray-500">Tool Calls</p>
            <div className="fg-tool-timeline">
              {toolCalls.map((tool, i) => (
                <div key={`${tool}-${i}`} className="fg-tool-item pb-3">
                  <span className="fg-tool-dot" />
                  <span className="font-mono text-xs text-blue-300">{tool}</span>
                </div>
              ))}
            </div>
          </>
        ) : null}

        {/* Plan steps */}
        {assessment.plan.steps.length > 0 ? (
          <>
            <p className="m-0 mb-2 mt-5 text-[10px] font-semibold uppercase tracking-widest text-gray-500">Plan Steps</p>
            <div className="space-y-2">
              {assessment.plan.steps.map((step) => (
                <div key={step.step_id} className="rounded-sm border border-[#252e38] px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-xs text-gray-300">{step.zone_id}</span>
                    <div className="flex items-center gap-2">
                      <StrategyTag strategy={step.strategy} />
                      <span className="text-xs text-gray-500">
                        {step.start_after_minutes > 0 ? `+${step.start_after_minutes} min` : "immediate"}
                      </span>
                    </div>
                  </div>
                  {step.rationale?.[0] ? (
                    <p className="m-0 mt-1 text-xs italic text-gray-600">↳ {step.rationale[0]}</p>
                  ) : null}
                </div>
              ))}
            </div>
          </>
        ) : null}

        {/* Rejected alternatives */}
        {rejectedAlts.length > 0 ? (
          <>
            <p className="m-0 mb-2 mt-5 text-[10px] font-semibold uppercase tracking-widest text-gray-500">Considered &amp; Rejected</p>
            <div className="space-y-2">
              {rejectedAlts.map((alt, i) => (
                <div key={i} className="rounded-sm border border-[#2a1818] px-3 py-2">
                  <p className="m-0 font-mono text-xs text-red-400">
                    {stringify(alt.origin_id)} → {stringify(alt.destination_id, "none")}
                  </p>
                  <p className="m-0 mt-1 text-xs text-gray-500">{stringify(alt.reason ?? "", "")}</p>
                </div>
              ))}
            </div>
          </>
        ) : null}

        {/* Data gaps */}
        {dataGaps.length > 0 ? (
          <>
            <p className="m-0 mb-2 mt-5 text-[10px] font-semibold uppercase tracking-widest text-gray-500">Data Gaps</p>
            <div className="space-y-1">
              {dataGaps.map((gap) => (
                <p key={gap} className="m-0 text-xs text-yellow-600">⚠ {gap}</p>
              ))}
            </div>
          </>
        ) : null}

        {/* Risks if wrong */}
        {risksIfWrong.length > 0 ? (
          <>
            <p className="m-0 mb-2 mt-5 text-[10px] font-semibold uppercase tracking-widest text-gray-500">Risks if Wrong</p>
            <div className="space-y-1">
              {risksIfWrong.slice(0, 4).map((risk) => (
                <p key={risk} className="m-0 text-xs text-gray-500">• {risk}</p>
              ))}
            </div>
          </>
        ) : null}

        {/* Validation notes */}
        {assessment.validation_errors?.length ? (
          <>
            <p className="m-0 mb-2 mt-5 text-[10px] font-semibold uppercase tracking-widest text-gray-500">Validation Notes</p>
            <div className="space-y-1">
              {assessment.validation_errors.map((validationError) => (
                <p key={validationError} className="m-0 text-xs text-yellow-600">• {validationError}</p>
              ))}
            </div>
          </>
        ) : null}
      </div>
    </Dialog>
  );
}

function TraceSummaryItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="m-0 text-xs text-gray-500">{label}</p>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function PlanningModeTag({ mode }: { mode?: AssessmentResult["planning_mode"] }) {
  if (mode === "gemini_selected") return <Tag minimal intent={Intent.SUCCESS}>Gemini · direct</Tag>;
  if (mode === "gemini_repaired") return <Tag minimal intent={Intent.WARNING}>Gemini · repaired</Tag>;
  return <Tag minimal intent={Intent.NONE}>no gemini</Tag>;
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
