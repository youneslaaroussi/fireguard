type Props = {
  start: string;
  end: string;
  progress: number;
};

export function Timeline({ start, end, progress }: Props) {
  const ticks = makeTicks(start, end);
  const left = `${Math.max(0, Math.min(1, progress)) * 100}%`;
  return (
    <section className="timeline">
      <div className="tickRail">
        <div className="playhead" style={{ left }} />
        {ticks.map((tick) => (
          <div className="tick" key={tick}>{tick}</div>
        ))}
      </div>
      <div className="liveEdge">NOW</div>
    </section>
  );
}

function makeTicks(start: string, end: string) {
  const a = new Date(start);
  const b = new Date(end);
  if (Number.isNaN(a.valueOf()) || Number.isNaN(b.valueOf())) return [];
  return Array.from({ length: 8 }, (_, i) => {
    const d = new Date(a.getTime() + ((b.getTime() - a.getTime()) * i) / 7);
    return d.toISOString().slice(5, 10);
  });
}
