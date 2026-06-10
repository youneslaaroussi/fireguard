import { Tag } from "@blueprintjs/core";
import type { Stats } from "../types";

type Props = {
  value: Stats | null;
};

export function StatsStrip({ value }: Props) {
  if (!value) {
    return (
      <section className="statsStrip">
        <Stat label="FIRMS corpus" value="Loading" />
      </section>
    );
  }

  return (
    <section className="statsStrip">
      <Stat label="FIRMS corpus" value={formatNumber(value.firms_count)} />
      <Stat label="Date span" value={formatSpan(value.min_acquired_at, value.max_acquired_at)} />
      <Stat label="BCWS incidents" value={formatNumber(value.bcws_incident_count)} />
      <Stat label="BCWS perimeters" value={formatNumber(value.bcws_perimeter_count)} />
      <div className="sourceStats">
        {value.sources.map((source) => (
          <Tag key={source.source} minimal>
            {source.source}: {formatNumber(source.count)}
          </Tag>
        ))}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="statItem">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatNumber(value: number) {
  return value.toLocaleString();
}

function formatSpan(start?: string | null, end?: string | null) {
  if (!start || !end) return "n/a";
  return `${formatDate(start)} - ${formatDate(end)}`;
}

function formatDate(value: string) {
  return value.slice(0, 10);
}
