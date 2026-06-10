import { useEffect, useState } from "react";
import { Alignment, Button, ButtonGroup, Callout, Navbar, Tag } from "@blueprintjs/core";
import { getConfig, getStats, replay } from "../api";
import type { BcwsContext, FireEvent, ReplayRequest, Stats } from "../types";
import { AgenticIntelligenceApp } from "../intelligence/App";
import { Controls } from "./Controls";
import { EventStream } from "./EventStream";
import { MapPanel } from "./MapPanel";
import { StatsStrip } from "./StatsStrip";
import { Timeline } from "./Timeline";
import { dateString, sources } from "./state";

const initial: ReplayRequest = {
  latitude: 49.2827,
  longitude: -123.1207,
  radius_km: 250,
  start_date: dateString(-7),
  end_date: dateString(0),
  sources,
  speed: 3600,
  limit: 5000
};

const emptyContext: BcwsContext = {
  incidents: [],
  perimeters: []
};

export function App() {
  const [view, setView] = useState<"replay" | "intelligence">("intelligence");
  const [request, setRequest] = useState<ReplayRequest>(initial);
  const [events, setEvents] = useState<FireEvent[]>([]);
  const [context, setContext] = useState<BcwsContext>(emptyContext);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mapboxToken, setMapboxToken] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [replayProgress, setReplayProgress] = useState(0);
  const [status, setStatus] = useState("Idle");
  const [runId, setRunId] = useState(0);

  useEffect(() => {
    if (view !== "replay") return;
    getConfig().then((config) => setMapboxToken(config.mapbox_access_token)).catch((err) => setError(String(err)));
    getStats().then(setStats).catch((err) => setError(String(err)));
  }, [view]);

  async function startReplay() {
    setBusy(true);
    setError(null);
    setEvents([]);
    setContext(emptyContext);
    setReplayProgress(0);
    setStatus("Starting");
    setRunId((value) => value + 1);
    try {
      await replay(request, (message) => {
        if (message.type === "started") {
          setStatus(`Preparing ${message.area}`);
        } else if (message.type === "context") {
          setContext({ incidents: message.incidents, perimeters: message.perimeters });
          setStatus(
            `${message.cached ? "Cached" : "Loaded"} BCWS: ${message.incidents.length.toLocaleString()} incidents, ${message.perimeters.length.toLocaleString()} perimeters`
          );
        } else if (message.type === "chunk_start") {
          setStatus(`${message.cached ? "Reading cache" : "Collecting"} ${message.source} ${message.start_date} (${message.days}d)`);
        } else if (message.type === "chunk") {
          setStatus(`${message.cached ? "Cached" : "Collected"} ${message.source} ${message.start_date}: ${message.indexed.toLocaleString()}`);
        } else if (message.type === "events") {
          setEvents((current) => [...current, ...message.events]);
          setStatus(`Replaying ${message.source} ${message.start_date}: ${message.events.length.toLocaleString()} events`);
        } else if (message.type === "done") {
          setStatus(`Done: ${message.events.toLocaleString()} events`);
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
    <div className="shell">
      <Navbar className="topbar">
        <Navbar.Group align={Alignment.LEFT}>
          <Navbar.Heading>FireGuard</Navbar.Heading>
          <Navbar.Divider />
          <Tag intent="primary">FIRMS</Tag>
          <Tag intent="success">Elastic</Tag>
          <Tag intent="warning">BCWS</Tag>
        </Navbar.Group>
        <Navbar.Group align={Alignment.RIGHT}>
          <ButtonGroup>
            <Button active={view === "replay"} text="Replay" onClick={() => setView("replay")} />
            <Button active={view === "intelligence"} text="Intelligence" onClick={() => setView("intelligence")} />
          </ButtonGroup>
          {view === "replay" && <Button icon="play" text="Replay" intent="success" loading={busy} onClick={startReplay} />}
        </Navbar.Group>
      </Navbar>

      {view === "replay" ? (
        <>
          <Timeline start={request.start_date} end={request.end_date} progress={replayProgress} />

          <main className="workspace">
            <Controls value={request} onChange={setRequest} />
            <section className="mainPane">
              {error && <Callout intent="danger">{error}</Callout>}
              <StatsStrip value={stats} />
              <Callout intent="primary">{status}</Callout>
              <MapPanel token={mapboxToken} events={events} context={context} />
              <EventStream events={events} runId={runId} active={busy} onProgress={setReplayProgress} />
            </section>
          </main>
        </>
      ) : (
        <AgenticIntelligenceApp />
      )}
    </div>
  );
}
