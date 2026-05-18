"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getActionLogs } from "@/lib/api";
import type { ActionItem } from "@/lib/types";

function ActionIcon({ type }: { type: string }) {
  const style: React.CSSProperties = { flexShrink: 0 };
  if (type === "resident_sms") return (
    <svg style={style} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8abbff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
  if (type === "dispatch_task") return (
    <svg style={style} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8abbff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="3" width="15" height="13" rx="1" /><path d="M16 8h4l3 5v3h-7V8z" /><circle cx="5.5" cy="18.5" r="2.5" /><circle cx="18.5" cy="18.5" r="2.5" />
    </svg>
  );
  if (type === "shelter_notify") return (
    <svg style={style} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8abbff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  );
  if (type === "evacuation_order") return (
    <svg style={style} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8abbff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><path d="M15.54 8.46a5 5 0 0 1 0 7.07" /><path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
    </svg>
  );
  if (type === "road_closure") return (
    <svg style={style} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8abbff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="7" width="20" height="14" rx="2" /><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" /><line x1="12" y1="12" x2="12" y2="16" /><line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
  return (
    <svg style={style} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8abbff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  );
}

const STATUS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  executed: { bg: "#0d2b1e", text: "#45d483", border: "#1a4a30" },
  sent:     { bg: "#0d2b1e", text: "#45d483", border: "#1a4a30" },
  approved: { bg: "#0e1e2b", text: "#48aff0", border: "#1a3a50" },
  pending:  { bg: "#1a1400", text: "#f2b824", border: "#2a2200" },
  queued:   { bg: "#1a1400", text: "#f2b824", border: "#2a2200" },
  rejected: { bg: "#2b0d0d", text: "#d47070", border: "#4a1a1a" },
  failed:   { bg: "#2b0d0d", text: "#d47070", border: "#4a1a1a" },
  draft:    { bg: "#111820", text: "#5c7080", border: "#1a2530" },
};

function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] ?? STATUS_COLORS.draft;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 7px",
        background: c.bg,
        border: `1px solid ${c.border}`,
        borderRadius: 3,
        color: c.text,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
      }}
    >
      {status}
    </span>
  );
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return iso.slice(0, 19).replace("T", " ");
  }
}

function groupByBundle(actions: ActionItem[]): Map<string, ActionItem[]> {
  const map = new Map<string, ActionItem[]>();
  for (const a of actions) {
    const key = a.bundle_id ?? "unknown";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(a);
  }
  return map;
}

export default function HistoryPage() {
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await getActionLogs();
      setActions(res.actions);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load action logs");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const statuses = ["all", "executed", "sent", "approved", "pending", "rejected", "failed"];
  const filtered = filter === "all" ? actions : actions.filter((a) => a.status === filter);
  const grouped = groupByBundle(filtered);

  return (
    <main style={{ minHeight: "100vh", background: "#0b1117", color: "#edf5ff", fontFamily: "inherit" }}>
      {/* Header */}
      <header style={{
        position: "sticky", top: 0, zIndex: 40,
        display: "flex", alignItems: "center", gap: 12,
        padding: "0 20px", height: 56,
        background: "#1c2127", borderBottom: "1px solid #293742",
      }}>
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: 6, textDecoration: "none", color: "#8abbff", fontSize: 12, fontWeight: 700 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          Back
        </Link>
        <div style={{ width: 1, height: 18, background: "#293742" }} />
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#e05a5a" strokeWidth="2">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
        <span style={{ fontSize: 13, fontWeight: 800, letterSpacing: "0.08em", textTransform: "uppercase", color: "#fff" }}>FireGuard</span>
        <span style={{ color: "#293742" }}>·</span>
        <span style={{ fontSize: 12, color: "#8a9ba8" }}>Action Log</span>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "#4a5c6a" }}>{actions.length} total actions</span>
          <button
            onClick={load}
            style={{
              background: "#0e1820", border: "1px solid #1e3045", borderRadius: 3,
              color: "#8abbff", fontSize: 11, fontWeight: 700, padding: "4px 10px", cursor: "pointer",
              display: "flex", alignItems: "center", gap: 5,
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            Refresh
          </button>
        </div>
      </header>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 20px" }}>
        {/* Filter tabs */}
        <div style={{ display: "flex", gap: 6, marginBottom: 24, flexWrap: "wrap" }}>
          {statuses.map((s) => {
            const count = s === "all" ? actions.length : actions.filter((a) => a.status === s).length;
            if (count === 0 && s !== "all") return null;
            const active = filter === s;
            const c = s !== "all" ? STATUS_COLORS[s] : null;
            return (
              <button
                key={s}
                onClick={() => setFilter(s)}
                style={{
                  background: active ? (c?.bg ?? "#0e1820") : "#080d12",
                  border: `1px solid ${active ? (c?.border ?? "#1e3045") : "#1a2530"}`,
                  borderRadius: 3, cursor: "pointer",
                  color: active ? (c?.text ?? "#8abbff") : "#4a5c6a",
                  fontSize: 11, fontWeight: 700, letterSpacing: "0.06em",
                  textTransform: "uppercase", padding: "4px 10px",
                  display: "flex", alignItems: "center", gap: 5,
                }}
              >
                {s}
                <span style={{ opacity: 0.7, fontWeight: 400 }}>{count}</span>
              </button>
            );
          })}
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: "80px 0", color: "#4a5c6a", fontSize: 13 }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" style={{ animation: "fg-blink 1.4s ease-in-out infinite", display: "block", margin: "0 auto 12px" }}>
              <circle cx="12" cy="12" r="10" stroke="#1e3045" strokeWidth="2" />
              <path d="M12 6v6l4 2" stroke="#8abbff" strokeWidth="2" strokeLinecap="round" />
            </svg>
            Loading action logs...
          </div>
        ) : error ? (
          <div style={{ background: "#1c0a0a", border: "1px solid #4a1a1a", borderRadius: 4, padding: "14px 16px", color: "#d47070", fontSize: 12 }}>
            {error}
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ textAlign: "center", padding: "80px 0", color: "#4a5c6a", fontSize: 13 }}>
            No actions yet. Run an assessment to generate actions.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            {Array.from(grouped.entries()).map(([bundleId, bundleActions]) => {
              const latest = bundleActions[0];
              const execCount = bundleActions.filter((a) => ["executed", "sent"].includes(a.status)).length;
              const bundleTs = latest?.created_at;
              return (
                <div key={bundleId} style={{ background: "#0d151e", border: "1px solid #1a2530", borderRadius: 5, overflow: "hidden" }}>
                  {/* Bundle header */}
                  <div style={{
                    padding: "10px 16px",
                    background: "#0b1117",
                    borderBottom: "1px solid #1a2530",
                    display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
                  }}>
                    <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.1em", color: "#2d72d2", background: "#06101e", border: "1px solid #1a3050", borderRadius: 2, padding: "2px 6px" }}>BUNDLE</span>
                    <span style={{ fontSize: 11, fontFamily: "monospace", color: "#48aff0" }}>{bundleId.slice(0, 20)}…</span>
                    <span style={{ color: "#1a2530" }}>·</span>
                    <span style={{ fontSize: 11, color: "#4a5c6a" }}>{bundleActions.length} actions</span>
                    <span style={{ color: "#1a2530" }}>·</span>
                    <span style={{ fontSize: 11, color: "#4a5c6a" }}>{execCount} dispatched</span>
                    {bundleTs ? (
                      <>
                        <span style={{ color: "#1a2530" }}>·</span>
                        <span style={{ fontSize: 11, color: "#293742" }}>{fmtDate(bundleTs)}</span>
                      </>
                    ) : null}
                  </div>

                  {/* Action rows */}
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid #111e2a" }}>
                        {["Type", "Target", "Message", "Status", "Confidence", "Executed At"].map((h) => (
                          <th key={h} style={{ padding: "7px 14px", textAlign: "left", fontSize: 9, fontWeight: 800, letterSpacing: "0.1em", textTransform: "uppercase", color: "#293742" }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {bundleActions.map((action, i) => (
                        <tr
                          key={action.action_id}
                          style={{
                            borderBottom: i < bundleActions.length - 1 ? "1px solid #0e1820" : "none",
                            transition: "background 0.1s",
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = "#0e1820")}
                          onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                        >
                          <td style={{ padding: "10px 14px", whiteSpace: "nowrap" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                              <ActionIcon type={action.action_type} />
                              <span style={{ fontSize: 11, fontWeight: 700, color: "#8abbff", fontFamily: "monospace" }}>{action.action_type}</span>
                            </div>
                          </td>
                          <td style={{ padding: "10px 14px", fontSize: 11, color: "#c0ccd8", fontWeight: 600, whiteSpace: "nowrap" }}>
                            {action.target}
                          </td>
                          <td style={{ padding: "10px 14px", fontSize: 11, color: "#8a9ba8", maxWidth: 300 }}>
                            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{action.message}</div>
                            {action.reason ? (
                              <div style={{ fontSize: 10, color: "#4a5c6a", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{action.reason}</div>
                            ) : null}
                          </td>
                          <td style={{ padding: "10px 14px", whiteSpace: "nowrap" }}>
                            <StatusBadge status={action.status} />
                          </td>
                          <td style={{ padding: "10px 14px", fontSize: 11, color: "#5c7080", whiteSpace: "nowrap" }}>
                            {action.confidence != null ? `${Math.round(action.confidence * 100)}%` : "—"}
                          </td>
                          <td style={{ padding: "10px 14px", fontSize: 11, color: "#293742", whiteSpace: "nowrap" }}>
                            {fmtDate(action.executed_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}
