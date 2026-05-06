import type { AssessmentResult, IncidentContext, IntegrationStatus } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export function getCurrentIncident() {
  return request<IncidentContext>("/incidents/current");
}

export function resetDemo() {
  return request<{ status: string }>("/ingest/synthetic/reset-demo", { method: "POST" });
}

export function runAssessment() {
  return request<AssessmentResult>("/incidents/assess", { method: "POST" });
}

export function approveBundle(approvalId: string) {
  return request<{ approval: AssessmentResult["approval"]; actions: AssessmentResult["actions"] }>(`/approvals/${approvalId}/approve`, { method: "POST" });
}

export function executeBundle(bundleId: string) {
  return request<{ bundle_id: string; executed: AssessmentResult["actions"]; failed: AssessmentResult["actions"]; skipped?: AssessmentResult["actions"] }>(`/actions/${bundleId}/execute`, { method: "POST" });
}

export function getTraces(incidentId: string) {
  return request<{ incident_id: string; traces: Array<Record<string, unknown>>; latest: { events: Array<Record<string, unknown>> } | null }>(`/traces/${incidentId}`);
}

export function getIntegrationStatus() {
  return request<IntegrationStatus>("/integrations/status");
}

export function syncFivetranToElastic() {
  return request<Record<string, unknown>>("/sync/fivetran-to-elastic", { method: "POST" });
}

export function runEval(incidentId: string) {
  return request<Record<string, unknown>>(`/evals/${incidentId}`, { method: "POST" });
}
