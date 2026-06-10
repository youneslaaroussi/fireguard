import { useEffect, useState } from "react";
import { getConfig, getStats, replay } from "../api";
import type { BcwsContext, FireEvent, ReplayRequest, Stats, ThreatPayload } from "../types";
import { AgenticIntelligenceApp } from "../intelligence/App";
import { AgentOrb } from "./AgentOrb";
import { EventStream } from "./EventStream";
import { MapPanel } from "./MapPanel";
import { StatsStrip } from "./StatsStrip";
import { Timeline } from "./Timeline";
import { sources } from "./state";

const initial: ReplayRequest = {
  latitude: 52.5,
  longitude: -120.0,
  radius_km: 400,
  start_date: "2024-07-17",
  end_date: "2024-07-25",
  sources,
  speed: 14400,
  limit: 5000
};

const emptyContext: BcwsContext = {
  incidents: [],
  perimeters: [],
  evacuation_zones: [],
  evacuation_records: [],
  ess_facilities: [],
  road_events: [],
  weather_snapshot: null,
  policy_snippets: []
};

function BrandMark() {
  return (
    <div className="brandMark">
      <svg className="brandFlame" viewBox="0 0 16 20" fill="none" aria-hidden="true">
        <path d="M8 0C7 4 4 6.5 4 10.5a4 4 0 0 0 8 0c0-2.2-1.3-4-2.2-5.2-.45 1.8-1.2 2.8-1.8 3.2C7.8 7 7.4 4 8 0z" fill="#ff6b4a"/>
        <ellipse cx="8" cy="10.8" rx="1.5" ry="1.7" fill="#ffd0b0" opacity="0.65"/>
      </svg>
      <div className="brandText">
        <span className="brandName">FIREGUARD</span>
        <span className="brandSub">WILDFIRE INTELLIGENCE</span>
      </div>
    </div>
  );
}

export function App() {
  const [view, setView] = useState<"replay" | "intelligence">("replay");
  const [request, setRequest] = useState<ReplayRequest>(initial);
  const [events, setEvents] = useState<FireEvent[]>([]);
  const [context, setContext] = useState<BcwsContext>(emptyContext);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mapboxToken, setMapboxToken] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [replayProgress, setReplayProgress] = useState(0);
  const [status, setStatus] = useState("Idle");
  const [threatAlert, setThreatAlert] = useState<ThreatPayload | null>(null);
  const sessionContext = buildSessionContext(request, status, busy, events, context, stats, threatAlert);

  useEffect(() => {
    getConfig().then((config) => setMapboxToken(config.mapbox_access_token)).catch((err) => setError(String(err)));
    getStats().then(setStats).catch((err) => setError(String(err)));
  }, []);

  async function startReplay() {
    setBusy(true);
    setError(null);
    setEvents([]);
    setContext(emptyContext);
    setThreatAlert(null);
    setReplayProgress(0);
    setStatus("Starting");
    try {
      await replay(request, (message) => {
        if (message.type === "started") {
          setStatus(`Preparing ${message.area}`);
        } else if (message.type === "context") {
          setContext({
            incidents: message.incidents,
            perimeters: message.perimeters,
            evacuation_zones: message.evacuation_zones,
            evacuation_records: message.evacuation_records,
            ess_facilities: message.ess_facilities,
            road_events: message.road_events,
            weather_snapshot: message.weather_snapshot,
            policy_snippets: message.policy_snippets
          });
          setStatus(`${message.cached ? "Cached" : "Loaded"} — ${message.incidents.length.toLocaleString()} incidents · ${message.perimeters.length.toLocaleString()} perimeters · ${message.evacuation_zones.length.toLocaleString()} evac zones`);
        } else if (message.type === "chunk_start") {
          setStatus(`${message.cached ? "Cache" : "Fetch"} ${message.source} ${message.start_date}`);
        } else if (message.type === "chunk") {
          setStatus(`${message.cached ? "Cached" : "Indexed"} ${message.source}: ${message.indexed.toLocaleString()}`);
        } else if (message.type === "event") {
          setEvents((current) => [...current, message.event]);
          setReplayProgress(progressForEvent(message.event, request));
          setStatus(`Replay ${message.event.acquired_at.slice(0, 16).replace("T", " ")} · ${message.event.source}`);
        } else if (message.type === "threat") {
          const payload = { hotspot: message.hotspot, zone: message.zone };
          setThreatAlert(payload);
        } else if (message.type === "done") {
          setReplayProgress(1);
          setStatus(`Complete · ${message.events.toLocaleString()} detections`);
        } else if (message.type === "error") {
          setError(message.error);
        }
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={view === "replay" ? "shell--replay" : "shell--intelligence"}>
      {view === "replay" ? (
        <>
          <MapPanel
            token={mapboxToken}
            events={events}
            context={context}
            lat={request.latitude}
            lon={request.longitude}
            radiusKm={request.radius_km}
            onAreaChange={(lat, lon, radiusKm) =>
              setRequest((r) => ({ ...r, latitude: lat, longitude: lon, radius_km: Math.round(radiusKm) }))
            }
          />

          <header className="appHeader">
            <div className="headerRow">
              <BrandMark />
              <div className="headerSep" />
              <StatsStrip value={stats} />
              <div className="headerFill" />
              {threatAlert !== null && (
                <div className="threatChip">
                  <span className="threatDot" />
                  {threatAlert.zone.name}
                </div>
              )}
              <div className={`acqChip${busy ? " acqChip--on" : ""}`}>
                <span className="acqDot" />
                {busy ? "ACQUIRING" : "IDLE"}
              </div>
            </div>

            <Timeline
              start={request.start_date}
              end={request.end_date}
              progress={replayProgress}
              status={status}
              busy={busy}
              onReplay={() => void startReplay()}
            />

            {error && (
              <div className="errorBar">
                <span className="errorLabel">ERR</span>
                <span className="errorMsg">{error}</span>
                <button className="errorClose" onClick={() => setError(null)}>✕</button>
              </div>
            )}
          </header>

          <EventStream events={events} />
          <AgentOrb sessionContext={sessionContext} />
        </>
      ) : (
        <>
          <header className="appHeader appHeader--minimal">
            <div className="headerRow">
              <BrandMark />
              <div className="headerSep" />
              <button className="navChip" onClick={() => setView("replay")}>← REPLAY MAP</button>
              <div className="headerFill" />
              {threatAlert !== null && (
                <div className="threatChip">
                  <span className="threatDot" />
                  THREAT · {threatAlert.zone.name}
                </div>
              )}
            </div>
          </header>
          <AgenticIntelligenceApp />
        </>
      )}
    </div>
  );
}

function progressForEvent(event: FireEvent, request: ReplayRequest) {
  const start = Date.parse(`${request.start_date}T00:00:00Z`);
  const end = Date.parse(`${request.end_date}T00:00:00Z`) + 24 * 60 * 60 * 1000;
  const acquired = Date.parse(event.acquired_at);
  const span = end - start;
  if (!Number.isFinite(acquired) || span <= 0) return 0;
  return Math.min(1, Math.max(0, (acquired - start) / span));
}

function buildSessionContext(
  request: ReplayRequest,
  status: string,
  busy: boolean,
  events: FireEvent[],
  context: BcwsContext,
  stats: Stats | null,
  threatAlert: ThreatPayload | null,
) {
  const latestEvent = events[events.length - 1] ?? null;
  return {
    source: "fireguard_replay_ui",
    replay: {
      latitude: request.latitude,
      longitude: request.longitude,
      radius_km: request.radius_km,
      start_date: request.start_date,
      end_date: request.end_date,
      sources: request.sources,
      speed: request.speed,
      limit: request.limit,
      status,
      phase: busy ? "acquiring_or_replaying" : "idle",
      streamed_event_count: events.length,
      latest_event: latestEvent === null ? null : compactEvent(latestEvent),
    },
    corpus: stats === null ? null : {
      firms_count: stats.firms_count,
      min_acquired_at: stats.min_acquired_at,
      max_acquired_at: stats.max_acquired_at,
      sources: stats.sources,
      bcws_incident_count: stats.bcws_incident_count,
      bcws_perimeter_count: stats.bcws_perimeter_count,
    },
    map_context: {
      incidents: context.incidents.length,
      perimeters: context.perimeters.length,
      evacuation_zones: context.evacuation_zones.length,
      evacuation_records: context.evacuation_records.length,
      ess_facilities: context.ess_facilities.length,
      road_events: context.road_events.length,
      weather_snapshot_available: context.weather_snapshot != null,
    },
    threat_alert: threatAlert,
  };
}

function compactEvent(event: FireEvent) {
  return {
    source: event.source,
    acquired_at: event.acquired_at,
    latitude: event.latitude,
    longitude: event.longitude,
    confidence: event.confidence,
    frp: event.frp,
    brightness: event.brightness,
    bcws: event.bcws,
  };
}
