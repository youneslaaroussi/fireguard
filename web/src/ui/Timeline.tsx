type Props = {
  start: string;
  end: string;
  progress: number;
  status: string;
  busy: boolean;
  paused: boolean;
  onReplay: () => void;
  onTogglePause: () => void;
};

export function Timeline({ start, end, progress, status, busy, paused, onReplay, onTogglePause }: Props) {
  const ticks = makeTicks(start, end);
  const pct = Math.max(0, Math.min(1, progress));
  const running = busy && progress < 1;

  return (
    <div className="tlBar">
      {/* Track area */}
      <div className="tlTrackArea">
        {/* Tick labels — rendered above track */}
        <div className="tlTickRow">
          {ticks.map(({ label, pct: tp }, i) => (
            <div
              key={i}
              className={`tlTick${i === 0 ? " tlTick--first" : ""}${i === ticks.length - 1 ? " tlTick--last" : ""}`}
              style={{ left: `${tp * 100}%` }}
            >
              <span className="tlTickLabel">{label}</span>
            </div>
          ))}
        </div>

        {/* Track */}
        <div className="tlTrack">
          {/* Elapsed fill */}
          <div className="tlElapsed" style={{ width: `${pct * 100}%` }} />

          {/* Tick marks on track */}
          {ticks.map(({ pct: tp }, i) => (
            <div key={i} className="tlTickMark" style={{ left: `${tp * 100}%` }} />
          ))}

          {/* Playhead */}
          <div className="tlPlayhead" style={{ left: `${pct * 100}%` }}>
            <div className="tlPlayheadNeedle" />
            <div className="tlPlayheadDiamond" />
          </div>
        </div>

        {/* Status label */}
        <div className="tlStatus">{paused ? "⏸ PAUSED" : status}</div>
      </div>

      {/* Pause button — only while replay is in progress */}
      {running && (
        <button
          className={`tlPauseBtn${paused ? " tlPauseBtn--paused" : ""}`}
          onClick={onTogglePause}
          title={paused ? "Resume" : "Pause"}
        >
          {paused ? (
            <>
              <svg width="10" height="12" viewBox="0 0 10 12" fill="none" aria-hidden="true">
                <path d="M1 1l8 5-8 5V1z" fill="currentColor"/>
              </svg>
              <span>RESUME</span>
            </>
          ) : (
            <>
              <svg width="10" height="12" viewBox="0 0 10 12" fill="none" aria-hidden="true">
                <rect x="1" y="1" width="3" height="10" rx="1" fill="currentColor"/>
                <rect x="6" y="1" width="3" height="10" rx="1" fill="currentColor"/>
              </svg>
              <span>PAUSE</span>
            </>
          )}
        </button>
      )}

      {/* Replay button */}
      <button
        className={`tlReplayBtn${busy ? " tlReplayBtn--busy" : ""}`}
        onClick={onReplay}
        disabled={busy}
      >
        {busy ? (
          <>
            <span className="tlBusyDots">▪▪▪</span>
            <span>ACQUIRING</span>
          </>
        ) : (
          <>
            <svg width="10" height="12" viewBox="0 0 10 12" fill="none" aria-hidden="true">
              <path d="M1 1l8 5-8 5V1z" fill="currentColor"/>
            </svg>
            <span>REPLAY</span>
          </>
        )}
      </button>
    </div>
  );
}

type Tick = { label: string; pct: number };

function makeTicks(start: string, end: string): Tick[] {
  const a = new Date(start);
  const b = new Date(end);
  if (Number.isNaN(a.valueOf()) || Number.isNaN(b.valueOf())) return [];
  const span = b.getTime() - a.getTime();
  const days = Math.ceil(span / 86_400_000);
  // One tick per day, capped at 9
  const count = Math.min(days + 1, 9);
  return Array.from({ length: count }, (_, i) => {
    const p = count <= 1 ? 0 : i / (count - 1);
    const d = new Date(a.getTime() + span * p);
    return { label: d.toISOString().slice(5, 10), pct: p };
  });
}
