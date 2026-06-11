import { useState, type ReactNode } from "react";
import type { BcwsContext, ReplayRequest, Stats } from "../types";
import type { MapAnnotation } from "../intelligence/types";
import { LOGOS } from "../intelligence/logos";
import { sources as allSources } from "./state";

type Props = {
  request: ReplayRequest;
  onRequestChange: (value: ReplayRequest) => void;
  context: BcwsContext;
  stats: Stats | null;
  busy: boolean;
  annotation?: MapAnnotation | null;
};

const SRC_META: Record<string, { short: string; color: string }> = {
  VIIRS_NOAA20_NRT: { short: "VIIRS N20",  color: "#4ab4f5" },
  VIIRS_NOAA20_SP:  { short: "VIIRS N20",  color: "#4ab4f5" },
  VIIRS_NOAA21_NRT: { short: "VIIRS N21",  color: "#62c4f8" },
  VIIRS_NOAA21_SP:  { short: "VIIRS N21",  color: "#62c4f8" },
  VIIRS_SNPP_NRT:   { short: "VIIRS SNPP", color: "#2898d8" },
  VIIRS_SNPP_SP:    { short: "VIIRS SNPP", color: "#2898d8" },
  MODIS_NRT:        { short: "MODIS",      color: "#f0a840" },
  MODIS_SP:         { short: "MODIS",      color: "#f0a840" },
};

const SPEED_OPTIONS = [
  { label: "1 min/s", value: 60 },
  { label: "1 hr/s", value: 3600 },
  { label: "6 hr/s", value: 21600 },
  { label: "12 hr/s", value: 43200 },
  { label: "24 hr/s", value: 86400 },
];

const ANN_ROUTE_COLORS: Record<string, string> = {
  safe:      "#10b981",
  blocked:   "#ef4444",
  alternate: "#f97316",
};

function Section({ title, children, defaultOpen = true }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="sbSection">
      <button className="sbSectionHeader" type="button" onClick={() => setOpen((v) => !v)}>
        <span className={`sbTriangle${open ? " sbTriangle--open" : ""}`} />
        {title}
      </button>
      {open && <div className="sbSectionBody">{children}</div>}
    </div>
  );
}

function ContextRow({ color, label, count }: { color: string; label: string; count: number }) {
  return (
    <div className="sbRow">
      <span className="sbSquare" style={{ background: count > 0 ? color : "#374151" }} />
      <span className="sbRowLabel">{label}</span>
      <span className="sbRowCount">{count.toLocaleString()}</span>
    </div>
  );
}

export function Sidebar({ request, onRequestChange, context, stats, busy, annotation = null }: Props) {
  function patch(next: Partial<ReplayRequest>) {
    onRequestChange({ ...request, ...next });
  }

  function toggleSource(source: string) {
    const next = request.sources.includes(source)
      ? request.sources.filter((item) => item !== source)
      : [...request.sources, source];
    patch({ sources: next });
  }

  const sourceCounts = new Map((stats?.sources ?? []).map((s) => [s.source, s.count]));

  return (
    <aside className="sidebar">
      <Section title="CONTEXT">
        <ContextRow color="#e5484d" label="Incidents"   count={context.incidents.length} />
        <ContextRow color="#f59e0b" label="Perimeters"  count={context.perimeters.length} />
        <ContextRow color="#a855f7" label="Evac zones"  count={context.evacuation_zones.length} />
        <ContextRow color="#e5484d" label="Evac orders" count={context.evacuation_records.length} />
        <ContextRow color="#22c55e" label="Shelters"    count={context.ess_facilities.length} />
        <ContextRow color="#eab308" label="Road events" count={context.road_events.length} />
        <ContextRow color="#3b82f6" label="Weather"     count={context.weather_snapshot ? 1 : 0} />
      </Section>

      <Section title="SOURCES">
        {allSources.map((source) => {
          const meta = SRC_META[source] ?? { short: source.slice(0, 9), color: "#5a7a9a" };
          const active = request.sources.includes(source);
          const count = sourceCounts.get(source);
          return (
            <button
              key={source}
              type="button"
              className="sbRow sbRow--toggle"
              onClick={() => toggleSource(source)}
              disabled={busy}
              title={source}
            >
              <span
                className="sbSquare sbSquare--check"
                style={active ? { background: meta.color } : undefined}
              />
              <img src={LOGOS.nasa.src} alt="" width={10} height={10} className="sbLogo" />
              <span className="sbRowLabel" style={{ color: active ? "#c8d6e0" : "#4b5563" }}>{meta.short}</span>
              {count != null && <span className="sbRowCount">{formatK(count)}</span>}
            </button>
          );
        })}
        {stats && (
          <div className="sbMetaRow">
            {formatK(stats.firms_count)} indexed · {formatSpan(stats.min_acquired_at ?? null, stats.max_acquired_at ?? null)}
          </div>
        )}
      </Section>

      <Section title="REPLAY">
        <label className="sbField">
          <span className="sbFieldLabel">START</span>
          <input
            className="sbInput"
            type="date"
            value={request.start_date}
            disabled={busy}
            onChange={(e) => patch({ start_date: e.currentTarget.value })}
          />
        </label>
        <label className="sbField">
          <span className="sbFieldLabel">END</span>
          <input
            className="sbInput"
            type="date"
            value={request.end_date}
            disabled={busy}
            onChange={(e) => patch({ end_date: e.currentTarget.value })}
          />
        </label>
        <label className="sbField">
          <span className="sbFieldLabel">SPEED</span>
          <select
            className="sbInput"
            value={request.speed}
            disabled={busy}
            onChange={(e) => patch({ speed: Number(e.currentTarget.value) })}
          >
            {SPEED_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </label>
        <div className="sbMetaRow">
          {request.latitude.toFixed(2)}, {request.longitude.toFixed(2)} · r {request.radius_km} km
        </div>
      </Section>

      <div className="sbFill" />

      <Section title="LEGEND">
        <div className="sbLegend">
          <span><i className="sbLegendDot" style={{ background: "#f15b43" }} />FIRMS hotspot</span>
          <span><i className="sbLegendDot" style={{ background: "#e5484d" }} />BCWS incident</span>
          <span><i className="sbLegendLine" style={{ background: "#ffd27f" }} />Fire perimeter</span>
          <span><i className="sbLegendLine" style={{ background: "#e7a8ff" }} />Evac zone</span>
          <span><i className="sbLegendDot" style={{ background: "#43d9ad" }} />ESS shelter</span>
          <span><i className="sbLegendDot" style={{ background: "#f6f08d" }} />Road event</span>
          <span><i className="sbLegendLine" style={{ background: "#6bbcff" }} />Wind vector</span>
          {annotation !== null && annotation.routes.map((r, i) => (
            <span key={i}>
              <i className="sbLegendLine" style={{ background: ANN_ROUTE_COLORS[r.status] ?? "#6366f1" }} />
              {r.label}
            </span>
          ))}
        </div>
      </Section>
    </aside>
  );
}

function formatK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatSpan(start: string | null, end: string | null): string {
  if (!start || !end) return "";
  return `${start.slice(5, 10)} — ${end.slice(5, 10)}`;
}
