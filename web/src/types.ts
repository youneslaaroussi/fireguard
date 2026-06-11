export type ReplayRequest = {
  latitude: number;
  longitude: number;
  radius_km: number;
  start_date: string;
  end_date: string;
  sources: string[];
  speed: number;
};

export type FireEvent = {
  source: string;
  latitude: number;
  longitude: number;
  acquired_at: string;
  satellite?: string;
  instrument?: string;
  confidence?: string;
  frp?: number;
  brightness?: number;
  replay_second: number;
  weather?: WeatherResult | null;
  place?: PlaceResult | null;
  bcws?: BcwsMatch;
};

export type ClientConfig = {
  mapbox_access_token: string;
};

export type Stats = {
  firms_count: number;
  bcws_incident_count: number;
  bcws_perimeter_count: number;
  min_acquired_at?: string | null;
  max_acquired_at?: string | null;
  sources: SourceCount[];
};

export type ThreatPayload = {
  hotspot: {
    lat: number;
    lon: number;
    frp: number;
    confidence?: string;
    acquired_at: string;
    source: string;
  };
  zone: {
    name: string;
    population?: number;
    homes?: number;
    latitude?: number;
    longitude?: number;
    distance_km?: number;
  };
};

export type SourceCount = {
  source: string;
  count: number;
};

export type PlaceResult = {
  formatted_address?: string;
  place_id?: string;
  types?: string[];
};

export type WeatherResult = {
  time: string;
  temperature_2m?: number | null;
  relative_humidity_2m?: number | null;
  precipitation?: number | null;
  wind_speed_10m?: number | null;
  wind_direction_10m?: number | null;
  wind_gusts_10m?: number | null;
  source: string;
};

export type BcwsIncident = {
  fire_number?: string;
  incident_name?: string;
  fire_status?: string;
  current_size_ha?: number;
  fire_cause?: string;
  fire_type?: string;
  geographic_description?: string;
  fire_url?: string;
  latitude?: number;
  longitude?: number;
  distance_km?: number;
  source?: string;
};

export type BcwsPerimeter = {
  fire_number?: string;
  fire_status?: string;
  fire_size_hectares?: number;
  track_date?: string;
  load_date?: string;
  fire_url?: string;
  feature_area_sqm?: number;
  feature_length_m?: number;
  geometry?: GeoJSON.Geometry;
  source?: string;
};

export type BcwsContext = {
  incidents: BcwsIncident[];
  perimeters: BcwsPerimeter[];
  evacuation_zones: EvacuationZone[];
  evacuation_records: EvacuationRecord[];
  ess_facilities: EssFacility[];
  road_events: RoadEvent[];
  weather_snapshot?: ReplayWeatherSnapshot | null;
  policy_snippets: PolicySnippet[];
};

export type BcwsMatch = {
  incident?: BcwsIncident | null;
  perimeter?: BcwsPerimeter | null;
};

export type ReplayMessage =
  | { type: "started"; area: string }
  | ({
      type: "context";
      cached: boolean;
      incidents: BcwsIncident[];
      perimeters: BcwsPerimeter[];
    } & ReplayLocalContext)
  | { type: "chunk_start"; source: string; start_date: string; days: number; cached: boolean }
  | { type: "chunk"; source: string; start_date: string; days: number; cached: boolean; indexed: number }
  | ({ type: "threat" } & ThreatPayload)
  | { type: "event"; event: FireEvent }
  | { type: "done"; events: number }
  | { type: "error"; error: string };

export type ReplayLocalContext = {
  evacuation_zones: EvacuationZone[];
  evacuation_records: EvacuationRecord[];
  ess_facilities: EssFacility[];
  road_events: RoadEvent[];
  weather_snapshot?: ReplayWeatherSnapshot | null;
  policy_snippets: PolicySnippet[];
};

export type EvacuationZone = {
  id?: string | number;
  event_name?: string;
  event_type?: string;
  order_alert_name?: string;
  status?: string;
  issuing_agency?: string;
  municipality?: string;
  population?: number;
  homes?: number;
  event_start_date?: string;
  all_clear_date?: string;
  geometry?: GeoJSON.Geometry;
  source?: string;
  source_url?: string;
};

export type EvacuationRecord = {
  order_alert_id?: string;
  event_name?: string;
  event_type?: string;
  order_alert_name?: string;
  status?: string;
  issuing_agency?: string;
  population?: number;
  homes?: number;
  latitude?: number;
  longitude?: number;
  event_start_date?: string;
  updated_at?: string;
  source?: string;
  source_url?: string;
};

export type EssFacility = {
  facility_id?: string;
  name?: string;
  facility_type?: string;
  address?: string;
  community?: string;
  municipality?: string;
  status?: string;
  latitude?: number;
  longitude?: number;
  updated_at?: string;
  source?: string;
  source_url?: string;
};

export type RoadEvent = {
  source?: string;
  external_id?: string;
  title?: string;
  description?: string;
  event_type?: string;
  severity?: string;
  road_name?: string;
  latitude?: number;
  longitude?: number;
  geometry?: GeoJSON.Geometry;
  starts_at?: string;
  ends_at?: string | null;
  updated_at?: string;
  source_url?: string;
};

export type ReplayWeatherSnapshot = {
  source?: string;
  latitude?: number;
  longitude?: number;
  wind_speed_kph?: number;
  wind_direction_degrees?: number;
  wind_gusts_kph?: number;
  forecast_horizon_hours?: number;
};

export type PolicySnippet = {
  policy_id?: string;
  title?: string;
  source?: string;
  source_url?: string;
  body?: string;
  applies_to?: string[];
};
