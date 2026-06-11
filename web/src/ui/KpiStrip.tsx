import { memo, useEffect, useRef, useState } from "react";
import type { BcwsContext, FireEvent, ThreatPayload } from "../types";

type Props = {
  events: FireEvent[];
  context: BcwsContext;
  threat: ThreatPayload | null;
  busy: boolean;
};

type Tile = {
  key: string;
  label: string;
  value: number;
  format?: "int" | "k";
  flavor?: "normal" | "warn" | "critical" | "ok";
  unit?: string;
};

function fmt(n: number, mode: "int" | "k" | undefined): string {
  if (mode === "k") {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  }
  return n.toLocaleString();
}

const Counter = memo(function Counter({ value, format }: { value: number; format?: "int" | "k" }) {
  const [displayed, setDisplayed] = useState(value);
  const prev = useRef(value);

  useEffect(() => {
    if (prev.current === value) return;
    const start = prev.current;
    const end = value;
    const duration = Math.min(700, 120 + Math.abs(end - start) * 2);
    const t0 = performance.now();
    let raf = 0;
    function step(now: number) {
      const t = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplayed(Math.round(start + (end - start) * eased));
      if (t < 1) raf = requestAnimationFrame(step);
      else prev.current = end;
    }
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return <span className="kpiValueNum">{fmt(displayed, format)}</span>;
});

function KpiTile({ tile, pulse }: { tile: Tile; pulse: boolean }) {
  return (
    <div className={`kpiTile kpiTile--${tile.flavor ?? "normal"}${pulse ? " kpiTile--pulse" : ""}`}>
      <div className="kpiTileLabel">{tile.label}</div>
      <div className="kpiTileValue">
        <Counter value={tile.value} format={tile.format} />
        {tile.unit && <span className="kpiTileUnit">{tile.unit}</span>}
      </div>
    </div>
  );
}

export function KpiStrip({ events, context, threat, busy }: Props) {
  const critical = events.reduce(
    (n, e) => n + ((e.threat_score ?? 0) >= 75 ? 1 : 0),
    0,
  );
  const sheltersOpen = context.ess_facilities.reduce(
    (n, s) => n + ((s.status ?? "").toLowerCase() === "open" ? 1 : 0),
    0,
  );
  const sheltersTotal = context.ess_facilities.length;
  const roadClosures = context.road_events.reduce(
    (n, r) => n + ((r.severity ?? "").toLowerCase().includes("closure") || (r.event_type ?? "").toLowerCase().includes("closure") ? 1 : 0),
    0,
  );
  const evacOrders = context.evacuation_records.reduce(
    (n, r) => n + ((r.status ?? "").toLowerCase() === "order" ? 1 : 0),
    0,
  );
  const evacAlerts = context.evacuation_records.reduce(
    (n, r) => n + ((r.status ?? "").toLowerCase() === "alert" ? 1 : 0),
    0,
  );
  const populationAtRisk = context.evacuation_records.reduce(
    (n, r) => n + (r.population ?? 0),
    0,
  );
  const incidentsActive = context.incidents.reduce(
    (n, i) => n + ((i.fire_status ?? "").toLowerCase().includes("out of control") || (i.fire_status ?? "").toLowerCase().includes("being held") ? 1 : 0),
    0,
  );
  const maxFrp = events.reduce((m, e) => Math.max(m, e.frp ?? 0), 0);

  const tiles: Tile[] = [
    { key: "detections", label: "DETECTIONS", value: events.length, format: "k", flavor: events.length > 0 ? "normal" : "normal" },
    { key: "critical", label: "CRITICAL", value: critical, flavor: critical > 0 ? "critical" : "normal" },
    { key: "incidents", label: "ACTIVE FIRES", value: incidentsActive, flavor: incidentsActive > 0 ? "warn" : "normal" },
    { key: "maxfrp", label: "PEAK FRP", value: Math.round(maxFrp), flavor: maxFrp >= 50 ? "critical" : maxFrp >= 20 ? "warn" : "normal", unit: "MW" },
    { key: "orders", label: "EVAC ORDERS", value: evacOrders, flavor: evacOrders > 0 ? "critical" : "normal" },
    { key: "alerts", label: "EVAC ALERTS", value: evacAlerts, flavor: evacAlerts > 0 ? "warn" : "normal" },
    { key: "popatrisk", label: "POP AT RISK", value: populationAtRisk, format: "k", flavor: populationAtRisk > 0 ? "warn" : "normal" },
    { key: "shelters", label: "SHELTERS", value: sheltersOpen, flavor: sheltersOpen === 0 && sheltersTotal > 0 ? "critical" : sheltersOpen > 0 ? "ok" : "normal", unit: sheltersTotal > 0 ? `/ ${sheltersTotal}` : undefined },
    { key: "closures", label: "ROAD CLOSED", value: roadClosures, flavor: roadClosures > 0 ? "warn" : "normal" },
  ];

  // Pulse tile briefly when its value changes
  const prevValues = useRef<Record<string, number>>({});
  const [pulsedKeys, setPulsedKeys] = useState<Set<string>>(new Set());
  useEffect(() => {
    const changed = new Set<string>();
    for (const t of tiles) {
      const prev = prevValues.current[t.key];
      if (prev !== undefined && prev !== t.value) changed.add(t.key);
      prevValues.current[t.key] = t.value;
    }
    if (changed.size === 0) return;
    setPulsedKeys((p) => {
      const next = new Set(p);
      for (const k of changed) next.add(k);
      return next;
    });
    const id = window.setTimeout(() => {
      setPulsedKeys((p) => {
        const next = new Set(p);
        for (const k of changed) next.delete(k);
        return next;
      });
    }, 700);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.length, context, threat]);

  return (
    <div className={`kpiStrip${busy ? " kpiStrip--live" : ""}${threat ? " kpiStrip--threat" : ""}`}>
      <span className="kpiStripBadge">
        <span className="kpiStripBadgeDot" />
        <span>{busy ? "LIVE" : "STANDBY"}</span>
      </span>
      {tiles.map((tile) => (
        <KpiTile key={tile.key} tile={tile} pulse={pulsedKeys.has(tile.key)} />
      ))}
    </div>
  );
}
