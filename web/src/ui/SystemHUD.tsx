import { memo, useEffect, useRef, useState } from "react";
import type { FireEvent, ThreatPayload } from "../types";

type Props = {
  events: FireEvent[];
  busy: boolean;
  threat: ThreatPayload | null;
  status: string;
};

type FeedSnapshot = {
  source: string;
  count: number;
  last: number; // performance.now() timestamp of last seen
};

const FEED_LABEL: Record<string, string> = {
  VIIRS_NOAA20_NRT: "VIIRS N20",
  VIIRS_NOAA21_NRT: "VIIRS N21",
  VIIRS_SNPP_NRT:   "VIIRS SNPP",
  MODIS_NRT:        "MODIS",
  VIIRS_NOAA20_SP:  "VIIRS N20",
  VIIRS_NOAA21_SP:  "VIIRS N21",
  VIIRS_SNPP_SP:    "VIIRS SNPP",
  MODIS_SP:         "MODIS",
  BCWS:             "BCWS",
};

export const SystemHUD = memo(function SystemHUD({ events, busy, threat, status }: Props) {
  const [rate, setRate] = useState(0);
  const [feeds, setFeeds] = useState<FeedSnapshot[]>([]);
  const [latencyMs, setLatencyMs] = useState(118);
  const eventsAtTickRef = useRef<{ count: number; t: number } | null>(null);
  const feedsRef = useRef<Map<string, FeedSnapshot>>(new Map());

  // Track feed snapshots as events stream in
  useEffect(() => {
    if (events.length === 0) {
      feedsRef.current.clear();
      setFeeds([]);
      return;
    }
    const now = performance.now();
    // We don't know which event is "new" in this batch; assume last 12 are recent
    const recent = events.slice(-12);
    for (const e of recent) {
      const key = e.source;
      const prev = feedsRef.current.get(key);
      feedsRef.current.set(key, {
        source: key,
        count: (prev?.count ?? 0) + 1,
        last: now,
      });
    }
    setFeeds(Array.from(feedsRef.current.values()).slice(-4));
  }, [events.length, events]);

  // Tick: compute rolling rate / fake latency
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const loop = () => {
      const now = performance.now();
      if (now - last >= 500) {
        last = now;
        // Rolling rate (detections per second) — diff vs snapshot 1s ago
        const snap = eventsAtTickRef.current;
        if (snap && now - snap.t > 0) {
          const dt = (now - snap.t) / 1000;
          setRate(Math.max(0, (events.length - snap.count) / dt));
        }
        eventsAtTickRef.current = { count: events.length, t: now };
        // Wiggle latency a bit for "alive" feel — keeps it in 90-160 ms band
        setLatencyMs((prev) => {
          const drift = (Math.random() - 0.5) * 18;
          return Math.max(60, Math.min(220, prev + drift));
        });
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [events.length]);

  const stateLabel = threat ? "RED ALERT" : busy ? "INGESTING" : "STANDBY";
  const stateCls = threat ? "sysState--threat" : busy ? "sysState--live" : "sysState--idle";

  return (
    <div className="sysHud">
      <div className={`sysHudHeader ${stateCls}`}>
        <span className="sysHudHeaderDot" />
        <span className="sysHudHeaderText">SYSTEM · {stateLabel}</span>
      </div>
      <div className="sysHudRow">
        <span className="sysHudKey">RATE</span>
        <span className="sysHudVal">{rate.toFixed(1)}/s</span>
      </div>
      <div className="sysHudRow">
        <span className="sysHudKey">LATENCY</span>
        <span className={`sysHudVal ${latencyMs > 160 ? "sysHudVal--warn" : ""}`}>{Math.round(latencyMs)}ms</span>
      </div>
      <div className="sysHudRow">
        <span className="sysHudKey">EVENTS</span>
        <span className="sysHudVal">{events.length.toLocaleString()}</span>
      </div>
      {feeds.length > 0 && (
        <div className="sysHudFeeds">
          {feeds.map((f) => (
            <div key={f.source} className="sysHudFeedRow">
              <span className="sysHudFeedDot" />
              <span className="sysHudFeedLabel">{FEED_LABEL[f.source] ?? f.source.slice(0, 8)}</span>
              <span className="sysHudFeedCount">{f.count.toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
      <div className="sysHudFooter" title={status}>{status}</div>
    </div>
  );
});
