from typing import Any, Literal

from pydantic import BaseModel, Field


ActionStatus = Literal["pending", "approved", "rejected", "executed", "failed", "sent", "draft"]
RiskLevel = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]


class GeoPoint(BaseModel):
    lat: float
    lon: float


class SourceRecord(BaseModel):
    id: str
    source: str
    source_url: str | None = None
    updated_at: str
    ingested_at: str
    freshness_minutes: float
    stale: bool = False


class ZoneRisk(BaseModel):
    zone_id: str
    risk_level: RiskLevel
    score: float
    urgency_minutes: int
    confidence: float
    reasoning_factors: list[str]
    evidence_ids: list[str]


class RouteOption(BaseModel):
    origin_id: str
    destination_id: str
    duration_minutes: int
    distance_km: float
    safe: bool
    risk_flags: list[str]
    polyline: list[GeoPoint]
    evidence_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)
    route_source: str = "deterministic_fallback"
    provider_error: str | None = None


class PlanStep(BaseModel):
    step_id: str
    zone_id: str
    strategy: str
    destination_id: str | None
    start_after_minutes: int
    message: str
    rationale: list[str]
    evidence_ids: list[str]
    assumption_ids: list[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    action_id: str
    bundle_id: str
    action_type: str
    target: str
    status: ActionStatus
    message: str
    payload: dict[str, Any]
    reason: str
    evidence_ids: list[str]
    assumption_ids: list[str] = Field(default_factory=list)
    confidence: float
    external_system: str
    is_simulated_endpoint: bool
    simulation_label: str | None = None
    requires_human_approval: bool = True
    created_at: str
    approved_at: str | None = None
    executed_at: str | None = None


class EvacuationPlan(BaseModel):
    plan_id: str
    incident_id: str
    summary: str
    recommended_strategy: str
    confidence: float
    zone_risks: list[ZoneRisk]
    routes: list[RouteOption]
    steps: list[PlanStep]
    rejected_alternatives: list[dict[str, Any]]
    operational_assumptions: list[dict[str, Any]] = Field(default_factory=list)
    data_freshness: list[dict[str, Any]]
    risks_if_wrong: list[str]
    fallback_plan: str
    requires_approval: bool = True


class Approval(BaseModel):
    approval_id: str
    bundle_id: str
    status: Literal["pending", "approved", "rejected"]
    approver_role: str
    approval_url: str
    created_at: str
    decided_at: str | None = None


class AssessmentResult(BaseModel):
    incident_id: str
    context: dict[str, Any]
    plan: EvacuationPlan
    bundle_id: str
    approval: Approval
    actions: list[ActionItem]
    trace: list[dict[str, Any]]
    agent_review: dict[str, Any] | None = None
    gemini_status: str | None = None
    gemini_tool_calls: list[str] = Field(default_factory=list)
    phoenix_trace_ids: list[str] = Field(default_factory=list)


class ToolRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
