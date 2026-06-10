export type ReplayRequest = {
  latitude: number;
  longitude: number;
  radius_km: number;
  start_date: string;
  end_date: string;
  sources: string[];
  speed: number;
  limit: number;
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
};

export type BcwsMatch = {
  incident?: BcwsIncident | null;
  perimeter?: BcwsPerimeter | null;
};

export type ReplayMessage =
  | { type: "started"; area: string }
  | { type: "context"; cached: boolean; incidents: BcwsIncident[]; perimeters: BcwsPerimeter[] }
  | { type: "chunk_start"; source: string; start_date: string; days: number; cached: boolean }
  | { type: "chunk"; source: string; start_date: string; days: number; cached: boolean; indexed: number }
  | { type: "events"; source: string; start_date: string; days: number; cached: boolean; indexed: number; events: FireEvent[] }
  | { type: "done"; events: number }
  | { type: "error"; error: string };
