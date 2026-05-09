"use client";

import {
  Button,
  ButtonGroup,
  Callout,
  Classes,
  Dialog,
  H4,
  H5,
  InputGroup,
  Intent,
  NonIdealState,
  ProgressBar,
  Tag,
} from "@blueprintjs/core";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import { MapPanel } from "@/components/MapPanel";
import { approveBundle, confirmShelterCapacity, executeBundle, getCurrentIncident, getIntegrationStatus, getTraces, registerResidentTestContact, resetDemo, runAssessment, runEval, syncFivetranToElastic, syncLiveOverlay, syncShelterCapacitySheet, syncSourceBackedZoneContext } from "@/lib/api";
import type { ActionItem, AssessmentResult, IncidentContext, IntegrationStatus, Shelter, ZoneRisk } from "@/lib/types";

type ActivePane = "overview" | "sources" | "evidence" | "actions" | "audit" | "diagnostics";
type DemoStage = "observe" | "collect" | "alert" | "agent" | "approve" | "audit";

const DEMO_STAGES: Array<{ id: DemoStage; label: string; icon: string }> = [
  { id: "observe", label: "Observe", icon: "eye-open" },
  { id: "collect", label: "Collect", icon: "satellite" },
  { id: "alert", label: "Alert", icon: "warning-sign" },
  { id: "agent", label: "Agent", icon: "predictive-analysis" },
  { id: "approve", label: "Approve", icon: "confirm" },
  { id: "audit", label: "Audit", icon: "path-search" },
];

const STAGE_COPY: Record<DemoStage, { label: string; headline: string; detail: string; intent: Intent }> = {
  observe: {
    label: "Observe",
    headline: "Start with the operational picture",
    detail: "Map, replay decision context, and live/open overlay records are loaded before the agent runs.",
    intent: Intent.NONE,
  },
  collect: {
    label: "Collect",
    headline: "Refresh live operational feeds",
    detail: "Pull current Fivetran warehouse records into the live overlay without changing the replay decision evidence.",
    intent: Intent.PRIMARY,
  },
  alert: {
    label: "Alert",
    headline: "Situation alert active",
    detail: "Operational conflict detected across fire, route, and shelter-capacity constraints.",
    intent: Intent.WARNING,
  },
  agent: {
    label: "Agent",
    headline: "Gemini composes the evacuation strategy",
    detail: "The backend gives facts, routes, risks, and constraints; Gemini chooses the staged plan; validation guards execution.",
    intent: Intent.DANGER,
  },
  approve: {
    label: "Approve",
    headline: "Approval gate is active",
    detail: "Public-facing and dispatch-like actions are held until the commander approves the bundle.",
    intent: Intent.WARNING,
  },
  audit: {
    label: "Audit",
    headline: "Actions and evidence are traceable",
    detail: "Tool calls, validation, Phoenix/Arize span IDs, eval checks, and action results are available for review.",
    intent: Intent.SUCCESS,
  },
};

function intentForRisk(level: string): Intent {
  if (level === "CRITICAL" || level === "HIGH") return Intent.DANGER;
  if (level === "MODERATE") return Intent.WARNING;
  return Intent.SUCCESS;
}

function intentForStatus(status: string): Intent {
  if (["executed", "approved", "sent", "ok", "completed", "synced"].includes(status)) return Intent.SUCCESS;
  if (["failed", "rejected", "error"].includes(status)) return Intent.DANGER;
  if (["pending", "queued", "attention"].includes(status)) return Intent.WARNING;
  return Intent.NONE;
}

function planningModeText(mode?: string) {
  if (mode === "gemini_selected") return "Gemini selected";
  if (mode === "gemini_repaired") return "Gemini repaired";
  if (mode === "deterministic_fallback") return "Fallback";
  return "not run";
}

function intentForPlanningMode(mode?: string): Intent {
  if (mode === "gemini_selected" || mode === "gemini_repaired") return Intent.SUCCESS;
  if (mode === "deterministic_fallback") return Intent.WARNING;
  return Intent.NONE;
}

function shortText(value: string, maxLength: number) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
}

function stringify(value: unknown, fallback = "unknown") {
  if (value === undefined || value === null || value === "") return fallback;
  return String(value);
}

function operatorText(value: string) {
  return value
    .replaceAll("source-backed", "current operational")
    .replaceAll("FireGuard is logging an internal monitoring update instead of sending", "The system will record a monitoring update and will not send")
    .replaceAll("public evacuation instruction drafted", "public evacuation instruction recommended")
    .replaceAll("current current", "current");
}

function publicValidationErrorText(value: string) {
  const normalized = value.toLowerCase();
  if (normalized.includes("resource_exhausted") || normalized.includes("429")) {
    return "Gemini planning is temporarily rate-limited. Backend fallback is active and public actions remain locked.";
  }
  if (normalized.includes("cancelled") || normalized.includes("499")) {
    return "Gemini planning did not complete. Backend fallback is active and public actions remain locked.";
  }
  if (normalized.includes("geminiplandecision") || normalized.includes("validation error")) {
    return "Gemini returned a planning response that failed the contract. The backend rejected it.";
  }
  if (normalized.includes("unsafe route")) {
    return "Gemini selected a route that is not marked safe. The backend rejected it.";
  }
  if (normalized.includes("closed shelter")) {
    return "Gemini selected an unavailable shelter. The backend rejected it.";
  }
  return operatorText(value);
}

function decisionRecordCount(context: IncidentContext | null) {
  if (!context) return 0;
  return context.fires.length + context.perimeters.length + context.road_events.length + context.zones.length + context.shelters.length;
}

function liveOverlayRecordCount(context: IncidentContext | null) {
  if (!context?.live_context) return 0;
  const counts = context.live_context.record_counts || {};
  const counted = Object.values(counts).reduce((total, value) => total + Number(value || 0), 0);
  if (counted) return counted;
  return context.live_context.fires.length + context.live_context.perimeters.length + context.live_context.road_events.length;
}

function inferDemoStage({
  context,
  assessment,
  actions,
  busy,
  executedCount,
}: {
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
  actions: ActionItem[];
  busy: string | null;
  executedCount: number;
}): DemoStage {
  if (executedCount > 0) return "audit";
  if (assessment?.approval.status === "approved") return "audit";
  if (assessment || actions.length) return "approve";
  if (busy === "assessment") return "agent";
  if (liveOverlayRecordCount(context) > 0) return "alert";
  if (context) return "collect";
  return "observe";
}

export default function Home() {
  const [context, setContext] = useState<IncidentContext | null>(null);
  const [assessment, setAssessment] = useState<AssessmentResult | null>(null);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [traceEvents, setTraceEvents] = useState<Array<Record<string, unknown>>>([]);
  const [integrationStatus, setIntegrationStatus] = useState<IntegrationStatus | null>(null);
  const [evalResult, setEvalResult] = useState<Record<string, unknown> | null>(null);
  const [contactInputs, setContactInputs] = useState<Record<string, string>>({});
  const [activePane, setActivePane] = useState<ActivePane>("overview");
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [situationOpen, setSituationOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [initialLoadHold, setInitialLoadHold] = useState(true);

  const load = async () => {
    const [nextContext, nextStatus] = await Promise.all([getCurrentIncident(), getIntegrationStatus()]);
    setContext(nextContext);
    setIntegrationStatus(nextStatus);
  };

  useEffect(() => {
    load().catch((err: Error) => {
      console.error(err);
      setError("The latest incident data could not be loaded. Open diagnostics for system status.");
    });
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setInitialLoadHold(false), 1600);
    return () => window.clearTimeout(timer);
  }, []);

  const rejectedRoute = useMemo(() => {
    return assessment?.plan.rejected_alternatives.find((item) => String(item.reason || "").toLowerCase().includes("closure") || String(item.reason || "").toLowerCase().includes("risk"));
  }, [assessment]);

  const assumptionsToShow = useMemo(() => {
    return [...(context?.operational_assumptions || [])].sort((a, b) => Number(Boolean(b.blocks_execution)) - Number(Boolean(a.blocks_execution)));
  }, [context]);

  const publicActionCount = useMemo(() => actions.filter((action) => action.requires_human_approval).length, [actions]);
  const executedCount = useMemo(() => actions.filter((action) => ["executed", "sent"].includes(action.status)).length, [actions]);
  const traceSource = traceEvents.length ? traceEvents : assessment?.trace || [];
  const inferredDemoStage = useMemo(
    () => inferDemoStage({ context, assessment, actions, busy, executedCount }),
    [context, assessment, actions, busy, executedCount],
  );
  const demoStage: DemoStage = busy === "assessment" ? "agent" : situationOpen ? "alert" : inferredDemoStage;
  const showInitialLoader = !error && (!context || initialLoadHold);

  async function runWithBusy(key: string, task: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await task();
    } catch (err) {
      console.error(err);
      setError("The operation did not complete. Open diagnostics for the latest system status.");
    } finally {
      setBusy(null);
    }
  }

  async function handleReset() {
    await runWithBusy("reset", async () => {
      await resetDemo();
      setAssessment(null);
      setActions([]);
      setTraceEvents([]);
      setEvalResult(null);
      setApprovalOpen(false);
      setSituationOpen(false);
      setTraceOpen(false);
      await load();
    });
  }

  async function handleAssessment() {
    await runWithBusy("assessment", async () => {
      const result = await runAssessment();
      setAssessment(result);
      setContext(result.context);
      setActions(result.actions);
      setTraceEvents(result.trace);
      setEvalResult(await runEval(result.incident_id));
      setIntegrationStatus(await getIntegrationStatus());
      setSituationOpen(false);
      setTraceOpen(true);
    });
  }

  async function handleApprove() {
    if (!assessment) return;
    await runWithBusy("approve", async () => {
      const result = await approveBundle(assessment.approval.approval_id);
      setActions(result.actions);
      setAssessment({ ...assessment, approval: result.approval, actions: result.actions });
      setApprovalOpen(false);
      setActivePane("actions");
    });
  }

  async function handleExecute() {
    if (!assessment) return;
    await runWithBusy("execute", async () => {
      const result = await executeBundle(assessment.bundle_id);
      const nextActions = [...result.executed, ...result.failed, ...(result.skipped || [])];
      setActions(nextActions);
      setAssessment({ ...assessment, actions: nextActions });
      const traces = await getTraces(assessment.incident_id);
      setTraceEvents(traces.latest?.events || traceEvents);
      setEvalResult(await runEval(assessment.incident_id));
      setIntegrationStatus(await getIntegrationStatus());
      setActivePane("audit");
      setTraceOpen(true);
    });
  }

  async function handleFivetranSync() {
    await runWithBusy("fivetran", async () => {
      await syncFivetranToElastic();
      await load();
    });
  }

  async function handleLiveOverlaySync() {
    await runWithBusy("live-overlay", async () => {
      await syncLiveOverlay();
      await load();
      setSituationOpen(true);
    });
  }

  async function handleShelterCapacitySheetSync() {
    await runWithBusy("shelter-sheet", async () => {
      await syncShelterCapacitySheet();
      await load();
      setActivePane("sources");
    });
  }

  async function handleSourceZoneContextSync() {
    await runWithBusy("source-zone-context", async () => {
      await syncSourceBackedZoneContext();
      await load();
      setActivePane("sources");
    });
  }

  async function handleCapacityConfirm(shelter: Shelter) {
    await runWithBusy(`capacity-${shelter.shelter_id}`, async () => {
      await confirmShelterCapacity(shelter.shelter_id, shelter.capacity_available, shelter.capacity_total);
      await load();
    });
  }

  async function handleContactCheckIn(zoneId: string) {
    const phone = contactInputs[zoneId]?.trim();
    if (!phone) return;
    await runWithBusy(`contact-${zoneId}`, async () => {
      await registerResidentTestContact(zoneId, phone);
      setContactInputs((current) => ({ ...current, [zoneId]: "" }));
      await load();
    });
  }

  return (
    <main className="fireguard-shell text-[#f5f8fa]">
      <OpsTopbar
        stage={demoStage}
        hasAssessment={Boolean(assessment)}
        busy={busy}
        onReset={handleReset}
        onOpenTrace={() => setTraceOpen(true)}
      />

      {error ? (
        <div className="px-3 pt-3">
          <Callout intent={Intent.DANGER} icon="error" title="Action needed">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>{error}</span>
              <Button small icon="layers" text="Open diagnostics" onClick={() => setActivePane("diagnostics")} />
            </div>
          </Callout>
        </div>
      ) : null}

      {showInitialLoader ? (
        <InitialLoadingScreen />
      ) : (
        <div className="ops-body">
          <OpsRail
            activePane={activePane}
            onSelectPane={setActivePane}
          />
          <div className="ops-grid">
            <div className="ops-left-stack">
              <LeftOpsPanel
                activePane={activePane}
                status={integrationStatus}
                evalResult={evalResult}
                context={context}
                assessment={assessment}
                actions={actions}
                assumptions={assumptionsToShow}
                contactInputs={contactInputs}
                rejectedRoute={rejectedRoute}
                publicActionCount={publicActionCount}
                executedCount={executedCount}
                busy={busy}
                traceEvents={traceSource}
                stage={demoStage}
                onOpenApproval={() => setApprovalOpen(true)}
                onOpenSituationAlert={() => setSituationOpen(true)}
                onOpenTrace={() => setTraceOpen(true)}
                onRunAssessment={handleAssessment}
                onRefreshFeeds={handleFivetranSync}
                onRefreshLiveOverlay={handleLiveOverlaySync}
                onRefreshShelters={handleShelterCapacitySheetSync}
                onRefreshZones={handleSourceZoneContextSync}
                onContactChange={(zoneId, phone) => setContactInputs((current) => ({ ...current, [zoneId]: phone }))}
                onContactCheckIn={handleContactCheckIn}
                onCapacityConfirm={handleCapacityConfirm}
                onExecute={handleExecute}
              />
            </div>
            <CenterOpsArea context={context} assessment={assessment} actions={actions} />
            <RightOpsPanel
              status={integrationStatus}
              evalResult={evalResult}
              context={context}
              assessment={assessment}
              actions={actions}
              stage={demoStage}
            />
          </div>
        </div>
      )}

      <ApprovalDialog
        isOpen={approvalOpen}
        assessment={assessment}
        busy={busy}
        onClose={() => setApprovalOpen(false)}
        onApprove={handleApprove}
      />
      <SituationAlertDialog
        isOpen={situationOpen}
        context={context}
        assessment={assessment}
        rejectedRoute={rejectedRoute}
        busy={busy}
        onClose={() => setSituationOpen(false)}
        onRunAssessment={handleAssessment}
      />
      <AgentTraceDialog
        isOpen={traceOpen}
        assessment={assessment}
        traceEvents={traceSource}
        evalResult={evalResult}
        onClose={() => setTraceOpen(false)}
      />
    </main>
  );
}

function InitialLoadingScreen() {
  return (
    <section className="fireguard-loading-screen">
      <div className="fireguard-loading-panel">
        <p className="ops-section-kicker">Initializing</p>
        <H4 className="m-0">Loading operational picture</H4>
        <p className="m-0 text-sm leading-5 text-[#abb3bf]">
          Preparing the incident view.
        </p>
        <ProgressBar className="fireguard-loading-bar" intent={Intent.PRIMARY} />
      </div>
    </section>
  );
}

function OpsTopbar({
  stage,
  hasAssessment,
  busy,
  onReset,
  onOpenTrace,
}: {
  stage: DemoStage;
  hasAssessment: boolean;
  busy: string | null;
  onReset: () => void;
  onOpenTrace: () => void;
}) {
  return (
    <header className="ops-topbar">
      <div className="ops-brand">
        <span className="ops-brand-mark">
          <img src="/brand/fireguard-logo-web.png" alt="" />
        </span>
        <span className="font-semibold">FireGuard</span>
      </div>
      <DemoStepStrip stage={stage} />
      <ButtonGroup minimal className="ops-toolbar-group">
        <a className="ops-github-link" href="https://github.com/youneslaaroussi/fireguard" target="_blank" rel="noreferrer" aria-label="Open FireGuard on GitHub">
          <span aria-hidden className="bp6-icon bp6-icon-git-repo" />
          <span>GitHub</span>
        </a>
        <Button icon="refresh" text="Reset" loading={busy === "reset"} disabled={busy !== null} onClick={onReset} />
        <Button icon="path-search" text="Trace" disabled={!hasAssessment} onClick={onOpenTrace} />
      </ButtonGroup>
    </header>
  );
}

function DemoStepStrip({ stage }: { stage: DemoStage }) {
  const currentIndex = DEMO_STAGES.findIndex((item) => item.id === stage);
  return (
    <div className="ops-status-strip" aria-label="Operational workflow">
      {DEMO_STAGES.map((item, index) => {
        const active = item.id === stage;
        const complete = index < currentIndex;
        return (
          <div key={item.id} className={`ops-step-pill ${active ? "ops-step-active" : ""} ${complete ? "ops-step-complete" : ""}`} title={item.label} aria-label={item.label}>
            <span aria-hidden className={`bp6-icon bp6-icon-${item.icon}`} />
          </div>
        );
      })}
    </div>
  );
}

function OpsRail({
  activePane,
  onSelectPane,
}: {
  activePane: ActivePane;
  onSelectPane: (pane: ActivePane) => void;
}) {
  return (
    <nav className="ops-rail" aria-label="FireGuard tools">
      <Button active={activePane === "overview"} minimal icon="dashboard" title="Overview" onClick={() => onSelectPane("overview")} />
      <Button active={activePane === "sources"} minimal icon="map" title="Data sources" onClick={() => onSelectPane("sources")} />
      <Button active={activePane === "evidence"} minimal icon="timeline-events" title="Evidence" onClick={() => onSelectPane("evidence")} />
      <Button active={activePane === "actions"} minimal icon="send-message" title="Actions" onClick={() => onSelectPane("actions")} />
      <Button active={activePane === "audit"} minimal icon="path-search" title="Audit" onClick={() => onSelectPane("audit")} />
      <Button active={activePane === "diagnostics"} minimal icon="layers" title="Diagnostics" onClick={() => onSelectPane("diagnostics")} />
    </nav>
  );
}

function LeftOpsPanel({
  activePane,
  status,
  evalResult,
  context,
  assessment,
  actions,
  assumptions,
  contactInputs,
  rejectedRoute,
  publicActionCount,
  executedCount,
  busy,
  traceEvents,
  stage,
  onOpenApproval,
  onOpenSituationAlert,
  onOpenTrace,
  onRunAssessment,
  onRefreshFeeds,
  onRefreshLiveOverlay,
  onRefreshShelters,
  onRefreshZones,
  onContactChange,
  onContactCheckIn,
  onCapacityConfirm,
  onExecute,
}: {
  activePane: ActivePane;
  status: IntegrationStatus | null;
  evalResult: Record<string, unknown> | null;
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
  actions: ActionItem[];
  assumptions: Record<string, unknown>[];
  contactInputs: Record<string, string>;
  rejectedRoute?: Record<string, unknown>;
  publicActionCount: number;
  executedCount: number;
  busy: string | null;
  traceEvents: Array<Record<string, unknown>>;
  stage: DemoStage;
  onOpenApproval: () => void;
  onOpenSituationAlert: () => void;
  onOpenTrace: () => void;
  onRunAssessment: () => void;
  onRefreshFeeds: () => void;
  onRefreshLiveOverlay: () => void;
  onRefreshShelters: () => void;
  onRefreshZones: () => void;
  onContactChange: (zoneId: string, phone: string) => void;
  onContactCheckIn: (zoneId: string) => void;
  onCapacityConfirm: (shelter: Shelter) => void;
  onExecute: () => void;
}) {
  const paneTitle = {
    overview: "Command",
    sources: "Sources",
    evidence: "Evidence",
    actions: "Actions",
    audit: "Audit",
    diagnostics: "Diagnostics",
  }[activePane];
  const renderPane = () => {
    if (activePane === "sources") {
      return (
        <ContextDetails
          context={context}
          assumptions={assumptions}
          contactInputs={contactInputs}
          busy={busy}
          onRefreshFeeds={onRefreshFeeds}
          onRefreshLiveOverlay={onRefreshLiveOverlay}
          onRefreshShelters={onRefreshShelters}
          onRefreshZones={onRefreshZones}
          onContactChange={onContactChange}
          onContactCheckIn={onContactCheckIn}
          onCapacityConfirm={onCapacityConfirm}
        />
      );
    }
    if (activePane === "evidence") return <PlanDetails assessment={assessment} />;
    if (activePane === "actions") return <ActionDetails actions={actions} assessment={assessment} busy={busy} onExecute={onExecute} />;
    if (activePane === "audit") return <AuditDetails traceEvents={traceEvents} evalResult={evalResult} assessment={assessment} />;
    if (activePane === "diagnostics") return <ProviderDetails status={status} evalResult={evalResult} />;
    return (
      <CommandPanel
        context={context}
        assessment={assessment}
        actions={actions}
        assumptions={assumptions}
        rejectedRoute={rejectedRoute}
        publicActionCount={publicActionCount}
        executedCount={executedCount}
        busy={busy}
        stage={stage}
        onOpenApproval={onOpenApproval}
        onOpenSituationAlert={onOpenSituationAlert}
        onOpenTrace={onOpenTrace}
        onRunAssessment={onRunAssessment}
        onRefreshLiveOverlay={onRefreshLiveOverlay}
        onRefreshFeeds={onRefreshFeeds}
        onExecute={onExecute}
      />
    );
  };

  return (
    <aside className="fireguard-command-panel">
      <div className="ops-pane-header">
        <div>
          <H5 className="m-0">{paneTitle}</H5>
        </div>
        {assessment ? <Tag minimal intent={Intent.SUCCESS}>assessed</Tag> : null}
      </div>
      <div className="ops-pane-content">{renderPane()}</div>
    </aside>
  );
}

function CommandPanel({
  context,
  assessment,
  actions,
  assumptions,
  rejectedRoute,
  publicActionCount,
  executedCount,
  busy,
  stage,
  onOpenApproval,
  onOpenSituationAlert,
  onOpenTrace,
  onRunAssessment,
  onRefreshLiveOverlay,
  onRefreshFeeds,
  onExecute,
}: {
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
  actions: ActionItem[];
  assumptions: Record<string, unknown>[];
  rejectedRoute?: Record<string, unknown>;
  publicActionCount: number;
  executedCount: number;
  busy: string | null;
  stage: DemoStage;
  onOpenApproval: () => void;
  onOpenSituationAlert: () => void;
  onOpenTrace: () => void;
  onRunAssessment: () => void;
  onRefreshLiveOverlay: () => void;
  onRefreshFeeds: () => void;
  onExecute: () => void;
}) {
  const plan = assessment?.plan;
  const approved = assessment?.approval.status === "approved";
  const blockers = assumptions.filter((item) => item.blocks_execution).length;
  const validationPassed = assessment?.plan_validation?.valid === true;
  const stageCopy = STAGE_COPY[stage];
  const decisionRecords = decisionRecordCount(context);
  const liveRecords = liveOverlayRecordCount(context);
  const publicLocked = !assessment || assessment.approval.status !== "approved";

  return (
    <PaneBody>
      <div className="fireguard-command-overview">
        <section className="fireguard-hero-command">
          <div>
            <H4 className="m-0">{plan ? plan.recommended_strategy.replaceAll("_", " ") : stageCopy.headline}</H4>
            <p className="m-0 mt-2 text-sm leading-5 text-[#b8c7d6]">
              Refresh inputs, inspect the alert, run Gemini, then approve or hold the action bundle.
            </p>
          </div>
          <Tag intent={stageCopy.intent}>{stageCopy.label}</Tag>
        </section>

        <section className="fireguard-command-section fireguard-command-step">
          <div className="fireguard-command-step-head">
            <div>
              <span>01</span>
              <H5 className="m-0">Inputs</H5>
            </div>
            <Tag minimal>{decisionRecords + liveRecords} records</Tag>
          </div>
          <p className="fireguard-command-step-copy">
            Decision evidence stays separate from current situational awareness.
          </p>
          <div className="grid grid-cols-4 gap-2">
            <MiniMetric label="Decision" value={decisionRecords} intent={Intent.PRIMARY} />
            <MiniMetric label="Current" value={liveRecords} intent={Intent.SUCCESS} />
            <MiniMetric label="Roads" value={context?.road_events.length ?? 0} intent={Intent.WARNING} />
            <MiniMetric label="ESS" value={context?.shelters.length ?? 0} intent={Intent.PRIMARY} />
          </div>
          <div className="mt-3 grid gap-2">
            <Button icon="satellite" text="Collect live overlay" loading={busy === "live-overlay"} disabled={busy !== null} onClick={onRefreshLiveOverlay} />
            <Button icon="database" text="Sync decision feeds" loading={busy === "fivetran"} disabled={busy !== null} onClick={onRefreshFeeds} />
          </div>
        </section>

        <section className="fireguard-command-section fireguard-command-step">
          <div className="fireguard-command-step-head">
            <div>
              <span>02</span>
              <H5 className="m-0">Situation</H5>
            </div>
            <Tag intent={blockers ? Intent.WARNING : Intent.PRIMARY}>{blockers} blockers</Tag>
          </div>
          <p className="fireguard-command-step-copy">
            Review conflicts before planning: route closures, shelter state, and source gaps.
          </p>
          <Button icon="warning-sign" text="Open situation alert" intent={Intent.WARNING} disabled={!context || busy !== null} onClick={onOpenSituationAlert} />
          {rejectedRoute ? (
            <div className="fireguard-alert-line mt-3">
              <span aria-hidden className="bp6-icon bp6-icon-blocked-person" />
              <p>{shortText(String(rejectedRoute.reason), 190)}</p>
            </div>
          ) : null}
          {assumptions.length ? (
            <Callout className="mt-3" compact intent={blockers ? Intent.WARNING : Intent.PRIMARY} icon="info-sign">
              {assumptions.length} input{assumptions.length === 1 ? "" : "s"} require review.
            </Callout>
          ) : null}
        </section>

        <section className="fireguard-command-section fireguard-command-step">
          <div className="fireguard-command-step-head">
            <div>
              <span>03</span>
              <H5 className="m-0">Agent</H5>
            </div>
            {assessment ? <Tag intent={intentForPlanningMode(assessment.planning_mode)}>{planningModeText(assessment.planning_mode)}</Tag> : <Tag minimal>ready</Tag>}
          </div>
          <p className="fireguard-command-step-copy">
            Gemini chooses sequence, destinations, messages, and rejected alternatives. Backend validation gates the result.
          </p>
          <Button
            large
            icon="play"
            text={plan ? "Run reassessment" : "Run Gemini agent"}
            intent={Intent.DANGER}
            loading={busy === "assessment"}
            disabled={busy !== null}
            onClick={onRunAssessment}
          />
          {plan ? (
            <div className="fireguard-decision-block mt-3">
              <div className="flex flex-wrap gap-2">
                <Tag intent={plan.recommended_strategy === "monitor" ? Intent.PRIMARY : Intent.WARNING}>
                  {plan.recommended_strategy.replaceAll("_", " ")}
                </Tag>
                <Tag intent={validationPassed ? Intent.SUCCESS : Intent.WARNING}>{validationPassed ? "validated" : "guarded"}</Tag>
                <Tag minimal intent={publicLocked ? Intent.WARNING : Intent.SUCCESS}>{publicLocked ? "locked" : "approved"}</Tag>
              </div>
              <p className="m-0 mt-3 text-sm leading-5 text-[#eef3f7]">{shortText(operatorText(plan.summary), 220)}</p>
              <div className="mt-3">
                <div className="mb-1 flex items-center justify-between text-xs text-[#abb3bf]">
                  <span>Confidence</span>
                  <span>{Math.round(plan.confidence * 100)}%</span>
                </div>
                <ProgressBar intent={Intent.SUCCESS} value={plan.confidence} />
              </div>
            </div>
          ) : null}
        </section>

        <section className="fireguard-command-section fireguard-command-step">
          <div className="fireguard-command-step-head">
            <div>
              <span>04</span>
              <H5 className="m-0">Approval</H5>
            </div>
            {assessment ? <Tag intent={intentForStatus(assessment.approval.status)}>{assessment.approval.status}</Tag> : <Tag minimal>locked</Tag>}
          </div>
          <p className="fireguard-command-step-copy">
            Public-facing, road, shelter, and dispatch actions stay held until approval.
          </p>
          <div className="grid grid-cols-4 gap-2">
            <MiniMetric label="Drafted" value={actions.length} />
            <MiniMetric label="Public" value={publicActionCount} intent={Intent.WARNING} />
            <MiniMetric label="Done" value={executedCount} intent={Intent.SUCCESS} />
            <MiniMetric label="Blocked" value={blockers} intent={blockers ? Intent.WARNING : Intent.NONE} />
          </div>
          <div className="mt-3 grid gap-2">
            {!assessment ? (
              <div className="fireguard-locked-state">
                <Tag minimal>locked</Tag>
              </div>
            ) : (
              <>
                <Button icon="path-search" text="Tool trace" onClick={onOpenTrace} />
                {!approved ? <Button icon="confirm" text="Review & Approve" intent={Intent.PRIMARY} onClick={onOpenApproval} /> : null}
                <Button icon="play" text="Execute Approved Actions" intent={Intent.SUCCESS} disabled={!approved || busy !== null} loading={busy === "execute"} onClick={onExecute} />
              </>
            )}
          </div>
        </section>
      </div>
    </PaneBody>
  );
}

function WorkflowStatus({ steps }: { steps: Array<{ label: string; detail: string; intent: Intent }> }) {
  return (
    <section className="fireguard-workflow">
      {steps.map((step, index) => (
        <div key={step.label} className="fireguard-workflow-row">
          <span className={`fireguard-workflow-node ops-status-${step.intent}`} />
          {index < steps.length - 1 ? <span className="fireguard-workflow-line" /> : null}
          <div className="fireguard-workflow-copy">
            <span>{step.label}</span>
            <small>{step.detail}</small>
          </div>
        </div>
      ))}
    </section>
  );
}

function CenterOpsArea({ context, assessment, actions }: { context: IncidentContext | null; assessment: AssessmentResult | null; actions: ActionItem[] }) {
  return (
    <div className="ops-center-stack">
      <section className="ops-map-frame">
        <div className="ops-column-header">
          <div>
            <H5 className="m-0">BC Operations</H5>
          </div>
        </div>
        <div className="ops-map-body">
          <MapPanel context={context} assessment={assessment} />
        </div>
      </section>
      <section className="ops-analytics-frame">
        <div className="ops-column-header ops-column-header-compact">
          <div>
            <H5 className="m-0">Status</H5>
          </div>
          <Tag minimal>{actions.length} actions</Tag>
        </div>
        <AnalyticsPanel context={context} assessment={assessment} actions={actions} />
      </section>
    </div>
  );
}

function AnalyticsPanel({ context, assessment, actions }: { context: IncidentContext | null; assessment: AssessmentResult | null; actions: ActionItem[] }) {
  const risks = assessment?.plan.zone_risks || [];
  const routes = assessment?.plan.routes || [];

  return (
    <section className="ops-analytics">
      <RiskSummaryCard risks={risks} context={context} />
      <RouteSummaryCard routes={routes} />
      <ActionStateSummary actions={actions} />
    </section>
  );
}

function RiskSummaryCard({ risks, context }: { risks: ZoneRisk[]; context: IncidentContext | null }) {
  const ranked = [...risks].sort((a, b) => b.score - a.score).slice(0, 3);
  return (
    <div className="ops-summary-card">
      <SummaryCardHeader title="Zone risk" subtitle={ranked.length ? `${ranked.length} zones` : "pending"} />
      {ranked.length ? (
        <div className="ops-risk-list">
          {ranked.map((risk) => (
            <div key={risk.zone_id} className="ops-risk-row">
              <div className="ops-risk-copy">
                <span>{risk.zone_id}</span>
                <Tag minimal intent={intentForRisk(risk.risk_level)}>{risk.risk_level}</Tag>
              </div>
              <div className="ops-meter">
                <span className={`ops-meter-fill ops-meter-${risk.risk_level.toLowerCase()}`} style={{ width: `${Math.round(risk.score * 100)}%` }} />
              </div>
              <small>{Math.round(risk.score * 100)}%</small>
            </div>
          ))}
        </div>
      ) : (
        <div className="ops-summary-waiting">
          <MetricLine label="Fire records" value={String(context?.fires.length || 0)} />
          <MetricLine label="Road events" value={String(context?.road_events.length || 0)} />
          <MetricLine label="Zones loaded" value={String(context?.zones.length || 0)} />
        </div>
      )}
    </div>
  );
}

function RouteSummaryCard({ routes }: { routes: AssessmentResult["plan"]["routes"] }) {
  const safe = routes.filter((route) => route.safe);
  const blocked = routes.filter((route) => !route.safe);
  const fastest = safe.reduce<number | null>((best, route) => best === null ? route.duration_minutes : Math.min(best, route.duration_minutes), null);
  const total = Math.max(routes.length, 1);
  return (
    <div className="ops-summary-card">
      <SummaryCardHeader title="Route safety" subtitle={routes.length ? `${routes.length} routes` : "pending"} />
      <div className="ops-route-split" aria-hidden="true">
        <span className="ops-route-safe" style={{ width: `${(safe.length / total) * 100}%` }} />
        <span className="ops-route-blocked" style={{ width: `${(blocked.length / total) * 100}%` }} />
      </div>
      <div className="ops-summary-grid">
        <MetricLine label="Safe" value={String(safe.length)} tone="safe" />
        <MetricLine label="Blocked" value={String(blocked.length)} tone="blocked" />
        <MetricLine label="Fastest safe" value={fastest === null ? "none" : `${fastest}m`} />
      </div>
    </div>
  );
}

function ActionStateSummary({ actions }: { actions: ActionItem[] }) {
  const pending = actions.filter((action) => action.status === "pending").length;
  const approved = actions.filter((action) => action.status === "approved").length;
  const executed = actions.filter((action) => ["executed", "sent"].includes(action.status)).length;
  const failed = actions.filter((action) => action.status === "failed").length;
  const total = Math.max(actions.length, 1);
  return (
    <div className="ops-summary-card">
      <SummaryCardHeader title="Action state" subtitle={actions.length ? `${actions.length} actions` : "pending"} />
      <div className="ops-action-state-bar" aria-hidden="true">
        <span className="ops-action-state-pending" style={{ width: `${(pending / total) * 100}%` }} />
        <span className="ops-action-state-approved" style={{ width: `${(approved / total) * 100}%` }} />
        <span className="ops-action-state-executed" style={{ width: `${(executed / total) * 100}%` }} />
        <span className="ops-action-state-failed" style={{ width: `${(failed / total) * 100}%` }} />
      </div>
      <div className="ops-summary-grid">
        <MetricLine label="Queued" value={String(pending)} />
        <MetricLine label="Approved" value={String(approved)} tone="safe" />
        <MetricLine label="Executed" value={String(executed)} />
      </div>
    </div>
  );
}

function SummaryCardHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="ops-summary-header">
      <p>{title}</p>
      <span>{subtitle}</span>
    </div>
  );
}

function MetricLine({ label, value, tone }: { label: string; value: string; tone?: "safe" | "blocked" }) {
  return (
    <div className="ops-metric-line">
      <span>{label}</span>
      <strong className={tone ? `ops-metric-${tone}` : undefined}>{value}</strong>
    </div>
  );
}

function RightOpsPanel({
  status,
  evalResult,
  context,
  assessment,
  actions,
  stage,
}: {
  status: IntegrationStatus | null;
  evalResult: Record<string, unknown> | null;
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
  actions: ActionItem[];
  stage: DemoStage;
}) {
  return (
    <aside className="ops-right-stack">
      <div className="ops-column-header">
        <div>
          <H5 className="m-0">Operational State</H5>
        </div>
      </div>
      <div className="ops-pane-content">
        <MissionBriefPane status={status} evalResult={evalResult} context={context} assessment={assessment} actions={actions} stage={stage} />
      </div>
    </aside>
  );
}

function MissionBriefPane({
  status,
  evalResult,
  context,
  assessment,
  actions,
  stage,
}: {
  status: IntegrationStatus | null;
  evalResult: Record<string, unknown> | null;
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
  actions: ActionItem[];
  stage: DemoStage;
}) {
  const providerHealth = providerSummaries(status, evalResult).slice(0, 4);
  const plan = assessment?.plan;
  const pendingActions = actions.filter((action) => action.status === "pending").length;
  const stageCopy = STAGE_COPY[stage];
  const topRisks = [...(plan?.zone_risks || [])].sort((a, b) => b.score - a.score).slice(0, 2);
  const rejected = plan?.rejected_alternatives?.[0];

  return (
    <PaneBody>
      <section className="ops-panel">
        <div className="ops-panel-title">
          <H5 className="m-0">Providers</H5>
          <Tag minimal intent={stageCopy.intent}>{stageCopy.label}</Tag>
        </div>
        <div className="mission-provider-strip">
          {providerHealth.map((item) => (
            <div key={item.title} className="mission-provider-chip">
              <span className={`ops-status-dot ops-status-${item.intent}`} />
              <span>{item.title}</span>
              <Tag minimal intent={item.intent}>{item.value}</Tag>
            </div>
          ))}
        </div>
      </section>

      <section className="ops-panel">
        <div className="ops-panel-title">
          <H5 className="m-0">Snapshot</H5>
          <Tag minimal intent={assessment ? Intent.SUCCESS : Intent.NONE}>{assessment ? "ready" : "not run"}</Tag>
        </div>
        {plan ? (
          <div className="mission-snapshot">
            <TraceLine label="Strategy" value={plan.recommended_strategy.replaceAll("_", " ")} />
            <TraceLine label="Planning" value={planningModeText(assessment?.planning_mode)} />
            <TraceLine label="Validation" value={assessment?.plan_validation?.valid === true ? "passed" : "guarded"} />
            <TraceLine label="Approval" value={assessment?.approval.status || "locked"} />
          </div>
        ) : (
          <div className="mission-signal-grid">
            <MetricLine label="Decision" value={String(decisionRecordCount(context))} />
            <MetricLine label="Current" value={String(liveOverlayRecordCount(context))} />
            <MetricLine label="Orders" value={String(context?.public_evacuation_orders?.length || 0)} />
          </div>
        )}
      </section>

      {topRisks.length ? (
        <section className="ops-panel">
          <div className="ops-panel-title">
            <H5 className="m-0">Risk</H5>
          </div>
          <div className="grid gap-2">
            {topRisks.map((risk) => (
              <div key={risk.zone_id} className="mission-risk-row">
                <span>{risk.zone_id}</span>
                <div className="ops-meter">
                  <span className={`ops-meter-fill ops-meter-${risk.risk_level.toLowerCase()}`} style={{ width: `${Math.round(risk.score * 100)}%` }} />
                </div>
                <Tag minimal intent={intentForRisk(risk.risk_level)}>{risk.risk_level}</Tag>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {rejected ? (
        <section className="ops-panel mission-rejection">
          <div className="ops-panel-title">
            <H5 className="m-0">Rejected route</H5>
            <Tag intent={Intent.DANGER}>blocked</Tag>
          </div>
          <p>{shortText(String(rejected.reason), 210)}</p>
        </section>
      ) : null}

      <section className="ops-panel">
        <div className="ops-panel-title">
          <H5 className="m-0">Queue</H5>
          <Tag minimal intent={pendingActions ? Intent.WARNING : actions.length ? Intent.SUCCESS : Intent.NONE}>
            {actions.length ? `${pendingActions}/${actions.length} queued` : "locked"}
          </Tag>
        </div>
        <div className="ops-action-list">
          {actions.length ? actions.slice(0, 4).map((action) => (
            <ActionQueueRow key={action.action_id} action={action} />
          )) : (
            <div className="ops-empty-line">None</div>
          )}
        </div>
      </section>
    </PaneBody>
  );
}

function OverviewPane({
  status,
  evalResult,
  context,
  assessment,
  actions,
}: {
  status: IntegrationStatus | null;
  evalResult: Record<string, unknown> | null;
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
  actions: ActionItem[];
}) {
  const summaries = providerSummaries(status, evalResult).slice(0, 5);
  const evalChecks = evalResult?.checks as Record<string, boolean> | undefined;
  const evalPassed = evalChecks ? Object.values(evalChecks).filter(Boolean).length : 0;
  const evalTotal = evalChecks ? Object.keys(evalChecks).length : 0;
  const maxRisk = assessment?.plan.zone_risks.reduce((max, risk) => Math.max(max, risk.score), 0) || 0;
  const openShelters = context?.shelters.filter((shelter) => (shelter.official_facility_status || shelter.status) === "OPEN").length || 0;

  return (
    <PaneBody>
      <section className="ops-panel">
        <div className="ops-panel-title">
          <H5 className="m-0">Providers</H5>
        </div>
        <div className="ops-provider-grid">
          {summaries.map((item) => (
            <div key={item.title} className="ops-provider-row">
              <span className={`ops-status-dot ops-status-${item.intent}`} />
              <div className="ops-provider-copy">
                <span>{item.title}</span>
                <small>{item.detail}</small>
              </div>
              <Tag minimal intent={item.intent}>{item.value}</Tag>
            </div>
          ))}
        </div>
      </section>

      <section className="ops-panel">
        <div className="ops-panel-title">
          <H5 className="m-0">Assessment</H5>
        </div>
        <div className="ops-gauge-row">
          <DonutGauge label="Max risk" value={maxRisk} intent={maxRisk >= 0.6 ? Intent.WARNING : Intent.SUCCESS} />
          <DonutGauge label="Open ESS" value={context?.shelters.length ? openShelters / context.shelters.length : 0} intent={openShelters ? Intent.SUCCESS : Intent.WARNING} />
        </div>
        <div className="mt-3 grid gap-2">
          <TraceLine label="Eval checks" value={evalTotal ? `${evalPassed}/${evalTotal}` : "not run"} />
          <TraceLine label="Trace events" value={String(assessment?.trace.length || 0)} />
        </div>
      </section>

      <section className="ops-panel ops-action-table">
        <div className="ops-panel-title">
          <H5 className="m-0">Queue</H5>
        </div>
        <div className="ops-action-list">
          {actions.length ? actions.slice(0, 7).map((action) => (
            <ActionQueueRow key={action.action_id} action={action} />
          )) : (
            <div className="ops-empty-line">None</div>
          )}
        </div>
      </section>
    </PaneBody>
  );
}

function ActionQueueRow({ action }: { action: ActionItem }) {
  const statusIntent = intentForStatus(action.status);
  return (
    <div className="ops-action-row">
      <span className={`ops-action-rail ops-action-rail-${statusIntent}`} />
      <span aria-hidden className={`ops-action-glyph bp6-icon bp6-icon-${actionIcon(action.action_type)}`} />
      <div className="ops-action-copy">
        <div className="ops-action-title-row">
          <span>{action.action_type.replaceAll("_", " ")}</span>
          <Tag minimal intent={statusIntent}>{action.status}</Tag>
        </div>
        <div className="ops-action-meta-grid">
          <div>
            <small>Target</small>
            <span>{action.target}</span>
          </div>
          <div>
            <small>System</small>
            <span>{action.external_system}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function actionIcon(actionType: string) {
  if (actionType.includes("sms") || actionType.includes("resident")) return "send-message";
  if (actionType.includes("shelter")) return "home";
  if (actionType.includes("road")) return "git-branch";
  if (actionType.includes("dispatch")) return "truck";
  if (actionType.includes("timeline")) return "timeline-events";
  return "flows";
}

function DonutGauge({ label, value, intent }: { label: string; value: number; intent: Intent }) {
  const pct = Math.max(0, Math.min(1, value));
  const color = intent === Intent.WARNING ? "#f29d49" : intent === Intent.DANGER ? "#db3737" : "#2d72d2";
  return (
    <div className="ops-gauge">
      <div className="ops-donut" style={{ background: `conic-gradient(${color} ${Math.round(pct * 360)}deg, #1d2a35 0deg)` }}>
        <span>{Math.round(pct * 100)}</span>
      </div>
      <p>{label}</p>
    </div>
  );
}

function ApprovalDialog({
  isOpen,
  assessment,
  busy,
  onClose,
  onApprove,
}: {
  isOpen: boolean;
  assessment: AssessmentResult | null;
  busy: string | null;
  onClose: () => void;
  onApprove: () => void;
}) {
  return (
    <Dialog className="bp6-dark" icon="confirm" isOpen={isOpen} onClose={onClose} title="Approve Action Bundle">
      <div className={Classes.DIALOG_BODY}>
        {assessment ? (
          <div className="grid gap-3">
            <Callout intent={assessment.plan.requires_approval ? Intent.WARNING : Intent.PRIMARY} title={assessment.plan.recommended_strategy.replaceAll("_", " ")}>
              {operatorText(assessment.plan.summary)}
            </Callout>
            <div className="grid gap-2">
              {assessment.plan.steps.map((step) => (
                <div key={step.step_id} className="fireguard-muted-card p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{step.zone_id}</span>
                    <Tag minimal>{step.strategy}</Tag>
                  </div>
                  <p className="m-0 mt-2 text-sm text-[#d3d8de]">{step.message}</p>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <NonIdealState icon="info-sign" title="No bundle" description="Run assessment first." />
        )}
      </div>
      <div className={Classes.DIALOG_FOOTER}>
        <div className={Classes.DIALOG_FOOTER_ACTIONS}>
          <Button text="Cancel" onClick={onClose} />
          <Button intent={Intent.SUCCESS} icon="tick" text="Approve" disabled={!assessment || assessment.approval.status === "approved"} loading={busy === "approve"} onClick={onApprove} />
        </div>
      </div>
    </Dialog>
  );
}

function SituationAlertDialog({
  isOpen,
  context,
  assessment,
  rejectedRoute,
  busy,
  onClose,
  onRunAssessment,
}: {
  isOpen: boolean;
  context: IncidentContext | null;
  assessment: AssessmentResult | null;
  rejectedRoute?: Record<string, unknown>;
  busy: string | null;
  onClose: () => void;
  onRunAssessment: () => void;
}) {
  const liveRecords = liveOverlayRecordCount(context);
  const decisionRecords = decisionRecordCount(context);
  const conflictCount = (context?.road_events.length || 0) + (context?.fires.length || 0);
  const capacityAvailable = context?.shelters.reduce((total, shelter) => total + Number(shelter.capacity_available || 0), 0) || 0;

  return (
    <Dialog className="bp6-dark fireguard-alert-dialog" icon="warning-sign" isOpen={isOpen} onClose={onClose} title="Situation Alert">
      <div className={Classes.DIALOG_BODY}>
        <div className="fireguard-alert-hero">
          <div className="fireguard-alert-pulse" aria-hidden>
            <span />
            <span />
            <strong>FG</strong>
          </div>
          <div>
            <p className="ops-section-kicker">Wildfire evacuation alert</p>
            <H4 className="m-0">Route, fire, and shelter constraints require assessment</H4>
            <p className="m-0 mt-2 text-sm leading-5 text-[#cbd4dd]">
              {assessment
                ? shortText(operatorText(assessment.plan.summary), 260)
                : "Current evidence is loaded. Run Gemini to choose strategy, sequence zones, select destinations, and draft approval-gated actions."}
            </p>
          </div>
        </div>

        <div className="fireguard-alert-grid">
          <AlertSignal label="Decision records" value={decisionRecords} intent={Intent.PRIMARY} />
          <AlertSignal label="Live overlay" value={liveRecords} intent={liveRecords ? Intent.SUCCESS : Intent.WARNING} />
          <AlertSignal label="Fire/road signals" value={conflictCount} intent={Intent.WARNING} />
          <AlertSignal label="ESS capacity" value={capacityAvailable} intent={Intent.PRIMARY} />
        </div>

        {rejectedRoute ? (
          <Callout className="mt-4" intent={Intent.DANGER} icon="blocked-person" title="Unsafe route rejected">
            {shortText(String(rejectedRoute.reason), 240)}
          </Callout>
        ) : (
          <Callout className="mt-4" intent={Intent.WARNING} icon="info-sign" title="Command decision required">
            Public actions stay locked behind Gemini planning, backend validation, and commander approval.
          </Callout>
        )}
      </div>
      <div className={Classes.DIALOG_FOOTER}>
        <div className={Classes.DIALOG_FOOTER_ACTIONS}>
          <Button text="Close" onClick={onClose} />
          <Button
            icon="play"
            intent={Intent.DANGER}
            text={assessment ? "Run Reassessment" : "Run Gemini Agent"}
            loading={busy === "assessment"}
            disabled={busy !== null}
            onClick={onRunAssessment}
          />
        </div>
      </div>
    </Dialog>
  );
}

function AlertSignal({ label, value, intent }: { label: string; value: number; intent: Intent }) {
  return (
    <div className="fireguard-alert-signal">
      <span>{label}</span>
      <strong>{value}</strong>
      <i className={`ops-status-dot ops-status-${intent}`} />
    </div>
  );
}

function AgentTraceDialog({
  isOpen,
  assessment,
  traceEvents,
  evalResult,
  onClose,
}: {
  isOpen: boolean;
  assessment: AssessmentResult | null;
  traceEvents: Array<Record<string, unknown>>;
  evalResult: Record<string, unknown> | null;
  onClose: () => void;
}) {
  const toolCalls = assessment?.gemini_tool_calls || [];
  const validationPassed = assessment?.plan_validation?.valid === true;
  const rejectedAlternatives = assessment?.plan.rejected_alternatives || [];
  const evalChecks = evalResult?.checks as Record<string, boolean> | undefined;
  const visibleToolEvents: Array<Record<string, unknown>> = traceEvents.length
    ? traceEvents.slice(0, 8)
    : toolCalls.map((tool) => ({ tool, evidence_ids: [] as string[] }));

  return (
    <Dialog className="bp6-dark fireguard-trace-dialog" icon="path-search" isOpen={isOpen} onClose={onClose} title="Agent Decision Trace">
      <div className={Classes.DIALOG_BODY}>
        {assessment ? (
          <div className="fireguard-trace-layout">
            <section className="fireguard-trace-summary">
              <TraceLine label="Gemini status" value={assessment.gemini_status || "not run"} />
              <TraceLine label="Planning mode" value={planningModeText(assessment.planning_mode)} />
              <TraceLine label="Backend validation" value={validationPassed ? "passed" : "guarded"} />
              <TraceLine label="Phoenix spans" value={String(assessment.phoenix_trace_ids?.length || 0)} />
              <TraceLine label="Eval score" value={evalResult ? `${Math.round(Number(evalResult.score || 0) * 100)}%` : "not run"} />
            </section>

            <section className="fireguard-trace-section">
              <div className="ops-panel-title">
                <H5 className="m-0">Gemini Planning Output</H5>
                <Tag intent={intentForPlanningMode(assessment.planning_mode)}>{planningModeText(assessment.planning_mode)}</Tag>
              </div>
              <p className="m-0 mt-2 text-sm leading-5 text-[#cbd4dd]">{operatorText(assessment.plan.summary)}</p>
              <div className="mt-3 grid gap-2">
                {assessment.plan.steps.slice(0, 4).map((step) => (
                  <div key={step.step_id} className="fireguard-muted-card p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold">{step.zone_id}</span>
                      <Tag minimal>{step.strategy}</Tag>
                    </div>
                    <p className="m-0 mt-2 text-xs leading-5 text-[#abb3bf]">{shortText(step.message, 150)}</p>
                  </div>
                ))}
              </div>
            </section>

            <section className="fireguard-trace-section">
              <div className="ops-panel-title">
                <H5 className="m-0">Tool Calls</H5>
                <Tag minimal>{traceEvents.length || toolCalls.length}</Tag>
              </div>
              <div className="fireguard-tool-call-list">
                {visibleToolEvents.map((event, index) => {
                  const eventRecord = event as Record<string, unknown>;
                  const evidenceIds = eventRecord.evidence_ids;
                  return (
                  <div key={`${String(eventRecord.tool || eventRecord.step || index)}-${index}`} className="fireguard-tool-call">
                    <span aria-hidden className="bp6-icon bp6-icon-data-lineage" />
                    <div>
                      <strong>{String(eventRecord.tool || eventRecord.step || `tool ${index + 1}`)}</strong>
                      <small>{Array.isArray(evidenceIds) ? `Evidence ${evidenceIds.length}` : "Evidence tracked in audit"}</small>
                    </div>
                  </div>
                  );
                })}
              </div>
            </section>

            {rejectedAlternatives.length ? (
              <section className="fireguard-trace-section">
                <div className="ops-panel-title">
                  <H5 className="m-0">Rejected Alternatives</H5>
                  <Tag intent={Intent.DANGER}>{rejectedAlternatives.length}</Tag>
                </div>
                <div className="grid gap-2">
                  {rejectedAlternatives.slice(0, 3).map((item, index) => (
                    <div key={index} className="fireguard-muted-card p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold">{stringify(item.origin_id)}{" -> "}{stringify(item.destination_id, "none")}</span>
                        <Tag minimal intent={Intent.DANGER}>rejected</Tag>
                      </div>
                      <p className="m-0 mt-2 text-xs leading-5 text-[#abb3bf]">{shortText(String(item.reason), 180)}</p>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {evalChecks ? (
              <section className="fireguard-trace-section">
                <div className="ops-panel-title">
                  <H5 className="m-0">Eval Checks</H5>
                </div>
                <div className="fireguard-eval-chip-grid">
                  {Object.entries(evalChecks).map(([key, passed]) => (
                    <Tag key={key} intent={passed ? Intent.SUCCESS : Intent.DANGER}>{key.replaceAll("_", " ")}</Tag>
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        ) : (
          <NonIdealState icon="predictive-analysis" title="Agent has not run" description="Trigger the Gemini assessment to generate tool calls, validation, and trace exports." />
        )}
      </div>
      <div className={Classes.DIALOG_FOOTER}>
        <div className={Classes.DIALOG_FOOTER_ACTIONS}>
          <Button text="Close" onClick={onClose} />
        </div>
      </div>
    </Dialog>
  );
}

function ProviderDetails({ status, evalResult }: { status: IntegrationStatus | null; evalResult: Record<string, unknown> | null }) {
  const summaries = providerSummaries(status, evalResult);
  return (
    <PaneBody>
      <div className="grid gap-3">
        {summaries.map((item) => (
          <div key={item.title} className="fireguard-muted-card p-3">
            <div className="flex items-center justify-between gap-2">
              <H5 className="m-0">{item.title}</H5>
              <Tag intent={item.intent}>{item.state}</Tag>
            </div>
            <p className="m-0 mt-2 text-sm font-semibold text-[#f5f8fa]">{item.value}</p>
            <p className="m-0 mt-1 text-sm text-[#abb3bf]">{item.detail}</p>
          </div>
        ))}
      </div>
    </PaneBody>
  );
}

function ContextDetails({
  context,
  assumptions,
  contactInputs,
  busy,
  onRefreshFeeds,
  onRefreshLiveOverlay,
  onRefreshShelters,
  onRefreshZones,
  onContactChange,
  onContactCheckIn,
  onCapacityConfirm,
}: {
  context: IncidentContext | null;
  assumptions: Record<string, unknown>[];
  contactInputs: Record<string, string>;
  busy: string | null;
  onRefreshFeeds: () => void;
  onRefreshLiveOverlay: () => void;
  onRefreshShelters: () => void;
  onRefreshZones: () => void;
  onContactChange: (zoneId: string, phone: string) => void;
  onContactCheckIn: (zoneId: string) => void;
  onCapacityConfirm: (shelter: Shelter) => void;
}) {
  if (!context) return <PaneBody><NonIdealState icon="database" title="Context loading" /></PaneBody>;
  return (
    <PaneBody>
      <div className="grid gap-4">
        <section>
          <H5>Refresh Data</H5>
          <div className="grid gap-2">
            <Button icon="satellite" text="Refresh Fivetran live overlay" loading={busy === "live-overlay"} disabled={busy !== null} onClick={onRefreshLiveOverlay} />
            <Button icon="database" text="Sync Fivetran decision feeds" loading={busy === "fivetran"} disabled={busy !== null} onClick={onRefreshFeeds} />
            <Button icon="manual" text="Refresh shelter capacity" loading={busy === "shelter-sheet"} disabled={busy !== null} onClick={onRefreshShelters} />
            <Button icon="map" text="Refresh zone and road context" loading={busy === "source-zone-context"} disabled={busy !== null} onClick={onRefreshZones} />
          </div>
        </section>

        <section>
          <H5>Decision Records</H5>
          <div className="grid grid-cols-2 gap-2">
            <Metric label="Fires" value={context.fires.length} />
            <Metric label="Perimeters" value={context.perimeters.length} />
            <Metric label="Roads" value={context.road_events.length} />
            <Metric label="ESS sites" value={context.public_ess_facilities?.length || 0} />
          </div>
          <p className="m-0 mt-2 text-xs leading-5 text-[#8f99a8]">
            {String(context.decision_context?.decision_rule || "Decision evidence is kept separate from live overlay records.")}
          </p>
        </section>

        <section>
          <H5>Live Overlay</H5>
          <div className="grid grid-cols-2 gap-2">
            <Metric label="Live fires" value={context.live_context?.fires.length ?? 0} />
            <Metric label="Live perimeters" value={context.live_context?.perimeters.length ?? 0} />
            <Metric label="Live roads" value={context.live_context?.road_events.length ?? 0} />
            <Metric label="Live weather" value={context.live_context?.weather && Object.keys(context.live_context.weather).length ? 1 : 0} />
          </div>
          <p className="m-0 mt-2 text-xs leading-5 text-[#8f99a8]">
            {context.live_context?.decision_rule || "Current live records are display-only until explicitly promoted into a matching decision context."}
          </p>
          {context.live_context?.warnings?.length ? (
            <Callout className="mt-3" compact intent={Intent.WARNING} icon="info-sign">
              {context.live_context.warnings.length} live overlay source warning{context.live_context.warnings.length === 1 ? "" : "s"}.
            </Callout>
          ) : null}
        </section>

        <section>
          <H5>Shelter Capacity</H5>
          <div className="grid gap-2">
            {context.shelters.map((shelter) => (
              <div key={shelter.shelter_id} className="fireguard-muted-card p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="m-0 font-semibold">{shelter.name}</p>
                    <p className="m-0 mt-1 text-xs text-[#8f99a8]">{shortText(shelter.capacity_source_label || shelter.source_label || "capacity source not reported", 110)}</p>
                  </div>
                  <Tag intent={shelter.capacity_operator_confirmed ? Intent.SUCCESS : Intent.WARNING}>
                    {shelter.capacity_available}/{shelter.capacity_total}
                  </Tag>
                </div>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <Tag minimal intent={(shelter.official_facility_status || shelter.status) === "OPEN" ? Intent.SUCCESS : Intent.DANGER}>
                    ESS {shelter.official_facility_status || shelter.status}
                  </Tag>
                  <Button small icon="tick" text="Confirm Capacity" loading={busy === `capacity-${shelter.shelter_id}`} disabled={busy !== null} onClick={() => onCapacityConfirm(shelter)} />
                </div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <H5>Open Inputs</H5>
          <div className="grid gap-2">
            {assumptions.length ? assumptions.map((item) => (
              <div key={String(item.assumption_id)} className="fireguard-muted-card p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="m-0 font-semibold">{String(item.label)}</p>
                    <p className="m-0 mt-1 text-xs text-[#8f99a8]">{shortText(String(item.detail || item.fix_path || "Review before public execution."), 140)}</p>
                  </div>
                  <Tag intent={item.blocks_execution ? Intent.DANGER : Intent.WARNING}>{String(item.status || "open")}</Tag>
                </div>
                {item.component === "resident_contact" && item.blocks_execution ? (
                  <div className="mt-3 flex gap-2">
                    <InputGroup
                      fill
                      small
                      leftIcon="phone"
                      value={contactInputs[String(item.target)] || ""}
                      placeholder="+15065550123"
                      disabled={busy !== null}
                      onChange={(event) => onContactChange(String(item.target), event.target.value)}
                    />
                    <Button
                      small
                      icon="add"
                      text="Add"
                      loading={busy === `contact-${String(item.target)}`}
                      disabled={busy !== null || !contactInputs[String(item.target)]?.trim()}
                      onClick={() => onContactCheckIn(String(item.target))}
                    />
                  </div>
                ) : null}
              </div>
            )) : <NonIdealState icon="tick-circle" title="No open inputs" />}
          </div>
        </section>

        <section>
          <H5>Freshness</H5>
          <div className="grid gap-2">
            {context.data_freshness.map((item) => (
              <div key={String(item.source)} className="fireguard-muted-card flex items-center justify-between gap-3 p-3">
                <span>{String(item.source)}</span>
                <Tag intent={item.stale ? Intent.DANGER : Intent.SUCCESS}>{String(item.status)} {String(item.freshness_minutes)}m</Tag>
              </div>
            ))}
          </div>
        </section>
      </div>
    </PaneBody>
  );
}

function PlanDetails({ assessment }: { assessment: AssessmentResult | null }) {
  if (!assessment) return <PaneBody><NonIdealState icon="timeline-events" title="No plan yet" /></PaneBody>;
  const validationValid = assessment.plan_validation?.valid === true;
  const geminiSelected = assessment.planning_mode === "gemini_selected" || assessment.planning_mode === "gemini_repaired";
  const requestedActions = Array.isArray(assessment.plan.requested_actions) ? assessment.plan.requested_actions.length : 0;
  return (
    <PaneBody>
      <div className="grid gap-4">
        <Callout title={assessment.plan.recommended_strategy.replaceAll("_", " ")} intent={assessment.plan.requires_approval ? Intent.WARNING : Intent.PRIMARY}>
          {operatorText(assessment.plan.summary)}
        </Callout>
        <section>
          <H5>Planning Authority</H5>
          <div className="fireguard-muted-card p-3">
            <div className="flex flex-wrap gap-2">
              <Tag intent={intentForPlanningMode(assessment.planning_mode)}>{planningModeText(assessment.planning_mode)}</Tag>
              <Tag intent={validationValid ? Intent.SUCCESS : Intent.WARNING}>{validationValid ? "backend validation passed" : "backend fallback active"}</Tag>
              <Tag minimal intent={Intent.PRIMARY}>{requestedActions} Gemini action request{requestedActions === 1 ? "" : "s"}</Tag>
            </div>
            <p className="m-0 mt-2 text-sm text-[#d3d8de]">
              {geminiSelected
                ? "Gemini selected the operational strategy from route, risk, shelter, freshness, and evidence facts; backend validation controls execution."
                : "The final plan is not being claimed as Gemini-selected. Backend fallback is active because Gemini was unavailable or failed validation."}
            </p>
            {assessment.validation_errors?.length ? (
              <div className="mt-2 grid gap-1">
                {assessment.validation_errors.slice(0, 3).map((error) => (
                  <p key={error} className="m-0 text-xs text-[#f6b26b]">{publicValidationErrorText(error)}</p>
                ))}
              </div>
            ) : null}
          </div>
        </section>
        <section>
          <H5>Zone Risk</H5>
          <div className="grid gap-2">
            {assessment.plan.zone_risks.map((risk) => <RiskRow key={risk.zone_id} risk={risk} />)}
          </div>
        </section>
        <section>
          <H5>Plan Steps</H5>
          <div className="grid gap-2">
            {assessment.plan.steps.map((step) => (
              <div key={step.step_id} className="fireguard-muted-card p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{step.zone_id}</span>
                  <Tag>{step.strategy}</Tag>
                </div>
                <p className="m-0 mt-2 text-sm text-[#d3d8de]">{operatorText(step.message)}</p>
                <p className="m-0 mt-2 text-xs text-[#8f99a8]">Evidence: {step.evidence_ids.join(", ") || "none"}</p>
              </div>
            ))}
          </div>
        </section>
        <section>
          <H5>Rejected Alternatives</H5>
          <div className="grid gap-2">
            {assessment.plan.rejected_alternatives.map((item, index) => (
              <div key={`${String(item.origin_id)}-${String(item.destination_id)}-${index}`} className="fireguard-muted-card p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{stringify(item.origin_id)}{" -> "}{stringify(item.destination_id, "none")}</span>
                  <Tag intent={Intent.DANGER}>rejected</Tag>
                </div>
                <p className="m-0 mt-2 text-sm text-[#d3d8de]">{String(item.reason)}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </PaneBody>
  );
}

function ActionDetails({ actions, assessment, busy, onExecute }: { actions: ActionItem[]; assessment: AssessmentResult | null; busy: string | null; onExecute: () => void }) {
  return (
    <PaneBody>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <H5 className="m-0">Bundle {assessment?.bundle_id || "not created"}</H5>
          <p className="m-0 mt-1 text-sm text-[#8f99a8]">Execution requires an approved bundle.</p>
        </div>
        <Button icon="play" intent={Intent.SUCCESS} text="Execute" loading={busy === "execute"} disabled={!assessment || assessment.approval.status !== "approved" || busy !== null} onClick={onExecute} />
      </div>
      <div className="grid gap-2">
        {actions.length ? actions.map((action) => (
          <div key={action.action_id} className="fireguard-muted-card p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold">{action.action_type}</span>
              <Tag intent={intentForStatus(action.status)}>{action.status}</Tag>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <Tag minimal intent={action.is_simulated_endpoint ? Intent.WARNING : Intent.SUCCESS}>{action.is_simulated_endpoint ? "simulated endpoint" : "real/test channel"}</Tag>
              <Tag minimal intent={Intent.PRIMARY}>{action.external_system}</Tag>
              {action.requires_human_approval ? <Tag minimal intent={Intent.WARNING}>approval gated</Tag> : null}
            </div>
            <p className="m-0 mt-2 text-sm text-[#d3d8de]">{action.message}</p>
            <p className="m-0 mt-2 text-xs text-[#8f99a8]">{action.reason}</p>
            {typeof action.payload.github_issue_url === "string" ? (
              <a className="mt-2 block text-sm text-[#8abbff] underline underline-offset-4" href={action.payload.github_issue_url} target="_blank" rel="noreferrer">
                GitHub task #{String(action.payload.github_issue_number || "")}
              </a>
            ) : null}
          </div>
        )) : <NonIdealState icon="send-message" title="No actions generated" />}
      </div>
    </PaneBody>
  );
}

function AuditDetails({ traceEvents, evalResult, assessment }: { traceEvents: Array<Record<string, unknown>>; evalResult: Record<string, unknown> | null; assessment: AssessmentResult | null }) {
  const evalChecks = evalResult?.checks as Record<string, boolean> | undefined;
  const decisionCounts = assessment?.context.decision_context?.record_counts as Record<string, number> | undefined;
  const liveCounts = assessment?.context.live_context?.record_counts;
  return (
    <PaneBody>
      <div className="grid gap-4">
        <section>
          <H5>Trace Exports</H5>
          <div className="grid gap-2">
            <TraceLine label="Gemini status" value={assessment?.gemini_status || "not run"} />
            <TraceLine label="Planning mode" value={planningModeText(assessment?.planning_mode)} />
            <TraceLine label="Plan validation" value={assessment?.plan_validation?.valid === true ? "passed" : assessment ? "fallback or failed" : "not run"} />
            <TraceLine label="Phoenix spans" value={String(assessment?.phoenix_trace_ids?.length || 0)} />
            <TraceLine label="Arize AX spans" value={String(assessment?.arize_ax_trace_ids?.length || 0)} />
            <TraceLine label="Eval score" value={evalResult ? `${Math.round(Number(evalResult.score || 0) * 100)}%` : "not run"} />
          </div>
        </section>
        {assessment?.context.source_lineage ? (
          <section>
            <H5>Source Separation</H5>
            <div className="grid gap-2">
              <TraceLine label="Decision context" value={assessment.context.decision_context_mode || "unknown"} />
              <TraceLine label="Decision" value={String(Object.values(decisionCounts || {}).reduce((total, value) => total + Number(value || 0), 0))} />
              <TraceLine label="Current" value={String(Object.values(liveCounts || {}).reduce((total, value) => total + Number(value || 0), 0))} />
            </div>
            <p className="m-0 mt-2 text-xs leading-5 text-[#8f99a8]">{String(assessment.context.source_lineage.rule || "")}</p>
          </section>
        ) : null}
        {assessment?.candidate_facts_summary ? (
          <section>
            <H5>Candidate Facts</H5>
            <div className="grid grid-cols-2 gap-2">
              <TraceLine label="Safe routes" value={String(assessment.candidate_facts_summary.safe_route_count ?? 0)} />
              <TraceLine label="Rejected routes" value={String(assessment.candidate_facts_summary.unsafe_route_count ?? 0)} />
              <TraceLine label="Evidence records" value={String(assessment.candidate_facts_summary.evidence_count ?? 0)} />
              <TraceLine label="Fire trigger" value={assessment.candidate_facts_summary.wildfire_evacuation_trigger ? "true" : "false"} />
            </div>
          </section>
        ) : null}
        {evalChecks ? (
          <section>
            <H5>Eval Checks</H5>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(evalChecks).map(([key, passed]) => (
                <div key={key} className="fireguard-muted-card flex items-center justify-between gap-2 p-3">
                  <span>{key.replaceAll("_", " ")}</span>
                  <Tag intent={passed ? Intent.SUCCESS : Intent.DANGER}>{passed ? "pass" : "fail"}</Tag>
                </div>
              ))}
            </div>
          </section>
        ) : null}
        <section>
          <H5>Tool Events</H5>
          <div className="grid gap-2">
            {traceEvents.length ? traceEvents.map((event, index) => (
              <div key={String(event.event_id || index)} className="fireguard-muted-card p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{String(event.step || `event ${index + 1}`)}</span>
                  <Tag minimal intent={Intent.PRIMARY}>{String(event.tool || "tool")}</Tag>
                </div>
                <p className="m-0 mt-2 text-xs text-[#8f99a8]">Evidence: {Array.isArray(event.evidence_ids) ? event.evidence_ids.join(", ") || "none" : "none"}</p>
                <p className="m-0 mt-1 text-xs text-[#8f99a8]">Phoenix: {String(event.phoenix_trace_id || "not exported")}</p>
                <p className="m-0 mt-1 text-xs text-[#8f99a8]">Arize AX: {String(event.arize_ax_trace_id || "not exported")}</p>
              </div>
            )) : <NonIdealState icon="path-search" title="No trace events yet" />}
          </div>
        </section>
      </div>
    </PaneBody>
  );
}

function RiskRow({ risk }: { risk: ZoneRisk }) {
  return (
    <div className="fireguard-muted-card p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold">{risk.zone_id}</span>
        <Tag intent={intentForRisk(risk.risk_level)}>{risk.risk_level} {Math.round(risk.score * 100)}</Tag>
      </div>
      <p className="m-0 mt-2 text-sm text-[#d3d8de]">{risk.reasoning_factors[0]}</p>
      <p className="m-0 mt-2 text-xs text-[#8f99a8]">Confidence {Math.round(risk.confidence * 100)}%; urgency {risk.urgency_minutes}m</p>
    </div>
  );
}

function PaneBody({ children }: { children: ReactNode }) {
  return <div className="fireguard-scroll ops-pane-body">{children}</div>;
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="fireguard-muted-card p-3">
      <p className="m-0 text-xs uppercase tracking-wide text-[#8f99a8]">{label}</p>
      <p className="m-0 mt-1 text-2xl font-semibold text-[#f5f8fa]">{value}</p>
    </div>
  );
}

function MiniMetric({ label, value, intent = Intent.NONE }: { label: string; value: number; intent?: Intent }) {
  const dotClass = intent === Intent.DANGER ? "bg-[#db3737]" : intent === Intent.WARNING ? "bg-[#f2b824]" : intent === Intent.PRIMARY ? "bg-[#2d72d2]" : "bg-[#5f6b7c]";
  return (
    <div className="fireguard-mini-metric">
      <p className="m-0 text-[10px] font-semibold uppercase tracking-wide text-[#8f99a8]">{label}</p>
      <div className="mt-1 flex items-end justify-between gap-1">
        <span className="text-xl font-semibold leading-none text-[#f5f8fa]">{value}</span>
        <span className={`mb-1 h-2 w-2 ${dotClass}`} />
      </div>
    </div>
  );
}

function TraceLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="fireguard-muted-card flex items-center justify-between gap-3 p-3">
      <span>{label}</span>
      <Tag>{value}</Tag>
    </div>
  );
}

function providerSummaries(status: IntegrationStatus | null, evalResult: Record<string, unknown> | null) {
  const fivetranRun = status?.fivetran?.latest_run as Record<string, unknown> | null | undefined;
  const fivetranManaged = status?.fivetran?.managed_api as Record<string, unknown> | null | undefined;
  const fivetranConnection = fivetranManaged?.connection as Record<string, unknown> | null | undefined;
  const fivetranDestination = fivetranManaged?.destination as Record<string, unknown> | null | undefined;
  const fivetranWarnings = asRecordArray(fivetranRun?.warnings ?? status?.fivetran?.warnings);
  const fivetranQualityWarnings = asRecordArray(fivetranRun?.data_quality_warnings);
  const fivetranFallbackActive = status?.fivetran?.fallback_active === true || fivetranRun?.fallback_active === true || fivetranWarnings.length > 0;
  const firstQualityWarning = fivetranQualityWarnings[0];
  const fivetranStreams = fivetranRun?.streams as Record<string, unknown> | undefined;
  const fivetranRowCount = Object.values(fivetranStreams || {}).reduce<number>((total, value) => total + (typeof value === "number" ? value : 0), 0);
  const fivetranManagedOk = fivetranManaged?.status === "ok";
  const fivetranDetail = fivetranFallbackActive
    ? "Fallback records are flagged. Open diagnostics before execution."
    : fivetranQualityWarnings.length
      ? `${fivetranRowCount || "Loaded"} records synced; ${String(firstQualityWarning?.count_removed || 0)} out-of-region fire records filtered.`
      : fivetranManagedOk
        ? `${fivetranRowCount || "Loaded"} records synced through the warehouse.`
        : "Source feed sync is queued.";
  const liveOverlay = status?.live_overlay as Record<string, unknown> | undefined;
  const liveOverlayRun = liveOverlay?.latest_run as Record<string, unknown> | null | undefined;
  const liveOverlayCounts = liveOverlay?.record_counts as Record<string, unknown> | undefined;
  const liveOverlayWarnings = asRecordArray(liveOverlay?.warnings);
  const liveOverlayQualityWarnings = asRecordArray(liveOverlay?.data_quality_warnings ?? liveOverlayRun?.data_quality_warnings);
  const liveOverlayFallbackActive = liveOverlay?.fallback_active === true || liveOverlayRun?.fallback_active === true;
  const liveOverlayProvider = String(liveOverlayRun?.provider_path || liveOverlay?.provider || "fivetran_bigquery");
  const liveOverlayCount = Object.values(liveOverlayCounts || {}).reduce<number>((total, value) => total + (typeof value === "number" ? value : 0), 0);
  const liveOverlaySynced = Boolean(liveOverlayRun);
  const liveOverlayDetail = liveOverlaySynced
    ? liveOverlayFallbackActive
      ? "Fivetran warehouse overlay failed; direct source adapters are flagged as fallback."
      : `${liveOverlayCount || "Current"} records loaded through ${liveOverlayProvider}. ${String(liveOverlay?.decision_rule || "Display-only and separate from replay decision evidence.")}`
    : "Run live overlay sync to load current warehouse records beside the replay plan.";
  const evalChecks = evalResult?.checks as Record<string, boolean> | undefined;
  const passed = evalChecks ? Object.values(evalChecks).filter(Boolean).length : 0;
  const arizeCheck = status?.arize?.connection_check as Record<string, unknown> | undefined;
  const arizeAx = status?.arize?.arize_ax as Record<string, unknown> | undefined;
  const arizeAxCheck = arizeAx?.connection_check as Record<string, unknown> | undefined;
  const arizeOk = (status?.arize?.enabled === true && arizeCheck?.status === "ok") || arizeAxCheck?.status === "ok";
  const arizeDeployment = String(status?.arize?.deployment || "local");
  const arizeDetail = evalChecks
    ? `${passed}/${Object.keys(evalChecks).length} safety and grounding checks passed.`
    : arizeOk ? "Trace export is connected." : `${arizeDeployment} trace export is disconnected.`;
  const taskBackend = String(status?.action_tasks?.backend || "offline");
  const taskRepo = String(status?.action_tasks?.github_repo || "no repo configured");
  const shelterCapacity = status?.shelter_capacity as Record<string, unknown> | undefined;
  const shelterCapacityConfigured = shelterCapacity?.configured === true;
  const shelterCapacityUpdates = Number(shelterCapacity?.latest_update_count || 0);
  const shelterCapacityValue = shelterCapacityConfigured ? `${shelterCapacityUpdates} sheet updates` : "sheet offline";
  const shelterCapacityDetail = shelterCapacityConfigured
    ? `Latest capacity update: ${String(shelterCapacity?.latest_update_at || "no sync record")}`
    : "Capacity feed is disconnected.";
  const sourceZoneContext = status?.source_backed_zone_context as Record<string, unknown> | undefined;
  const sourceZoneUpdateCount = Number(sourceZoneContext?.latest_update_count || 0);

  return [
    {
      title: "Fivetran",
      state: fivetranFallbackActive ? "attention" : "active",
      value: fivetranFallbackActive ? "fallback flagged" : fivetranQualityWarnings.length ? "BC filtered" : fivetranManagedOk ? "connected" : fivetranRun ? String(fivetranRun.status) : "sync queued",
      detail: fivetranDetail,
      intent: status?.fivetran?.configured && fivetranManagedOk && !fivetranFallbackActive ? Intent.SUCCESS : Intent.WARNING,
    },
    {
      title: "Fivetran Live Overlay",
      state: liveOverlayFallbackActive || liveOverlayWarnings.length ? "attention" : liveOverlaySynced ? "active" : "sync required",
      value: liveOverlaySynced ? `${liveOverlayCount} current records` : "sync required",
      detail: liveOverlayQualityWarnings.length ? `${liveOverlayDetail} ${String(liveOverlayQualityWarnings[0]?.count_removed || 0)} out-of-region fire records filtered.` : liveOverlayDetail,
      intent: liveOverlaySynced && !liveOverlayFallbackActive && !liveOverlayWarnings.length ? Intent.SUCCESS : Intent.WARNING,
    },
    {
      title: "Elastic",
      state: status?.elastic?.configured ? "active" : "attention",
      value: status?.elastic?.configured ? "connected" : "not connected",
      detail: status?.elastic?.configured ? "Operational search is available." : "Operational search is not connected.",
      intent: status?.elastic?.configured ? Intent.SUCCESS : Intent.WARNING,
    },
    {
      title: "Gemini",
      state: status?.gemini?.configured ? "active" : "attention",
      value: status?.gemini?.configured ? "connected" : "not connected",
      detail: status?.gemini?.configured ? "Agent reasoning is available." : "Agent reasoning is not connected.",
      intent: status?.gemini?.configured ? Intent.SUCCESS : Intent.WARNING,
    },
    {
      title: "Shelter Sheet",
      state: shelterCapacityConfigured ? "active" : "attention",
      value: shelterCapacityValue,
      detail: shelterCapacityDetail,
      intent: shelterCapacityConfigured ? Intent.SUCCESS : Intent.WARNING,
    },
    {
      title: "Census/Roads",
      state: sourceZoneUpdateCount ? "active" : "attention",
      value: sourceZoneUpdateCount ? `${sourceZoneUpdateCount} zone updates` : "sync required",
      detail: sourceZoneUpdateCount ? `Latest update: ${String(sourceZoneContext?.latest_update_at || "no sync record")}` : "Zone and road context requires sync.",
      intent: sourceZoneUpdateCount ? Intent.SUCCESS : Intent.WARNING,
    },
    {
      title: "Phoenix/Arize",
      state: arizeOk ? "active" : "attention",
      value: evalResult ? `eval ${Math.round(Number(evalResult.score || 0) * 100)}%` : "trace-ready",
      detail: arizeDetail,
      intent: arizeOk ? Intent.SUCCESS : Intent.WARNING,
    },
    {
      title: "Action Tasks",
      state: status?.action_tasks?.configured ? "active" : "attention",
      value: status?.action_tasks?.configured ? "connected" : taskBackend,
      detail: status?.action_tasks?.configured ? `Task creation is available for ${taskRepo}.` : "Task creation is not connected.",
      intent: status?.action_tasks?.configured ? Intent.SUCCESS : Intent.WARNING,
    },
  ];
}
