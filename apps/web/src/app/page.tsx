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
import { approveBundle, confirmShelterCapacity, executeBundle, getCurrentIncident, getIntegrationStatus, getTraces, registerResidentTestContact, resetDemo, runAssessment, runEval, syncFivetranToElastic, syncShelterCapacitySheet, syncSourceBackedZoneContext } from "@/lib/api";
import type { ActionItem, AssessmentResult, IncidentContext, IntegrationStatus, Shelter, ZoneRisk } from "@/lib/types";

type ActivePane = "overview" | "sources" | "evidence" | "actions" | "audit" | "diagnostics";

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
    .replaceAll("public evacuation instruction drafted", "public evacuation instruction recommended");
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
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const rejectedRoute = useMemo(() => {
    return assessment?.plan.rejected_alternatives.find((item) => String(item.reason || "").toLowerCase().includes("closure") || String(item.reason || "").toLowerCase().includes("risk"));
  }, [assessment]);

  const assumptionsToShow = useMemo(() => {
    return [...(context?.operational_assumptions || [])].sort((a, b) => Number(Boolean(b.blocks_execution)) - Number(Boolean(a.blocks_execution)));
  }, [context]);

  const publicActionCount = useMemo(() => actions.filter((action) => action.requires_human_approval).length, [actions]);
  const executedCount = useMemo(() => actions.filter((action) => ["executed", "sent"].includes(action.status)).length, [actions]);
  const traceSource = traceEvents.length ? traceEvents : assessment?.trace || [];

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
    });
  }

  async function handleFivetranSync() {
    await runWithBusy("fivetran", async () => {
      await syncFivetranToElastic();
      await load();
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
        mode={context?.mode}
        hasAssessment={Boolean(assessment)}
        hasActions={Boolean(actions.length)}
        busy={busy}
        onReset={handleReset}
        onRunAssessment={handleAssessment}
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
              onOpenApproval={() => setApprovalOpen(true)}
              onRefreshFeeds={handleFivetranSync}
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
          />
        </div>
      </div>

      <ApprovalDialog
        isOpen={approvalOpen}
        assessment={assessment}
        busy={busy}
        onClose={() => setApprovalOpen(false)}
        onApprove={handleApprove}
      />
    </main>
  );
}

function OpsTopbar({
  mode,
  hasAssessment,
  hasActions,
  busy,
  onReset,
  onRunAssessment,
}: {
  mode?: string;
  hasAssessment: boolean;
  hasActions: boolean;
  busy: string | null;
  onReset: () => void;
  onRunAssessment: () => void;
}) {
  return (
    <header className="ops-topbar">
      <div className="ops-brand">
        <span className="ops-brand-mark">FG</span>
        <span className="font-semibold">FireGuard</span>
        <Tag minimal intent={Intent.PRIMARY}>Elastic</Tag>
      </div>
      <div className="ops-status-strip" aria-label="Incident status">
        <StatusPill label="Incident" value={mode === "replay" ? "Replay" : "Live"} intent={mode === "replay" ? Intent.WARNING : Intent.SUCCESS} />
        <StatusPill label="Assessment" value={hasAssessment ? "Ready" : "Pending"} intent={hasAssessment ? Intent.SUCCESS : Intent.NONE} />
        <StatusPill label="Action bundle" value={hasActions ? "Drafted" : "Empty"} intent={hasActions ? Intent.WARNING : Intent.NONE} />
      </div>
      <ButtonGroup minimal className="ops-toolbar-group">
        <Button icon="refresh" text="Reset" loading={busy === "reset"} disabled={busy !== null} onClick={onReset} />
        <Button icon="play" text={hasAssessment ? "Reassess" : "Run Assessment"} intent={Intent.DANGER} loading={busy === "assessment"} disabled={busy !== null} onClick={onRunAssessment} />
      </ButtonGroup>
    </header>
  );
}

function StatusPill({ label, value, intent }: { label: string; value: string; intent: Intent }) {
  return (
    <div className="ops-status-pill">
      <span>{label}</span>
      <Tag minimal intent={intent}>{value}</Tag>
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
      <div className="ops-rail-spacer" />
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
  onOpenApproval,
  onRefreshFeeds,
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
  onOpenApproval: () => void;
  onRefreshFeeds: () => void;
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
  const paneSubtitle = {
    overview: "Primary evacuation controls",
    sources: "Feeds, capacity, and open inputs",
    evidence: "Risk scores and rejected options",
    actions: "Approval-gated execution bundle",
    audit: "Tool calls, traces, and eval checks",
    diagnostics: "Provider and integration status",
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
        onOpenApproval={onOpenApproval}
        onExecute={onExecute}
      />
    );
  };

  return (
    <aside className="fireguard-command-panel">
      <div className="ops-pane-header">
        <div>
          <p className="ops-section-kicker">Command workspace</p>
          <H5 className="m-0">{paneTitle}</H5>
          <p className="ops-pane-subtitle">{paneSubtitle}</p>
        </div>
        <Tag minimal intent={assessment ? Intent.SUCCESS : Intent.NONE}>{assessment ? "assessed" : "standby"}</Tag>
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
  onOpenApproval,
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
  onOpenApproval: () => void;
  onExecute: () => void;
}) {
  const plan = assessment?.plan;
  const approved = assessment?.approval.status === "approved";
  const blockers = assumptions.filter((item) => item.blocks_execution).length;

  return (
    <PaneBody>
      <div className="fireguard-command-overview">
        <section className="fireguard-panel-head">
          <div>
            <p className="m-0 text-xs font-semibold uppercase tracking-[0.16em] text-[#8abbff]">Evacuation command</p>
            <H4 className="mb-0 mt-1">{plan ? "Recommendation Ready" : "Awaiting Assessment"}</H4>
          </div>
        </section>

        {plan ? (
          <section className="fireguard-decision-block">
            <div className="flex items-start justify-between gap-3">
              <div>
                <Tag intent={plan.recommended_strategy === "monitor" ? Intent.PRIMARY : Intent.WARNING}>
                  {plan.recommended_strategy.replaceAll("_", " ")}
                </Tag>
                <p className="m-0 mt-3 text-base leading-6 text-[#eef3f7]">{shortText(operatorText(plan.summary), 330)}</p>
              </div>
            </div>
            <div className="mt-4">
              <div className="mb-1 flex items-center justify-between text-xs text-[#abb3bf]">
                <span>Decision confidence</span>
                <span>{Math.round(plan.confidence * 100)}%</span>
              </div>
              <ProgressBar intent={Intent.SUCCESS} value={plan.confidence} />
            </div>
          </section>
        ) : (
          <section className="fireguard-empty-command">
            <div className="fireguard-pending-state">
              <Tag minimal intent={Intent.NONE}>no plan drafted</Tag>
              <H5 className="m-0 mt-3">Assessment Pending</H5>
              <p className="m-0 mt-2 text-sm leading-5 text-[#abb3bf]">Operational signals are loaded; public actions remain locked until an assessment and approval bundle exist.</p>
            </div>
          </section>
        )}

        <section className="fireguard-command-section">
          <div className="flex items-center justify-between gap-2">
            <H5 className="m-0">Operational Picture</H5>
            <Tag minimal>{context?.mode === "replay" ? "replay" : "live"}</Tag>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2">
            <MiniMetric label="Fires" value={context?.fires.length ?? 0} intent={Intent.DANGER} />
            <MiniMetric label="Roads" value={context?.road_events.length ?? 0} intent={Intent.WARNING} />
            <MiniMetric label="Zones" value={context?.zones.length ?? 0} intent={Intent.NONE} />
            <MiniMetric label="Shelters" value={context?.shelters.length ?? 0} intent={Intent.PRIMARY} />
          </div>
          {assumptions.length ? (
            <Callout className="mt-3" compact intent={blockers ? Intent.WARNING : Intent.PRIMARY} icon="info-sign">
              {assumptions.length} input{assumptions.length === 1 ? "" : "s"} need review; {blockers} block public execution.
            </Callout>
          ) : null}
        </section>

        {rejectedRoute ? (
          <section className="fireguard-command-section">
            <div className="flex items-center justify-between gap-2">
              <H5 className="m-0">Route Decision</H5>
              <Tag intent={Intent.DANGER}>blocked</Tag>
            </div>
            <p className="m-0 mt-2 text-sm leading-5 text-[#cbd4dd]">{shortText(String(rejectedRoute.reason), 190)}</p>
          </section>
        ) : null}

        <section className="fireguard-command-section">
          <div className="flex items-center justify-between gap-2">
            <H5 className="m-0">Action Control</H5>
            {assessment ? <Tag intent={intentForStatus(assessment.approval.status)}>{assessment.approval.status}</Tag> : <Tag minimal>locked</Tag>}
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <MiniMetric label="Drafted" value={actions.length} />
            <MiniMetric label="Public" value={publicActionCount} />
            <MiniMetric label="Done" value={executedCount} />
          </div>
          <div className="mt-3 grid gap-2">
            {!assessment ? (
              <div className="fireguard-locked-state">
                <Tag minimal>locked</Tag>
                <span>Approval bundle pending.</span>
              </div>
            ) : (
              <>
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

function CenterOpsArea({ context, assessment, actions }: { context: IncidentContext | null; assessment: AssessmentResult | null; actions: ActionItem[] }) {
  const incidentMode = context?.mode === "replay" ? "Replay window" : "Live window";
  const signalCount = (context?.fires.length || 0) + (context?.road_events.length || 0) + (context?.shelters.length || 0) + (context?.zones.length || 0);

  return (
    <div className="ops-center-stack">
      <section className="ops-map-frame">
        <div className="ops-column-header">
          <div>
            <p className="ops-section-kicker">Operational map</p>
            <H5 className="m-0">BC Fire, Roads, Shelters, Routes</H5>
          </div>
          <div className="ops-header-tags">
            <Tag minimal intent={context?.mode === "replay" ? Intent.WARNING : Intent.SUCCESS}>{incidentMode}</Tag>
            <Tag minimal>{signalCount} records</Tag>
          </div>
        </div>
        <div className="ops-map-body">
          <MapPanel context={context} assessment={assessment} />
        </div>
      </section>
      <section className="ops-analytics-frame">
        <div className="ops-column-header ops-column-header-compact">
          <div>
            <p className="ops-section-kicker">Signal trend</p>
            <H5 className="m-0">Risk, Routes, Actions</H5>
          </div>
          <Tag minimal>{actions.length} actions</Tag>
        </div>
        <AnalyticsPanel context={context} assessment={assessment} actions={actions} />
      </section>
    </div>
  );
}

function AnalyticsPanel({ context, assessment, actions }: { context: IncidentContext | null; assessment: AssessmentResult | null; actions: ActionItem[] }) {
  const riskValues = assessment?.plan.zone_risks.map((risk) => Math.round(risk.score * 100)) || [];
  const routeValues = assessment?.plan.routes.map((route) => route.duration_minutes).filter((value) => Number.isFinite(value)) || [];
  const actionValues = [
    actions.filter((action) => action.status === "pending").length,
    actions.filter((action) => action.status === "approved").length,
    actions.filter((action) => ["executed", "sent"].includes(action.status)).length,
  ];
  const signalValues = [context?.fires.length || 0, context?.road_events.length || 0, context?.zones.length || 0, context?.shelters.length || 0];

  return (
    <section className="ops-analytics">
      <MiniChart title="Risk by zone" subtitle={assessment ? `${riskValues.length} zones scored` : "waiting for assessment"} values={riskValues.length ? riskValues : signalValues} tone="#f29d49" />
      <MiniChart title="Route duration" subtitle={routeValues.length ? `${routeValues.length} options evaluated` : "no routes yet"} values={routeValues.length ? routeValues : signalValues} tone="#8abbff" />
      <MiniChart title="Action state" subtitle={`${actions.length} drafted actions`} values={actionValues} tone="#0f9960" />
    </section>
  );
}

function RightOpsPanel({
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
  return (
    <aside className="ops-right-stack">
      <div className="ops-column-header">
        <div>
          <p className="ops-section-kicker">Execution status</p>
          <H5 className="m-0">Systems & Queue</H5>
        </div>
        <Tag minimal intent={actions.length ? Intent.WARNING : Intent.NONE}>{actions.length ? `${actions.length} drafted` : "idle"}</Tag>
      </div>
      <div className="ops-pane-content">
        <OverviewPane status={status} evalResult={evalResult} context={context} assessment={assessment} actions={actions} />
      </div>
    </aside>
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
          <H5 className="m-0">Provider Status</H5>
        </div>
        <div className="ops-provider-grid">
          {summaries.map((item) => (
            <div key={item.title} className="ops-provider-row">
              <span>{item.title}</span>
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
          <TraceLine label="Eval checks" value={evalTotal ? `${evalPassed}/${evalTotal}` : "pending"} />
          <TraceLine label="Trace events" value={String(assessment?.trace.length || 0)} />
        </div>
      </section>

      <section className="ops-panel ops-action-table">
        <div className="ops-panel-title">
          <H5 className="m-0">Action Queue</H5>
        </div>
        <div className="ops-table">
          {actions.length ? actions.slice(0, 7).map((action) => (
            <div key={action.action_id} className="ops-table-row">
              <span>{action.action_type.replaceAll("_", " ")}</span>
              <span>{action.target}</span>
              <Tag minimal intent={intentForStatus(action.status)}>{action.status}</Tag>
            </div>
          )) : (
            <div className="ops-empty-line">No action bundle drafted.</div>
          )}
        </div>
      </section>
    </PaneBody>
  );
}

function MiniChart({ title, subtitle, values, tone }: { title: string; subtitle: string; values: number[]; tone: string }) {
  return (
    <div className="ops-chart-card">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="m-0 text-sm font-semibold text-[#f5f8fa]">{title}</p>
          <p className="m-0 mt-1 text-xs text-[#8f99a8]">{subtitle}</p>
        </div>
      </div>
      <Sparkline values={values} color={tone} />
    </div>
  );
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const safeValues = values.length >= 2 ? values : [0, values[0] || 0];
  const max = Math.max(...safeValues, 1);
  const min = Math.min(...safeValues, 0);
  const span = Math.max(max - min, 1);
  const points = safeValues
    .map((value, index) => {
      const x = safeValues.length === 1 ? 0 : (index / (safeValues.length - 1)) * 100;
      const y = 46 - ((value - min) / span) * 38;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <svg className="ops-sparkline" viewBox="0 0 100 52" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points} fill="none" stroke={color} strokeWidth="2.2" vectorEffect="non-scaling-stroke" />
      {safeValues.map((value, index) => {
        const x = safeValues.length === 1 ? 0 : (index / (safeValues.length - 1)) * 100;
        const y = 46 - ((value - min) / span) * 38;
        return <circle key={`${value}-${index}`} cx={x} cy={y} r="1.5" fill={color} />;
      })}
    </svg>
  );
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
            <Button icon="database" text="Refresh wildfire, road, and weather feeds" loading={busy === "fivetran"} disabled={busy !== null} onClick={onRefreshFeeds} />
            <Button icon="manual" text="Refresh shelter capacity" loading={busy === "shelter-sheet"} disabled={busy !== null} onClick={onRefreshShelters} />
            <Button icon="map" text="Refresh zone and road context" loading={busy === "source-zone-context"} disabled={busy !== null} onClick={onRefreshZones} />
          </div>
        </section>

        <section>
          <H5>Available Records</H5>
          <div className="grid grid-cols-2 gap-2">
            <Metric label="Fires" value={context.fires.length} />
            <Metric label="Perimeters" value={context.perimeters.length} />
            <Metric label="Roads" value={context.road_events.length} />
            <Metric label="ESS sites" value={context.public_ess_facilities?.length || 0} />
          </div>
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
  return (
    <PaneBody>
      <div className="grid gap-4">
        <Callout title={assessment.plan.recommended_strategy.replaceAll("_", " ")} intent={assessment.plan.requires_approval ? Intent.WARNING : Intent.PRIMARY}>
          {operatorText(assessment.plan.summary)}
        </Callout>
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
          <H5 className="m-0">Bundle {assessment?.bundle_id || "pending"}</H5>
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
  return (
    <PaneBody>
      <div className="grid gap-4">
        <section>
          <H5>Trace Exports</H5>
          <div className="grid gap-2">
            <TraceLine label="Gemini status" value={assessment?.gemini_status || "pending"} />
            <TraceLine label="Phoenix spans" value={String(assessment?.phoenix_trace_ids?.length || 0)} />
            <TraceLine label="Arize AX spans" value={String(assessment?.arize_ax_trace_ids?.length || 0)} />
            <TraceLine label="Eval score" value={evalResult ? `${Math.round(Number(evalResult.score || 0) * 100)}%` : "pending"} />
          </div>
        </section>
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
    ? "Some feed records are using a replay fallback. Review before demo execution."
    : fivetranQualityWarnings.length
      ? `${fivetranRowCount || "Loaded"} records synced; ${String(firstQualityWarning?.count_removed || 0)} out-of-region fire records filtered.`
      : fivetranManagedOk
        ? `${fivetranRowCount || "Loaded"} records synced through the warehouse.`
        : "Source feed sync is waiting for the next run.";
  const evalChecks = evalResult?.checks as Record<string, boolean> | undefined;
  const passed = evalChecks ? Object.values(evalChecks).filter(Boolean).length : 0;
  const arizeCheck = status?.arize?.connection_check as Record<string, unknown> | undefined;
  const arizeAx = status?.arize?.arize_ax as Record<string, unknown> | undefined;
  const arizeAxCheck = arizeAx?.connection_check as Record<string, unknown> | undefined;
  const arizeOk = (status?.arize?.enabled === true && arizeCheck?.status === "ok") || arizeAxCheck?.status === "ok";
  const arizeDeployment = String(status?.arize?.deployment || "local");
  const arizeDetail = evalChecks
    ? `${passed}/${Object.keys(evalChecks).length} safety and grounding checks passed.`
    : arizeOk ? "Trace export is connected." : `${arizeDeployment} trace export is not confirmed.`;
  const taskBackend = String(status?.action_tasks?.backend || "pending");
  const taskRepo = String(status?.action_tasks?.github_repo || "no repo configured");
  const shelterCapacity = status?.shelter_capacity as Record<string, unknown> | undefined;
  const shelterCapacityConfigured = shelterCapacity?.configured === true;
  const shelterCapacityUpdates = Number(shelterCapacity?.latest_update_count || 0);
  const shelterCapacityValue = shelterCapacityConfigured ? `${shelterCapacityUpdates} sheet updates` : "sheet needed";
  const shelterCapacityDetail = shelterCapacityConfigured
    ? `Latest capacity update: ${String(shelterCapacity?.latest_update_at || "not synced yet")}`
    : "Capacity feed is not connected yet.";
  const sourceZoneContext = status?.source_backed_zone_context as Record<string, unknown> | undefined;
  const sourceZoneUpdateCount = Number(sourceZoneContext?.latest_update_count || 0);

  return [
    {
      title: "Fivetran",
      state: fivetranFallbackActive ? "attention" : "active",
      value: fivetranFallbackActive ? "review needed" : fivetranQualityWarnings.length ? "BC filtered" : fivetranManagedOk ? "connected" : fivetranRun ? String(fivetranRun.status) : "waiting",
      detail: fivetranDetail,
      intent: status?.fivetran?.configured && fivetranManagedOk && !fivetranFallbackActive ? Intent.SUCCESS : Intent.WARNING,
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
      value: sourceZoneUpdateCount ? `${sourceZoneUpdateCount} zone updates` : "sync needed",
      detail: sourceZoneUpdateCount ? `Latest update: ${String(sourceZoneContext?.latest_update_at || "not synced yet")}` : "Zone and road context has not been refreshed.",
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
