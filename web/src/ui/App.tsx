import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getConfig, getStats, replay } from "../api";
import type { BcwsContext, FireEvent, ReplayRequest, Stats, ThreatPayload } from "../types";
import type { ActionPlan, MapAnnotation } from "../intelligence/types";
import { AgenticIntelligenceApp } from "../intelligence/App";
import { ActionsPanel } from "./ActionsPanel";
import { EventStream } from "./EventStream";
import { KpiStrip } from "./KpiStrip";
import { MapPanel } from "./MapPanel";
import { Sidebar } from "./Sidebar";
import { Timeline } from "./Timeline";
import { sources } from "./state";

const initial: ReplayRequest = {
  latitude: 52.5,
  longitude: -120.0,
  radius_km: 400,
  start_date: "2024-07-17",
  end_date: "2024-07-25",
  sources,
  speed: 43200
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
      <span className="brandName">FIREGUARD</span>
    </div>
  );
}

function formatWindow(start: string, end: string) {
  const a = new Date(`${start}T00:00:00Z`);
  const b = new Date(`${end}T00:00:00Z`);
  if (Number.isNaN(a.valueOf()) || Number.isNaN(b.valueOf())) return `${start} – ${end}`;
  const month = (d: Date) => d.toLocaleString("en-US", { month: "short", timeZone: "UTC" }).toUpperCase();
  const sameMonth = a.getUTCMonth() === b.getUTCMonth() && a.getUTCFullYear() === b.getUTCFullYear();
  if (sameMonth) return `${month(a)} ${a.getUTCDate()}–${b.getUTCDate()} ${b.getUTCFullYear()}`;
  return `${month(a)} ${a.getUTCDate()} – ${month(b)} ${b.getUTCDate()} ${b.getUTCFullYear()}`;
}

export function App() {
  const [request, setRequest] = useState<ReplayRequest>(initial);
  const [events, setEvents] = useState<FireEvent[]>([]);
  const [context, setContext] = useState<BcwsContext>(emptyContext);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const [mapboxToken, setMapboxToken] = useState("");
  const [googleMapsKey, setGoogleMapsKey] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [replayProgress, setReplayProgress] = useState(0);
  const [status, setStatus] = useState("Idle");
  const [threatAlert, setThreatAlert] = useState<ThreatPayload | null>(null);
  const [intelligencePrompt, setIntelligencePrompt] = useState<string | null>(null);
  const [mapAnnotation, setMapAnnotation] = useState<MapAnnotation | null>(null);
  const [actionPlan, setActionPlan] = useState<ActionPlan | null>(null);
  const [actionsOpen, setActionsOpen] = useState(true);
  const [rightTab, setRightTab] = useState<"map" | "graph">("map");
  const [chatSlot, setChatSlot] = useState<HTMLDivElement | null>(null);
  const [externalPrompt, setExternalPrompt] = useState<{ text: string; id: number } | null>(null);
  const externalPromptCounter = useRef(0);
  const [simDate, setSimDate] = useState<string | null>(null);
  const sessionContext = buildSessionContext(request, status, busy, events, context, stats, threatAlert);
  const spokenThreatRef = useRef<string | null>(null);
  const maxThreatScore = useMemo(
    () => events.reduce((m, e) => Math.max(m, e.threat_score ?? 0), 0),
    [events]
  );

  const speak = useCallback(async (text: string) => {
    try {
      const res = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) return;
      const buf = await res.arrayBuffer();
      const ctx = new AudioContext();
      const decoded = await ctx.decodeAudioData(buf);
      const src = ctx.createBufferSource();
      src.buffer = decoded;
      src.connect(ctx.destination);
      src.start();
    } catch {
      // TTS is best-effort
    }
  }, []);

  useEffect(() => {
    getConfig().then((config) => {
      setMapboxToken(config.mapbox_access_token);
      setGoogleMapsKey(config.google_maps_api_key);
    }).catch((err) => setError(String(err)));
    getStats().then(setStats).catch((err) => setError(String(err)));
  }, []);

  async function startReplay() {
    setBusy(true);
    setError(null);
    setEvents([]);
    setContext(emptyContext);
    setThreatAlert(null);
    setIntelligencePrompt(null);
    setMapAnnotation(null);
    setActionPlan(null);
    setSimDate(null);
    spokenThreatRef.current = null;
    setReplayProgress(0);
    setPaused(false);
    pausedRef.current = false;
    setStatus("Starting");
    // Batch streamed events so the table/map render ~8x/s instead of per event
    const eventBuffer: FireEvent[] = [];
    let flushTimer: number | null = null;
    const flush = () => {
      flushTimer = null;
      if (eventBuffer.length === 0) return;
      const batch = eventBuffer.splice(0);
      const last = batch[batch.length - 1];
      setEvents((current) => [...current, ...batch]);
      setReplayProgress(progressForEvent(last, request));
      setStatus(`Replay ${last.acquired_at.slice(0, 16).replace("T", " ")} · ${last.source}`);
    };
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
          eventBuffer.push(message.event);
          if (flushTimer === null) flushTimer = window.setTimeout(flush, 120);
          const acquired = message.event.acquired_at;
          if (acquired) setSimDate(acquired.slice(0, 16).replace("T", " ") + " UTC");
        } else if (message.type === "threat") {
          flush();
          const payload = { hotspot: message.hotspot, zone: message.zone };
          setThreatAlert(payload);
          setIntelligencePrompt(buildEvacuationPrompt(payload, request));
          if (spokenThreatRef.current !== payload.zone.name) {
            spokenThreatRef.current = payload.zone.name;
            void speak(`Threat detected. High-confidence fire hotspot near ${payload.zone.name}. FireGuard intelligence is analyzing evacuation routes.`);
          }
        } else if (message.type === "done") {
          flush();
          setReplayProgress(1);
          setStatus(`Complete · ${message.events.toLocaleString()} detections`);
        } else if (message.type === "error") {
          setError(message.error);
        }
      }, () => pausedRef.current);
    } catch (err) {
      setError(String(err));
    } finally {
      if (flushTimer !== null) window.clearTimeout(flushTimer);
      flush();
      setBusy(false);
      setPaused(false);
      pausedRef.current = false;
    }
  }

  function togglePause() {
    setPaused((p) => {
      pausedRef.current = !p;
      return !p;
    });
  }

  return (
    <div className="shell--replay">
      <header className={`appHeader${busy ? " appHeader--acquiring" : ""}`}>
        <BrandMark />
        <span className="headerCrumbSep">›</span>
        <span className="headerCrumb">REPLAY · {formatWindow(request.start_date, request.end_date)}</span>
        <span className="headerCrumbSep">›</span>
        <span className="headerCrumb headerCrumb--dim">CARIBOO FIRE CENTRE, BC</span>
        <div className="headerFill" />
        {maxThreatScore > 0 && (
          <span className={`scoreChip ${maxThreatScore >= 75 ? "scoreChip--critical" : maxThreatScore >= 50 ? "scoreChip--high" : maxThreatScore >= 25 ? "scoreChip--moderate" : "scoreChip--low"}`}>
            RISK {maxThreatScore}
          </span>
        )}
        {threatAlert !== null && (
          <button className="statusChip statusChip--threat" type="button">
            THREAT · {threatAlert.zone.name}
          </button>
        )}
        <div className={`statusChip${busy ? " statusChip--on" : ""}`}>
          {busy ? "ACQUIRING" : "IDLE"}
        </div>
      </header>

      {error && (
        <div className="errorBar">
          <span className="errorLabel">ERR</span>
          <span className="errorMsg">{error}</span>
          <button className="errorClose" onClick={() => setError(null)}>✕</button>
        </div>
      )}

      <KpiStrip events={events} context={context} threat={threatAlert} busy={busy} />

      <div className="appMain">
        <Sidebar
          request={request}
          onRequestChange={setRequest}
          context={context}
          stats={stats}
          busy={busy}
          annotation={mapAnnotation}
          events={events}
          threat={threatAlert}
          status={status}
        />

        <section className="centerPanel">
          <Timeline
            start={request.start_date}
            end={request.end_date}
            progress={replayProgress}
            status={status}
            busy={busy}
            paused={paused}
            speed={request.speed}
            onSpeedChange={(speed) => setRequest((r) => ({ ...r, speed }))}
            onReplay={() => void startReplay()}
            onTogglePause={togglePause}
          />
          <EventStream events={events} busy={busy} />
        </section>

        <section className="rightPanel">
          {/* Tab bar */}
          <div className="rightTabs">
            <button
              className={`rightTab${rightTab === "map" ? " rightTab--active" : ""}`}
              onClick={() => setRightTab("map")}
            >
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <rect x="1" y="1" width="10" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.4"/>
                <path d="M1 4h10" stroke="currentColor" strokeWidth="1"/>
              </svg>
              MAP
            </button>
            <button
              className={`rightTab${rightTab === "graph" ? " rightTab--active" : ""}${threatAlert ? " rightTab--alert" : ""}`}
              onClick={() => setRightTab("graph")}
            >
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <circle cx="6" cy="2" r="1.3" fill="currentColor"/>
                <circle cx="2" cy="9" r="1.3" fill="currentColor"/>
                <circle cx="10" cy="9" r="1.3" fill="currentColor"/>
                <line x1="6" y1="3.3" x2="2" y2="7.7" stroke="currentColor" strokeWidth="1"/>
                <line x1="6" y1="3.3" x2="10" y2="7.7" stroke="currentColor" strokeWidth="1"/>
              </svg>
              INTELLIGENCE
            </button>
          </div>

          {/* Map view — always mounted, hidden when graph tab active */}
          <div className={`rightPanelMap${rightTab === "map" ? "" : " rightPanelMap--hidden"}`}>
            <MapPanel
              token={mapboxToken}
              googleMapsKey={googleMapsKey}
              events={events}
              context={context}
              lat={request.latitude}
              lon={request.longitude}
              radiusKm={request.radius_km}
              annotation={mapAnnotation}
              threat={threatAlert}
              simDate={simDate}
              annotationActive={mapAnnotation !== null}
              busy={busy}
              onAreaChange={(lat, lon, radiusKm) =>
                setRequest((r) => ({ ...r, latitude: lat, longitude: lon, radius_km: Math.round(radiusKm) }))
              }
            />
            {threatAlert !== null && (
              <ThreatAlert threat={threatAlert} />
            )}
            {actionPlan !== null && actionsOpen && (
              <div className="actionsPopup">
                <ActionsPanel
                  plan={actionPlan}
                  onDismiss={() => setActionsOpen(false)}
                  onAct={(text) => {
                    externalPromptCounter.current += 1;
                    setExternalPrompt({ text, id: externalPromptCounter.current });
                  }}
                />
              </div>
            )}
            {actionPlan !== null && !actionsOpen && (
              <button className="actionsReopenBtn" type="button" onClick={() => setActionsOpen(true)}>
                <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm.75 9.5h-1.5v-4h1.5v4zm0-5.5h-1.5V3.5h1.5V5z" fill="#facc15"/>
                </svg>
                ACTIONS
                <span className="actionsReopenCount">{actionPlan.actions.length}</span>
              </button>
            )}
          </div>

          {/* Intelligence/graph view — hideChat=false but chat renders via chatSlotRef portal */}
          <div className={`rightPanelGraph${rightTab === "graph" ? "" : " rightPanelGraph--hidden"}`}>
            <AgenticIntelligenceApp
              autoPrompt={intelligencePrompt}
              externalPrompt={externalPrompt}
              workflowId="fireguard_evacuation"
              sessionContext={sessionContext}
              threat={threatAlert}
              mode="embedded"
              googleMapsKey={googleMapsKey}
              hideChat={false}
              chatPortalTarget={chatSlot}
              onAnnotation={setMapAnnotation}
              onActions={(plan) => { setActionPlan(plan); setActionsOpen(true); }}
              onSpeakMessage={speak}
            />
          </div>

          {/* Chat slot — always visible below both tabs, chat is portalled here */}
          <div className="rightPanelChat" ref={(el) => { if (el && el !== chatSlot) setChatSlot(el); }} />
        </section>
      </div>

    </div>
  );
}

function estimateEtaMinutes(frp: number, distanceKm?: number): number | null {
  if (distanceKm == null || distanceKm <= 0) return null;
  // Rough ROS heuristic: 0.4 km/h baseline + 0.06 km/h per MW of FRP, capped 6 km/h
  const kph = Math.min(6, 0.4 + 0.06 * frp);
  if (kph <= 0) return null;
  return (distanceKm / kph) * 60;
}

function ThreatAlert({ threat }: { threat: ThreatPayload }) {
  const { hotspot, zone } = threat;
  const etaMin = estimateEtaMinutes(hotspot.frp, zone.distance_km);
  const etaText = etaMin == null
    ? null
    : etaMin < 60
      ? `${Math.round(etaMin)} MIN`
      : `${(etaMin / 60).toFixed(1)} HR`;
  return (
    <div className="threatAlert">
      <div className="threatAlertPulse" />
      <div className="threatAlertBody">
        <div className="threatAlertHead">
          <svg className="threatAlertIcon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="M10 1L1 18h18L10 1z" fill="#ff3a2a" opacity="0.15"/>
            <path d="M10 1L1 18h18L10 1z" stroke="#ff3a2a" strokeWidth="1.5" strokeLinejoin="round"/>
            <rect x="9.25" y="7" width="1.5" height="6" rx="0.75" fill="#ff3a2a"/>
            <rect x="9.25" y="14.5" width="1.5" height="1.5" rx="0.75" fill="#ff3a2a"/>
          </svg>
          <span className="threatAlertTitle">THREAT DETECTED</span>
          <span className="threatAlertZone">{zone.name}</span>
          {etaText && (
            <span className="threatAlertEta">
              <span className="threatAlertEtaLabel">ETA TO ZONE</span>
              <span className="threatAlertEtaValue">{etaText}</span>
            </span>
          )}
        </div>
        <div className="threatAlertStats">
          <span><span className="threatAlertKey">FRP</span><span className="threatAlertVal">{hotspot.frp.toFixed(1)} MW</span></span>
          <span><span className="threatAlertKey">CONF</span><span className="threatAlertVal">{hotspot.confidence ?? "—"}</span></span>
          <span><span className="threatAlertKey">DIST</span><span className="threatAlertVal">{zone.distance_km != null ? `${zone.distance_km.toFixed(1)} km` : "—"}</span></span>
          <span><span className="threatAlertKey">POP</span><span className="threatAlertVal">{zone.population != null ? zone.population.toLocaleString() : "—"}</span></span>
        </div>
      </div>
    </div>
  );
}

function buildEvacuationPrompt(threat: ThreatPayload, request: ReplayRequest) {
  return [
    "Run the FireGuard evacuation workflow for this replay threat.",
    `Hotspot: lat ${threat.hotspot.lat}, lon ${threat.hotspot.lon}, FRP ${threat.hotspot.frp}, confidence ${threat.hotspot.confidence ?? "unknown"}, acquired ${threat.hotspot.acquired_at}, source ${threat.hotspot.source}.`,
    `Affected zone: ${threat.zone.name}, population ${threat.zone.population ?? "unknown"}, homes ${threat.zone.homes ?? "unknown"}, centroid lat ${threat.zone.latitude ?? "unknown"}, centroid lon ${threat.zone.longitude ?? "unknown"}, hotspot distance ${threat.zone.distance_km ?? "unknown"} km.`,
    `Replay window: ${request.start_date} through ${request.end_date}.`,
    "Scan affected zones, shelters, road events, and fire detections; evaluate routes to open shelters; then produce the evacuation brief and recommended action.",
  ].join("\n");
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
