import { memo, useEffect, useMemo, useRef } from "react";
import type { FireEvent } from "../types";

type Props = {
  events: FireEvent[];
  busy?: boolean;
};

const MAX_ROWS = 250;
const SPARK_BUCKETS = 36;

export function EventStream({ events, busy = false }: Props) {
  const feed = events.slice(-MAX_ROWS);
  const first = events[0]?.acquired_at;
  const latest = events[events.length - 1]?.acquired_at;
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);

  // Bucket events by acquired_at into a normalized sparkline of detection density
  const sparkline = useMemo(() => buildSparkline(events), [events]);

  // Track whether the user has scrolled away from the live tail
  function handleScroll() {
    const el = bodyRef.current;
    if (!el) return;
    pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  useEffect(() => {
    const el = bodyRef.current;
    if (el && pinnedToBottom.current) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <div className="eventTable">
      <div className="etHead">
        <span className="etcTime">TIME</span>
        <span className="etcSrc">SRC</span>
        <span className="etcCoord">COORD</span>
        <span className="etcFrp">FRP</span>
        <span className="etcConf">CONF</span>
        <span className="etcScore">RISK</span>
        <span className="etcInc">INCIDENT</span>
      </div>
      <div className="etBody" ref={bodyRef} onScroll={handleScroll}>
        {feed.length === 0 && (
          <div className="etEmpty">
            <span className="etEmptyTitle">{busy ? "ACQUIRING" : "NO DETECTIONS"}</span>
            <span className="etEmptyHint">
              {busy
                ? "Indexing satellite detection chunks — events stream as the replay clock advances"
                : "Press REPLAY to stream the acquisition window"}
            </span>
          </div>
        )}
        {feed.map((event) => (
          <EventRow
            key={`${event.source}-${event.acquired_at}-${event.latitude}-${event.longitude}`}
            event={event}
          />
        ))}
      </div>
      <div className="etCounter">
        {events.length.toLocaleString()} DETECTIONS
        {first && latest && (
          <>
            {" "}· {formatStamp(first)} → {formatStamp(latest)}
          </>
        )}
        {events.length > MAX_ROWS && <> · showing last {MAX_ROWS}</>}
        {sparkline.length > 0 && (
          <span className="etSparkline" title="Detection density over the replay window">
            {sparkline.map((v, i) => (
              <span
                key={i}
                className={`etSpark${v >= 0.66 ? " etSpark--hot" : v >= 0.33 ? " etSpark--mid" : ""}`}
                style={{ height: `${Math.max(2, v * 14)}px` }}
              />
            ))}
          </span>
        )}
      </div>
    </div>
  );
}

function buildSparkline(events: FireEvent[]): number[] {
  if (events.length < 2) return [];
  const stamps: number[] = [];
  for (const e of events) {
    const t = Date.parse(e.acquired_at);
    if (Number.isFinite(t)) stamps.push(t);
  }
  if (stamps.length < 2) return [];
  stamps.sort((a, b) => a - b);
  const minT = stamps[0];
  const maxT = stamps[stamps.length - 1];
  const span = maxT - minT;
  if (span <= 0) return [];
  const buckets = new Array(SPARK_BUCKETS).fill(0);
  for (const t of stamps) {
    const idx = Math.min(SPARK_BUCKETS - 1, Math.floor(((t - minT) / span) * SPARK_BUCKETS));
    buckets[idx] += 1;
  }
  const max = Math.max(...buckets);
  if (max === 0) return [];
  return buckets.map((b) => b / max);
}

const EventRow = memo(function EventRow({ event }: { event: FireEvent }) {
  const score = event.threat_score ?? 0;
  const hot = event.frp != null && event.frp >= 50;
  const critical = score >= 75;
  return (
    <div className={`etRow${hot ? " etRow--hot" : ""}${critical ? " etRow--critical" : ""}`}>
      <span className="etcTime">{event.acquired_at.slice(5, 16).replace("T", " ")}</span>
      <span className="etcSrc">{abbrevSrc(event.source)}</span>
      <span className="etcCoord">{event.latitude.toFixed(3)}, {event.longitude.toFixed(3)}</span>
      <span className="etcFrp">{event.frp != null ? event.frp.toFixed(1) : ""}</span>
      <span className="etcConf">{event.confidence ?? ""}</span>
      <span className={`etcScore${score >= 75 ? " etcScore--critical" : score >= 50 ? " etcScore--high" : score >= 25 ? " etcScore--moderate" : ""}`}>
        {score > 0 ? score : ""}
      </span>
      <span className="etcInc">{event.bcws?.incident?.incident_name ?? ""}</span>
    </div>
  );
});

function abbrevSrc(s: string) {
  return s
    .replace("VIIRS_NOAA20_SP", "V20S")
    .replace("VIIRS_NOAA21_SP", "V21S")
    .replace("VIIRS_SNPP_SP", "VNPS")
    .replace("VIIRS_NOAA20_NRT", "V20")
    .replace("VIIRS_NOAA21_NRT", "V21")
    .replace("VIIRS_SNPP_NRT", "VNP")
    .replace("MODIS_SP", "MODS")
    .replace("MODIS_NRT", "MOD");
}

function formatStamp(value: string) {
  return value.slice(5, 16).replace("T", " ");
}
