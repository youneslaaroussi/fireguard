import type { AssessmentResult, IncidentContext, IntegrationStatus } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export type SlimContext = {
  fires: Array<{ external_id: string; frp: number; source: string }>;
  zones: Array<{ zone_id: string; name: string; population: number; vulnerable_count: number }>;
  road_events: Array<{ external_id: string; road_name: string; title: string }>;
};

export type StreamEvent =
  | { type: "step"; event: Record<string, unknown>; slim_context?: SlimContext }
  | { type: "thinking"; step: string; message: string }
  | { type: "complete"; result: AssessmentResult }
  | { type: "error"; message: string };

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

export async function streamAssessment(
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<AssessmentResult> {
  const response = await fetch(`${API_BASE_URL}/incidents/assess/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: AssessmentResult | null = null;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data: ")) continue;
        const data = JSON.parse(line.slice(6)) as StreamEvent;
        onEvent(data);
        if (data.type === "complete") finalResult = data.result;
        if (data.type === "error") throw new Error(data.message);
      }
    }
  } finally {
    reader.releaseLock();
  }
  if (!finalResult) throw new Error("Assessment stream ended without a result");
  return finalResult;
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

export function getActionLogs() {
  return request<{ actions: import("./types").ActionItem[] }>("/action-logs");
}

export function getIntegrationStatus() {
  return request<IntegrationStatus>("/integrations/status");
}

export function syncFivetranToElastic() {
  return request<Record<string, unknown>>("/sync/fivetran-to-elastic", { method: "POST" });
}

export function syncLiveOverlay() {
  return request<Record<string, unknown>>("/sync/live-overlay", { method: "POST" });
}

export function syncShelterCapacitySheet() {
  return request<Record<string, unknown>>("/sync/google-sheets-shelter-capacity", { method: "POST" });
}

export function syncSourceBackedZoneContext() {
  return request<Record<string, unknown>>("/sync/source-backed-zone-context", { method: "POST" });
}

export function runEval(incidentId: string) {
  return request<Record<string, unknown>>(`/evals/${incidentId}`, { method: "POST" });
}

export function confirmShelterCapacity(shelterId: string, capacityAvailable: number, capacityTotal: number) {
  return request<Record<string, unknown>>(`/shelters/${shelterId}/capacity-check-in`, {
    method: "POST",
    body: JSON.stringify({
      capacity_available: capacityAvailable,
      capacity_total: capacityTotal,
      updated_by: "operator",
      note: "Capacity confirmed from the FireGuard operator UI.",
    }),
  });
}

export function registerResidentTestContact(zoneId: string, phone: string) {
  return request<Record<string, unknown>>("/resident-contacts/test-check-in", {
    method: "POST",
    body: JSON.stringify({
      zone_id: zoneId,
      phone,
      updated_by: "operator",
      consent_label: "Operator confirmed this is an opt-in, Twilio-verified test recipient.",
      note: "Resident test contact registered from the FireGuard operator UI.",
    }),
  });
}
