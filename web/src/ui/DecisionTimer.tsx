import { memo, useEffect, useRef, useState } from "react";
import type { ThreatPayload } from "../types";

type Props = {
  threat: ThreatPayload | null;
  hasPlan: boolean;
};

const RESPONSE_BUDGET_MS = 120_000; // "2 min response budget"

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSec / 60);
  const seconds = totalSec % 60;
  const tenths = Math.floor((ms % 1000) / 100);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

export const DecisionTimer = memo(function DecisionTimer({ threat, hasPlan }: Props) {
  const [elapsedMs, setElapsedMs] = useState(0);
  const startRef = useRef<number | null>(null);
  const lockedAtRef = useRef<number | null>(null);
  const threatKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const key = threat ? `${threat.zone.name}|${threat.hotspot.acquired_at}` : null;
    if (key !== threatKeyRef.current) {
      threatKeyRef.current = key;
      startRef.current = key ? performance.now() : null;
      lockedAtRef.current = null;
      setElapsedMs(0);
    }
  }, [threat]);

  // Lock the timer when a plan arrives
  useEffect(() => {
    if (hasPlan && threat && startRef.current && lockedAtRef.current === null) {
      lockedAtRef.current = performance.now();
    }
  }, [hasPlan, threat]);

  useEffect(() => {
    if (!threat) return;
    let raf = 0;
    const tick = () => {
      const now = performance.now();
      const start = startRef.current ?? now;
      const end = lockedAtRef.current ?? now;
      setElapsedMs(Math.max(0, end - start));
      if (lockedAtRef.current === null) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [threat, hasPlan]);

  if (!threat) return null;

  const budgetPct = Math.min(1, elapsedMs / RESPONSE_BUDGET_MS);
  const locked = lockedAtRef.current !== null;

  return (
    <div className={`decisionTimer${locked ? " decisionTimer--locked" : ""}`}>
      <div className="decisionTimerHeader">
        <span className="decisionTimerDot" />
        <span className="decisionTimerLabel">
          {locked ? "DECISION ISSUED" : "AGENT DECIDING"}
        </span>
      </div>
      <div className="decisionTimerValue">{formatElapsed(elapsedMs)}</div>
      <div className="decisionTimerSub">
        {locked ? "vs ~30 MIN MANUAL BASELINE" : "T+ SINCE THREAT DETECTED"}
      </div>
      <div className="decisionTimerBar">
        <div
          className={`decisionTimerBarFill${budgetPct >= 0.85 ? " decisionTimerBarFill--late" : ""}`}
          style={{ width: `${budgetPct * 100}%` }}
        />
      </div>
    </div>
  );
});
