import type { Stats } from "../types";

type Props = { value: Stats | null };

// Source display config: short label + accent color
const SRC: Record<string, { short: string; color: string }> = {
  VIIRS_NOAA20_NRT: { short: "V20",  color: "#4ab4f5" },
  VIIRS_NOAA20_SP:  { short: "V20S", color: "#3aaae8" },
  VIIRS_NOAA21_NRT: { short: "V21",  color: "#62c4f8" },
  VIIRS_NOAA21_SP:  { short: "V21S", color: "#52b8f2" },
  VIIRS_SNPP_NRT:   { short: "SNPP", color: "#2898d8" },
  VIIRS_SNPP_SP:    { short: "SNPS", color: "#2288cc" },
  MODIS_NRT:        { short: "MOD",  color: "#f0a840" },
};

function SatIcon({ color }: { color: string }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
      <rect x="4" y="0" width="2" height="4" fill={color} opacity="0.9"/>
      <rect x="0" y="4" width="10" height="2" fill={color} opacity="0.9"/>
      <rect x="4" y="6" width="2" height="4" fill={color} opacity="0.9"/>
      <circle cx="5" cy="5" r="1.5" fill={color}/>
    </svg>
  );
}

function ModisIcon({ color }: { color: string }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
      <circle cx="5" cy="5" r="4" stroke={color} strokeWidth="1.2" opacity="0.85"/>
      <circle cx="5" cy="5" r="1.8" fill={color}/>
      <line x1="5" y1="1" x2="5" y2="9" stroke={color} strokeWidth="0.8" opacity="0.5"/>
      <line x1="1" y1="5" x2="9" y2="5" stroke={color} strokeWidth="0.8" opacity="0.5"/>
    </svg>
  );
}

function FireIcon() {
  return (
    <svg width="10" height="12" viewBox="0 0 10 12" fill="none" aria-hidden="true">
      <path d="M5 0C4.4 2.4 2.5 3.8 2.5 6a2.5 2.5 0 0 0 5 0c0-1.3-.8-2.4-1.4-3.1-.2 1-.7 1.6-1.1 1.9C4.8 3.8 4.6 2.2 5 0z" fill="#ff6b4a"/>
      <ellipse cx="5" cy="6.2" rx="0.9" ry="1" fill="#ffd0b0" opacity="0.7"/>
    </svg>
  );
}

function BcwsIcon() {
  return (
    <svg width="10" height="12" viewBox="0 0 10 12" fill="none" aria-hidden="true">
      <path d="M5 1L1 3v3c0 2.2 1.7 4.3 4 5 2.3-.7 4-2.8 4-5V3L5 1z" stroke="#f0c060" strokeWidth="1" fill="none" opacity="0.8"/>
      <path d="M3.5 6l1 1 2-2" stroke="#f0c060" strokeWidth="1" strokeLinecap="round" opacity="0.9"/>
    </svg>
  );
}

export function StatsStrip({ value }: Props) {
  if (!value) {
    return (
      <div className="statsRow">
        <span className="statPill statPill--dim">Loading corpus…</span>
      </div>
    );
  }

  const isModis = (src: string) => src.includes("MODIS");

  return (
    <div className="statsRow">
      {/* FIRMS detections */}
      <span className="statPill">
        <FireIcon />
        <span className="statPillVal">{formatK(value.firms_count)}</span>
        <span className="statPillLabel">DETECTIONS</span>
      </span>

      {/* Time span */}
      {value.min_acquired_at && value.max_acquired_at && (
        <span className="statPill">
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
            <circle cx="5" cy="5" r="4" stroke="#3a6888" strokeWidth="1"/>
            <line x1="5" y1="2" x2="5" y2="5.5" stroke="#3a6888" strokeWidth="1" strokeLinecap="round"/>
            <line x1="5" y1="5.5" x2="7" y2="7" stroke="#3a6888" strokeWidth="1" strokeLinecap="round"/>
          </svg>
          <span className="statPillVal">{formatSpan(value.min_acquired_at, value.max_acquired_at)}</span>
        </span>
      )}

      {/* BCWS incidents */}
      {value.bcws_incident_count > 0 && (
        <span className="statPill">
          <BcwsIcon />
          <span className="statPillVal">{value.bcws_incident_count.toLocaleString()}</span>
          <span className="statPillLabel">INCIDENTS</span>
        </span>
      )}

      {/* Perimeters */}
      {value.bcws_perimeter_count > 0 && (
        <span className="statPill">
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
            <polygon points="5,1 9,4 7.5,9 2.5,9 1,4" stroke="#5a7a50" strokeWidth="1" fill="none" opacity="0.85"/>
          </svg>
          <span className="statPillVal">{value.bcws_perimeter_count.toLocaleString()}</span>
          <span className="statPillLabel">PERIMETERS</span>
        </span>
      )}

      {/* Source breakdown */}
      <div className="srcDivider" />
      {value.sources.map((src) => {
        const meta = SRC[src.source] ?? { short: src.source.slice(0, 4).toUpperCase(), color: "#5a7a9a" };
        return (
          <span key={src.source} className="srcPill" title={src.source}>
            {isModis(src.source)
              ? <ModisIcon color={meta.color} />
              : <SatIcon color={meta.color} />}
            <span className="srcPillLabel" style={{ color: meta.color }}>{meta.short}</span>
            <span className="srcPillCount">{formatK(src.count)}</span>
          </span>
        );
      })}
    </div>
  );
}

function formatK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

function formatSpan(start: string, end: string): string {
  const a = new Date(start);
  const b = new Date(end);
  const days = Math.round((b.getTime() - a.getTime()) / 86_400_000);
  if (days < 2) return `${start.slice(5, 10)}`;
  return `${start.slice(5, 10)} — ${end.slice(5, 10)}`;
}
