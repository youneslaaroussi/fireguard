import { useEffect, useMemo, useState } from "react";
import type { ActionPlan } from "../intelligence/types";
import type { ThreatPayload } from "../types";

type Props = {
  plan: ActionPlan | null;
  threat: ThreatPayload | null;
};

type ChannelState = {
  key: string;
  label: string;
  sent: number;
  total: number;
  ms: number;
  done: boolean;
};

const CHANNEL_TEMPLATES: Array<{ key: string; label: string; weight: number; latencyMs: number }> = [
  { key: "wea",      label: "WIRELESS EMERGENCY ALERT", weight: 0.78, latencyMs: 620 },
  { key: "sms",      label: "SMS",                      weight: 0.12, latencyMs: 880 },
  { key: "radio",    label: "RADIO BROADCAST",          weight: 0.06, latencyMs: 240 },
  { key: "siren",    label: "OUTDOOR SIREN",            weight: 0.04, latencyMs: 180 },
];

export function BroadcastCard({ plan, threat }: Props) {
  // Trigger when a new threat appears and a plan exists
  const targetKey = useMemo(() => {
    if (!plan || !threat) return null;
    return `${threat.zone.name}|${threat.hotspot.acquired_at}`;
  }, [plan, threat]);

  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [channels, setChannels] = useState<ChannelState[]>([]);
  const [dismissed, setDismissed] = useState<string | null>(null);

  // Spin up a broadcast simulation when a fresh plan + threat appears
  useEffect(() => {
    if (!targetKey || !threat) return;
    if (targetKey === activeKey) return;
    if (targetKey === dismissed) return;

    const totalPop = threat.zone.population ?? 1548;
    const initial: ChannelState[] = CHANNEL_TEMPLATES.map((tmpl) => ({
      key: tmpl.key,
      label: tmpl.label,
      sent: 0,
      total: Math.max(1, Math.round(totalPop * tmpl.weight)),
      ms: tmpl.latencyMs,
      done: false,
    }));

    setActiveKey(targetKey);
    setChannels(initial);

    const cleanups: number[] = [];
    initial.forEach((ch, i) => {
      const stepCount = 12;
      const stepMs = Math.max(40, Math.round(ch.ms / stepCount));
      for (let s = 1; s <= stepCount; s++) {
        const id = window.setTimeout(() => {
          setChannels((prev) => {
            const next = [...prev];
            const t = next[i];
            if (!t) return prev;
            next[i] = {
              ...t,
              sent: Math.round(t.total * (s / stepCount)),
              done: s === stepCount,
            };
            return next;
          });
        }, s * stepMs + i * 80);
        cleanups.push(id);
      }
    });

    return () => {
      for (const id of cleanups) window.clearTimeout(id);
    };
  }, [targetKey, threat, activeKey, dismissed]);

  if (!plan || !threat || !activeKey) return null;
  if (dismissed === activeKey) return null;

  const totalSent = channels.reduce((n, c) => n + c.sent, 0);
  const totalTarget = channels.reduce((n, c) => n + c.total, 0);
  const allDone = channels.length > 0 && channels.every((c) => c.done);
  const elapsedMs = Math.max(...channels.map((c) => c.ms));
  const pct = totalTarget === 0 ? 0 : Math.min(1, totalSent / totalTarget);

  return (
    <div className={`broadcastCard${allDone ? " broadcastCard--complete" : ""}`}>
      <div className="broadcastHead">
        <svg className="broadcastIcon" width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="1.6" fill="currentColor"/>
          <path d="M4.5 4.5a5 5 0 0 0 0 7" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round"/>
          <path d="M11.5 4.5a5 5 0 0 1 0 7" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round"/>
          <path d="M2.5 2.5a8 8 0 0 0 0 11" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" opacity="0.6"/>
          <path d="M13.5 2.5a8 8 0 0 1 0 11" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" opacity="0.6"/>
        </svg>
        <span className="broadcastTitle">{allDone ? "BROADCAST DELIVERED" : "BROADCAST TRANSMITTING"}</span>
        <span className="broadcastZone">{threat.zone.name}</span>
        <span className="broadcastTotal">{totalSent.toLocaleString()} / {totalTarget.toLocaleString()}</span>
        <button className="broadcastClose" onClick={() => setDismissed(activeKey)} title="Dismiss">✕</button>
      </div>
      <div className="broadcastBar">
        <div className="broadcastBarFill" style={{ width: `${pct * 100}%` }} />
      </div>
      <div className="broadcastChannels">
        {channels.map((ch) => (
          <div key={ch.key} className={`broadcastChannel${ch.done ? " broadcastChannel--done" : ""}`}>
            <span className="broadcastChannelDot" />
            <span className="broadcastChannelLabel">{ch.label}</span>
            <span className="broadcastChannelCount">{ch.sent.toLocaleString()}</span>
            <span className="broadcastChannelStatus">{ch.done ? "DELIVERED" : "TX"}</span>
          </div>
        ))}
      </div>
      {allDone && (
        <div className="broadcastFooter">
          ALERT DISPATCHED VIA 4 CHANNELS · {(elapsedMs / 1000).toFixed(2)}s · CMAS / IPAWS-COMPATIBLE
        </div>
      )}
    </div>
  );
}
