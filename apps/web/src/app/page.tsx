"use client";

import { Activity, AlertTriangle, CheckCircle2, ClipboardCheck, Database, Play, RefreshCcw, Send, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import { MapPanel } from "@/components/MapPanel";
import { StatusBadge } from "@/components/StatusBadge";
import { approveBundle, executeBundle, getCurrentIncident, getIntegrationStatus, getTraces, resetDemo, runAssessment, runEval, syncFivetranToElastic } from "@/lib/api";
import type { ActionItem, AssessmentResult, IncidentContext, IntegrationStatus } from "@/lib/types";

function buttonClass(kind: "primary" | "secondary" | "danger" = "secondary") {
  const base = "inline-flex h-10 items-center justify-center gap-2 border px-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50";
  if (kind === "primary") return `${base} border-emerald-400/70 bg-emerald-500/20 text-emerald-50 hover:bg-emerald-500/30`;
  if (kind === "danger") return `${base} border-fire/70 bg-fire/20 text-orange-50 hover:bg-fire/30`;
  return `${base} border-line bg-panel text-slate-100 hover:bg-slate-800`;
}

function riskTone(level: string) {
  if (level === "CRITICAL") return "danger";
  if (level === "HIGH") return "warn";
  if (level === "MODERATE") return "info";
  return "ok";
}

function actionTone(status: string) {
  if (status === "executed" || status === "approved") return "ok";
  if (status === "failed" || status === "rejected") return "danger";
  return "warn";
}

export default function Home() {
  const [context, setContext] = useState<IncidentContext | null>(null);
  const [assessment, setAssessment] = useState<AssessmentResult | null>(null);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [traceEvents, setTraceEvents] = useState<Array<Record<string, unknown>>>([]);
  const [integrationStatus, setIntegrationStatus] = useState<IntegrationStatus | null>(null);
  const [evalResult, setEvalResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    const [nextContext, nextStatus] = await Promise.all([getCurrentIncident(), getIntegrationStatus()]);
    setContext(nextContext);
    setIntegrationStatus(nextStatus);
  };

  useEffect(() => {
    load().catch((err: Error) => setError(err.message));
  }, []);

  const rejectedRoute = useMemo(() => {
    return assessment?.plan.rejected_alternatives.find((item) => String(item.reason || "").toLowerCase().includes("closure"));
  }, [assessment]);

  async function handleReset() {
    setBusy("reset");
    setError(null);
    try {
      await resetDemo();
      setAssessment(null);
      setActions([]);
      setTraceEvents([]);
      setEvalResult(null);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleAssessment() {
    setBusy("assessment");
    setError(null);
    try {
      const result = await runAssessment();
      setAssessment(result);
      setContext(result.context);
      setActions(result.actions);
      setTraceEvents(result.trace);
      setEvalResult(await runEval(result.incident_id));
      setIntegrationStatus(await getIntegrationStatus());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleApprove() {
    if (!assessment) return;
    setBusy("approve");
    setError(null);
    try {
      const result = await approveBundle(assessment.approval.approval_id);
      setActions(result.actions);
      setAssessment({ ...assessment, approval: result.approval, actions: result.actions });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleExecute() {
    if (!assessment) return;
    setBusy("execute");
    setError(null);
    try {
      const result = await executeBundle(assessment.bundle_id);
      const nextActions = [...result.executed, ...result.failed];
      setActions(nextActions);
      setAssessment({ ...assessment, actions: nextActions });
      const traces = await getTraces(assessment.incident_id);
      setTraceEvents(traces.latest?.events || traceEvents);
      setEvalResult(await runEval(assessment.incident_id));
      setIntegrationStatus(await getIntegrationStatus());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleFivetranSync() {
    setBusy("fivetran");
    setError(null);
    try {
      await syncFivetranToElastic();
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="min-h-screen bg-command text-slate-100">
      <header className="border-b border-line bg-command/95 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-normal">FireGuard</h1>
              <StatusBadge label="Elastic track" tone="info" />
              <StatusBadge label="Fivetran ingestion" tone="ok" />
              <StatusBadge label="Arize Phoenix traces" tone="ok" />
              <StatusBadge label={context?.mode === "replay" ? "Replay-ready" : "Live mode"} tone={context?.mode === "replay" ? "warn" : "ok"} />
            </div>
            <p className="mt-1 max-w-3xl text-sm text-slate-400">
              AI evacuation coordinator for wildfire operations: real/open data, deterministic safety tools, human approval, and auditable action execution.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={buttonClass()} onClick={handleReset} disabled={busy !== null}>
              <RefreshCcw size={16} /> Reset Demo
            </button>
            <button className={buttonClass()} onClick={handleFivetranSync} disabled={busy !== null}>
              <Database size={16} /> Sync Fivetran To Elastic
            </button>
            <button className={buttonClass("danger")} onClick={handleAssessment} disabled={busy !== null}>
              <Play size={16} /> Run Agent Assessment
            </button>
          </div>
        </div>
        {error ? <div className="mt-3 border border-fire/60 bg-fire/15 px-3 py-2 text-sm text-orange-100">{error}</div> : null}
      </header>

      <ProviderStrip status={integrationStatus} evalResult={evalResult} />

      <div className="grid gap-4 p-4 xl:grid-cols-[minmax(680px,1.35fr)_minmax(420px,0.65fr)]">
        <MapPanel context={context} assessment={assessment} />

        <aside className="grid gap-4">
          <section className="border border-line bg-panel p-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-base font-semibold">Incident Context</h2>
              <StatusBadge label={context?.store_backend || "loading"} tone="neutral" />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <Metric label="Fire detections" value={context?.fires.length ?? 0} />
              <Metric label="Road events" value={context?.road_events.length ?? 0} />
              <Metric label="Zones" value={context?.zones.length ?? 0} />
              <Metric label="Shelters" value={context?.shelters.length ?? 0} />
            </div>
            <div className="mt-4 grid gap-2">
              {context?.data_freshness.map((item) => (
                <div key={String(item.source)} className="flex items-center justify-between border border-line bg-command/70 px-3 py-2 text-xs">
                  <span>{String(item.source)}</span>
                  <StatusBadge label={`${String(item.status)} ${String(item.freshness_minutes)}m`} tone={item.stale ? "danger" : "ok"} />
                </div>
              ))}
            </div>
          </section>

          <section className="border border-line bg-panel p-4">
            <div className="flex items-center gap-2">
              <AlertTriangle size={18} className="text-fire" />
              <h2 className="text-base font-semibold">Decision Moment</h2>
            </div>
            {rejectedRoute ? (
              <div className="mt-3 border border-fire/50 bg-fire/10 p-3 text-sm">
                <p className="font-semibold text-orange-100">Obvious route rejected</p>
                <p className="mt-1 text-slate-300">{String(rejectedRoute.reason)}</p>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-400">Run the assessment to produce the auditable route rejection.</p>
            )}
          </section>
        </aside>
      </div>

      <div className="grid gap-4 px-4 pb-4 xl:grid-cols-3">
        <section className="border border-line bg-panel p-4">
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-emerald-300" />
            <h2 className="text-base font-semibold">Agent Plan</h2>
          </div>
          {assessment ? (
            <div className="mt-3 grid gap-3">
              <p className="text-sm text-slate-300">{assessment.plan.summary}</p>
              <div className="flex flex-wrap gap-2">
                <StatusBadge label={`confidence ${Math.round(assessment.plan.confidence * 100)}%`} tone="ok" />
                <StatusBadge label={assessment.plan.recommended_strategy} tone="info" />
                <StatusBadge label="approval required" tone="warn" />
                {assessment.agent_review ? <StatusBadge label={`Gemini ${String(assessment.agent_review.status)}`} tone={assessment.agent_review.status === "completed" ? "ok" : "warn"} /> : null}
              </div>
              {assessment.agent_review?.incident_summary ? (
                <div className="border border-line bg-command/60 p-3 text-sm">
                  <p className="font-semibold text-slate-100">Gemini review</p>
                  <p className="mt-1 text-slate-300">{String(assessment.agent_review.incident_summary)}</p>
                  <p className="mt-2 text-xs text-slate-500">
                    Tools: {Array.isArray(assessment.agent_review.tool_calls) ? assessment.agent_review.tool_calls.join(", ") : "none"}
                  </p>
                </div>
              ) : null}
              {assessment.plan.zone_risks.map((risk) => (
                <div key={risk.zone_id} className="border border-line bg-command/60 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{risk.zone_id}</span>
                    <StatusBadge label={`${risk.risk_level} ${Math.round(risk.score * 100)}`} tone={riskTone(risk.risk_level)} />
                  </div>
                  <p className="mt-2 text-xs text-slate-400">{risk.reasoning_factors[0]}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-400">No plan yet.</p>
          )}
        </section>

        <section className="border border-line bg-panel p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <ClipboardCheck size={18} className="text-amber" />
              <h2 className="text-base font-semibold">Approval Queue</h2>
            </div>
            {assessment ? <StatusBadge label={assessment.approval.status} tone={assessment.approval.status === "approved" ? "ok" : "warn"} /> : null}
          </div>
          {assessment ? (
            <div className="mt-3 grid gap-3">
              {assessment.plan.steps.map((step) => (
                <div key={step.step_id} className="border border-line bg-command/60 p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{step.zone_id}</span>
                    <StatusBadge label={step.strategy} tone={step.strategy.includes("shelter") ? "warn" : "ok"} />
                  </div>
                  <p className="mt-2 text-slate-300">{step.message}</p>
                </div>
              ))}
              <button className={buttonClass("primary")} onClick={handleApprove} disabled={busy !== null || assessment.approval.status === "approved"}>
                <CheckCircle2 size={16} /> Approve Action Bundle
              </button>
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-400">The agent has not requested approval yet.</p>
          )}
        </section>

        <section className="border border-line bg-panel p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Send size={18} className="text-shelter" />
              <h2 className="text-base font-semibold">Action Execution</h2>
            </div>
            <button className={buttonClass()} onClick={handleExecute} disabled={!assessment || busy !== null || assessment.approval.status !== "approved"}>
              Execute
            </button>
          </div>
          <div className="mt-3 grid max-h-[420px] gap-2 overflow-auto pr-1">
            {actions.length ? (
              actions.map((action) => (
                <div key={action.action_id} className="border border-line bg-command/60 p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{action.action_type}</span>
                    <StatusBadge label={action.status} tone={actionTone(action.status)} />
                  </div>
                  <p className="mt-2 text-slate-300">{action.message}</p>
                  <p className="mt-2 text-xs text-slate-500">{action.target}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-400">No actions generated.</p>
            )}
          </div>
        </section>
      </div>

      <section className="mx-4 mb-4 border border-line bg-panel p-4">
        <h2 className="text-base font-semibold">Trace And Evidence</h2>
        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {(traceEvents.length ? traceEvents : assessment?.trace || []).map((event) => (
            <div key={String(event.event_id)} className="border border-line bg-command/60 p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{String(event.step)}</span>
                <StatusBadge label={String(event.tool)} tone="info" />
              </div>
              <p className="mt-2 text-xs text-slate-400">Evidence: {Array.isArray(event.evidence_ids) ? event.evidence_ids.join(", ") || "none" : "none"}</p>
              <p className="mt-1 text-xs text-slate-500">Phoenix: {String(event.phoenix_trace_id || "pending/local-disabled")}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function ProviderStrip({ status, evalResult }: { status: IntegrationStatus | null; evalResult: Record<string, unknown> | null }) {
  const fivetranRun = status?.fivetran?.latest_run as Record<string, unknown> | null | undefined;
  const evalChecks = evalResult?.checks as Record<string, boolean> | undefined;
  const passed = evalChecks ? Object.values(evalChecks).filter(Boolean).length : 0;
  return (
    <section className="grid gap-2 border-b border-line bg-panel/70 px-4 py-3 md:grid-cols-4">
      <ProviderCard
        title="Fivetran"
        icon={<Database size={16} />}
        value={fivetranRun ? String(fivetranRun.status) : "waiting"}
        detail={`dataset ${String(status?.fivetran?.bigquery_dataset || status?.fivetran?.dataset || "fireguard_ingestion")}`}
        tone={status?.fivetran?.configured ? "ok" : "warn"}
      />
      <ProviderCard
        title="Elastic"
        icon={<Database size={16} />}
        value={String(status?.elastic?.backend || "loading")}
        detail={status?.elastic?.configured ? "real cluster configured" : "memory fallback for local tests"}
        tone={status?.elastic?.configured ? "ok" : "warn"}
      />
      <ProviderCard
        title="Gemini"
        icon={<Activity size={16} />}
        value={String(status?.gemini?.model || "gemini-2.5-flash")}
        detail={status?.gemini?.configured ? "Google Cloud project configured" : "tool API ready, project needed"}
        tone={status?.gemini?.configured ? "ok" : "warn"}
      />
      <ProviderCard
        title="Arize Phoenix"
        icon={<Activity size={16} />}
        value={evalResult ? `eval ${Math.round(Number(evalResult.score || 0) * 100)}%` : "trace-ready"}
        detail={evalChecks ? `${passed}/${Object.keys(evalChecks).length} eval checks passed` : String(status?.arize?.endpoint || "localhost:6006")}
        tone={status?.arize?.enabled ? "ok" : "warn"}
      />
    </section>
  );
}

function ProviderCard({ title, icon, value, detail, tone }: { title: string; icon: ReactNode; value: string; detail: string; tone: "ok" | "warn" }) {
  return (
    <div className="border border-line bg-command/70 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          {icon}
          {title}
        </div>
        <StatusBadge label={tone === "ok" ? "active" : "needs key"} tone={tone} />
      </div>
      <p className="mt-2 text-sm text-slate-200">{value}</p>
      <p className="mt-1 text-xs text-slate-500">{detail}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-line bg-command/70 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}
