export type GeoPoint = { lat: number; lon: number };

export type Zone = {
  zone_id: string;
  name: string;
  data_origin?: string;
  source_label?: string;
  synthetic?: boolean;
  geometry: GeoJSON.Polygon;
  centroid: GeoPoint;
  population: number;
  households: number;
  vulnerable_count: number;
  vehicle_access_score: number;
  priority_notes: string;
};

export type Shelter = {
  shelter_id: string;
  name: string;
  data_origin?: string;
  source_label?: string;
  synthetic?: boolean;
  location: GeoPoint;
  capacity_total: number;
  capacity_available: number;
  capacity_is_operator_assumption?: boolean;
  capacity_operator_confirmed?: boolean;
  capacity_source_label?: string;
  capacity_confirmed_at?: string;
  capacity_confirmed_by?: string;
  official_facility_status?: string;
  status: string;
  medical_support: boolean;
  accessible: boolean;
  pet_friendly: boolean;
};

export type FireHotspot = {
  external_id: string;
  source: string;
  location: GeoPoint;
  confidence: string;
  frp: number;
};

export type RoadEvent = {
  external_id: string;
  title: string;
  description: string;
  event_type: string;
  severity: string;
  road_name: string;
  location: GeoPoint;
  geometry?: GeoJSON.LineString | null;
};

export type Perimeter = {
  fire_number: string;
  fire_name: string;
  status: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
};

export type PublicEvacuationOrder = {
  order_alert_id: string;
  event_name: string;
  event_type: string;
  order_alert_name: string;
  status: string;
  issuing_agency: string;
  population: number;
  homes: number;
  location: GeoPoint;
  source_url?: string;
};

export type PublicEssFacility = {
  facility_id: string;
  name: string;
  facility_type: string;
  community: string;
  municipality: string;
  status: string;
  location: GeoPoint;
  source_url?: string;
};

export type IncidentContext = {
  incident_id: string;
  mode: string;
  store_backend: string;
  fires: FireHotspot[];
  perimeters: Perimeter[];
  road_events: RoadEvent[];
  weather: Record<string, unknown>;
  zones: Zone[];
  shelters: Shelter[];
  public_evacuation_orders?: PublicEvacuationOrder[];
  public_ess_facilities?: PublicEssFacility[];
  operational_assumptions?: Array<Record<string, unknown>>;
  data_freshness: Array<Record<string, unknown>>;
  provider_status: Record<string, Record<string, unknown>>;
  demo_disclosures: Array<Record<string, unknown>>;
};

export type ZoneRisk = {
  zone_id: string;
  risk_level: "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
  score: number;
  urgency_minutes: number;
  confidence: number;
  reasoning_factors: string[];
  evidence_ids: string[];
};

export type RouteOption = {
  origin_id: string;
  destination_id: string;
  duration_minutes: number;
  distance_km: number;
  safe: boolean;
  risk_flags: string[];
  polyline: GeoPoint[];
  evidence_ids: string[];
  assumption_ids?: string[];
};

export type PlanStep = {
  step_id: string;
  zone_id: string;
  strategy: string;
  destination_id: string | null;
  start_after_minutes: number;
  message: string;
  rationale: string[];
  evidence_ids: string[];
  assumption_ids?: string[];
};

export type EvacuationPlan = {
  plan_id: string;
  incident_id: string;
  summary: string;
  recommended_strategy: string;
  confidence: number;
  zone_risks: ZoneRisk[];
  routes: RouteOption[];
  steps: PlanStep[];
  rejected_alternatives: Array<Record<string, unknown>>;
  operational_assumptions?: Array<Record<string, unknown>>;
  data_freshness: Array<Record<string, unknown>>;
  risks_if_wrong: string[];
  fallback_plan: string;
  requires_approval: boolean;
};

export type ActionItem = {
  action_id: string;
  bundle_id: string;
  action_type: string;
  target: string;
  status: string;
  message: string;
  payload: Record<string, unknown>;
  reason: string;
  assumption_ids?: string[];
  confidence: number;
  external_system: string;
  is_simulated_endpoint: boolean;
  simulation_label?: string | null;
  requires_human_approval: boolean;
};

export type Approval = {
  approval_id: string;
  bundle_id: string;
  status: string;
  approval_url: string;
};

export type AssessmentResult = {
  incident_id: string;
  context: IncidentContext;
  plan: EvacuationPlan;
  bundle_id: string;
  approval: Approval;
  actions: ActionItem[];
  trace: Array<Record<string, unknown>>;
  agent_review?: Record<string, unknown> | null;
  gemini_status?: string | null;
  gemini_tool_calls?: string[];
  phoenix_trace_ids?: string[];
};

export type IntegrationStatus = {
  fivetran: Record<string, unknown>;
  elastic: Record<string, unknown>;
  gemini: Record<string, unknown>;
  arize: Record<string, unknown>;
  action_tasks?: Record<string, unknown>;
};
