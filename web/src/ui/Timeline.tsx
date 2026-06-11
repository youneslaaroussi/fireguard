import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const SPEED_STEPS = [
  { label: "1m/s",  value: 60 },
  { label: "1h/s",  value: 3600 },
  { label: "6h/s",  value: 21600 },
  { label: "12h/s", value: 43200 },
  { label: "24h/s", value: 86400 },
];

type Props = {
  start: string;
  end: string;
  progress: number;
  status: string;
  busy: boolean;
  paused: boolean;
  speed: number;
  onSpeedChange: (speed: number) => void;
  onReplay: () => void;
  onTogglePause: () => void;
};

export function Timeline({ start, end, progress, status, busy, paused, speed, onSpeedChange, onReplay, onTogglePause }: Props) {
  const ticks = makeTicks(start, end);
  const pct = Math.max(0, Math.min(1, progress));
  const running = busy && progress < 1;

  const [showSpotlight, setShowSpotlight] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const [btnRect, setBtnRect] = useState<DOMRect | null>(null);

  // Show 1 second after mount
  useEffect(() => {
    const t = setTimeout(() => {
      if (btnRef.current) setBtnRect(btnRef.current.getBoundingClientRect());
      setShowSpotlight(true);
    }, 1000);
    return () => clearTimeout(t);
  }, []);

  // Dismiss once replay starts
  useEffect(() => {
    if (busy) setShowSpotlight(false);
  }, [busy]);

  function dismiss() { setShowSpotlight(false); }

  return (
    <div className="tlBar">

      <SpeedControl speed={speed} onChange={onSpeedChange} disabled={busy} />

      {running ? (
        <button
          className={`tlTransportBtn${paused ? " tlTransportBtn--paused" : " tlTransportBtn--running"}`}
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
      ) : (
        <button
          ref={btnRef}
          className={`tlTransportBtn tlTransportBtn--replay${busy ? " tlTransportBtn--busy" : ""}${showSpotlight ? " tlTransportBtn--spotlit" : ""}`}
          onClick={() => { dismiss(); onReplay(); }}
          disabled={busy}
        >
          {busy ? (
            <>
              <span className="tlBusyDots">▪▪▪</span>
              <span>BUFFERING</span>
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
      )}

      {showSpotlight && btnRect && createPortal(
        <div className="tlSpotlight" onClick={dismiss}>
          {/* Label above the button */}
          <div
            className="tlSpotlightLabel"
            style={{ left: btnRect.left + btnRect.width / 2, top: btnRect.top - 14 }}
          >
            <span className="tlSpotlightTitle">START HERE</span>
            <span className="tlSpotlightSub">Press REPLAY to begin the simulation</span>
            <span className="tlSpotlightArrow" />
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

function SpeedControl({ speed, onChange, disabled }: { speed: number; onChange: (v: number) => void; disabled: boolean }) {
  const idx = SPEED_STEPS.findIndex(s => s.value === speed);
  const current = SPEED_STEPS[idx] ?? SPEED_STEPS[3];

  function step(dir: 1 | -1) {
    const next = SPEED_STEPS[Math.max(0, Math.min(SPEED_STEPS.length - 1, idx + dir))];
    if (next && next.value !== speed) onChange(next.value);
  }

  return (
    <div className="tlSpeedControl">
      <button className="tlSpeedBtn" onClick={() => step(-1)} disabled={disabled || idx === 0} title="Slower">‹</button>
      <span className="tlSpeedLabel">{current.label}</span>
      <button className="tlSpeedBtn" onClick={() => step(1)} disabled={disabled || idx === SPEED_STEPS.length - 1} title="Faster">›</button>
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
  const count = Math.min(days + 1, 9);
  return Array.from({ length: count }, (_, i) => {
    const p = count <= 1 ? 0 : i / (count - 1);
    const d = new Date(a.getTime() + span * p);
    return { label: d.toISOString().slice(5, 10), pct: p };
  });
}
