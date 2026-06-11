import { Dialog, Tag, Intent } from "@blueprintjs/core";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ClickedNodeInfo } from "./WorkflowGraph";
import type { StreamEvent } from "./types";

type Props = {
  node: ClickedNodeInfo | null;
  events: StreamEvent[];
  googleMapsKey?: string;
  onClose: () => void;
};

const STATUS_INTENT: Record<string, Intent> = {
  completed: Intent.SUCCESS,
  running:   Intent.PRIMARY,
  failed:    Intent.DANGER,
  rejected:  Intent.DANGER,
  waiting:   Intent.WARNING,
  pending:   Intent.NONE,
};

// Extract lat/lon from any object recursively (first found)
function findLatLon(obj: unknown, depth = 0): { lat: number; lon: number } | null {
  if (depth > 4 || obj === null || typeof obj !== "object" || Array.isArray(obj)) return null;
  const o = obj as Record<string, unknown>;
  const lat = typeof o.lat === "number" ? o.lat : typeof o.latitude === "number" ? o.latitude : null;
  const lon = typeof o.lon === "number" ? o.lon : typeof o.longitude === "number" ? o.longitude : null;
  if (lat !== null && lon !== null) return { lat, lon };
  for (const v of Object.values(o)) {
    const found = findLatLon(v, depth + 1);
    if (found) return found;
  }
  return null;
}

function toolEvents(events: StreamEvent[], nodeId: string) {
  return events.filter(
    (e) =>
      (e.node_id === nodeId || e.agent_id === nodeId) &&
      (e.event_type === "tool.started" || e.event_type === "tool.completed" || e.event_type === "tool.failed"),
  );
}

function agentMessages(events: StreamEvent[], nodeId: string) {
  return events.filter(
    (e) =>
      (e.node_id === nodeId || e.agent_id === nodeId) &&
      e.event_type === "agent.message.completed" &&
      typeof e.data.content === "string" &&
      (e.data.content as string).trim().length > 0,
  );
}

// For entity nodes (tool_xxx) find the parent tool event output
function entityToolOutput(events: StreamEvent[], nodeId: string): Record<string, unknown> | null {
  // nodeId looks like: tool_<parentId>_<invId>_<kind>_<slug>_<idx>
  const invMatch = nodeId.match(/^tool_[^_]+_([^_]+)/);
  if (!invMatch) return null;
  const invId = invMatch[1];
  const ev = events.find(
    (e) => e.event_type === "tool.completed" && e.data.invocation_id === invId,
  );
  if (!ev) return null;
  const out = ev.data.output;
  return out !== null && typeof out === "object" && !Array.isArray(out)
    ? (out as Record<string, unknown>)
    : null;
}

function renderValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof v === "string") return v || "—";
  return JSON.stringify(v);
}

function KV({ k, v }: { k: string; v: unknown }) {
  return (
    <div className="ndm-kv">
      <span className="ndm-key">{k}</span>
      <span className="ndm-val">{renderValue(v)}</span>
    </div>
  );
}

export function NodeDetailModal({ node, events, googleMapsKey = "", onClose }: Props) {
  if (!node) return null;

  const intent = STATUS_INTENT[node.status] ?? Intent.NONE;
  const badge = node.platformBadge;

  // Find relevant tool output for this node
  const isEntity = node.id.startsWith("tool_") && node.layer === "entity";
  const isTool = node.id.startsWith("tool_") && node.layer === "tool";
  const toolEvts = isTool ? toolEvents(events, node.id.replace(/^tool_/, "").split("_")[0]) : [];
  const entityOutput = isEntity ? entityToolOutput(events, node.id) : null;
  const msgs = agentMessages(events, node.id);

  // Find coordinates for a map image
  const coords = findLatLon(entityOutput) ?? findLatLon(
    events.find(
      (e) => (e.node_id === node.id || e.agent_id === node.id) &&
        e.event_type === "tool.completed",
    )?.data ?? null,
  );

  const mapImgUrl =
    googleMapsKey && coords
      ? (() => {
          const p = new URLSearchParams({
            center: `${coords.lat},${coords.lon}`,
            zoom: badge === "hotspot" ? "13" : badge === "route" ? "10" : "14",
            size: "560x220",
            maptype: badge === "hotspot" ? "satellite" : "roadmap",
            key: googleMapsKey,
            style: [
              "feature:all|element:labels|visibility:simplified",
              "feature:water|color:0x0d1b2a",
              "feature:landscape|color:0x111d2b",
              "feature:road|color:0x1e3a5f",
              "feature:poi|visibility:off",
            ].map((s) => `style=${s}`).join("&").replace("style=", ""),
          });
          // manually add multiple style params
          const base = `https://maps.googleapis.com/maps/api/staticmap?center=${coords.lat},${coords.lon}&zoom=${badge === "hotspot" ? 13 : badge === "route" ? 10 : 14}&size=560x220&maptype=${badge === "hotspot" ? "satellite" : "roadmap"}&key=${googleMapsKey}`;
          return base;
        })()
      : null;

  // Structured output fields to show
  const outputFields: Array<[string, unknown]> = entityOutput
    ? Object.entries(entityOutput).filter(
        ([k, v]) =>
          !Array.isArray(v) &&
          typeof v !== "object" &&
          !["ok", "source_url"].includes(k),
      )
    : [];

  const isRejected = node.status === "failed" || node.status === "rejected";

  return (
    <Dialog
      className="ndm-dialog bp6-dark"
      isOpen
      onClose={onClose}
      title={null}
      canOutsideClickClose
      canEscapeKeyClose
    >
      <div className="ndm-header" style={{ borderColor: node.accentColor + "66" }}>
        <div className="ndm-header-top">
          <div className="ndm-title-row">
            <span className="ndm-glyph" style={{ color: node.accentColor }}>{nodeGlyph(badge, node.label)}</span>
            <span className="ndm-title">{node.label}</span>
            <Tag intent={intent} minimal className="ndm-status-tag">{node.status.toUpperCase()}</Tag>
          </div>
          {badge && (
            <span className="ndm-badge" style={{ color: node.accentColor }}>
              {badge.toUpperCase()}
            </span>
          )}
        </div>
        {node.summary && <p className="ndm-summary">{node.summary}</p>}
        {isRejected && (
          <div className="ndm-rejected-banner">
            ✕ This location was evaluated and excluded from the evacuation plan
          </div>
        )}
      </div>

      <div className="ndm-body">
        {/* Map image */}
        {mapImgUrl && (
          <div className="ndm-map-section">
            <img
              className="ndm-map-img"
              src={mapImgUrl}
              alt={`Map for ${node.label}`}
              loading="lazy"
            />
            <div className="ndm-map-coords">
              {coords!.lat.toFixed(4)}, {coords!.lon.toFixed(4)}
            </div>
          </div>
        )}

        {/* Key/value output fields */}
        {outputFields.length > 0 && (
          <div className="ndm-section">
            <div className="ndm-section-title">DATA</div>
            <div className="ndm-kvgrid">
              {outputFields.map(([k, v]) => <KV key={k} k={k.replace(/_/g, " ").toUpperCase()} v={v} />)}
            </div>
          </div>
        )}

        {/* Agent assessment / messages */}
        {msgs.length > 0 && (
          <div className="ndm-section">
            <div className="ndm-section-title">AGENT ASSESSMENT</div>
            <div className="ndm-messages">
              {msgs.map((e) => (
                <div key={e.event_id} className="ndm-message">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{String(e.data.content)}</ReactMarkdown>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tool calls for workflow nodes */}
        {toolEvts.length > 0 && (
          <div className="ndm-section">
            <div className="ndm-section-title">TOOL CALLS</div>
            {toolEvts.map((e) => (
              <div key={e.event_id} className="ndm-tool-row">
                <span className={`ndm-tool-status ndm-tool-status--${e.event_type.split(".")[1]}`}>
                  {e.event_type.split(".")[1].toUpperCase()}
                </span>
                <span className="ndm-tool-name">{String(e.data.tool_name ?? "tool")}</span>
              </div>
            ))}
          </div>
        )}

        {/* Nothing available */}
        {msgs.length === 0 && outputFields.length === 0 && toolEvts.length === 0 && !mapImgUrl && (
          <div className="ndm-empty">
            {node.status === "pending" ? "This node has not run yet." : "No detail available for this node."}
          </div>
        )}
      </div>
    </Dialog>
  );
}

function nodeGlyph(badge: string | null | undefined, label: string): string {
  if (badge === "elastic")    return "⬡";
  if (badge === "nasa")       return "✦";
  if (badge === "googlemaps") return "◎";
  if (badge === "zone")       return "⬡";
  if (badge === "shelter_open" || badge === "open") return "⌂";
  if (badge === "shelter_closed" || badge === "closed") return "⌂";
  if (badge === "road")       return "⚠";
  if (badge === "hotspot")    return "✦";
  if (badge === "route")      return "→";
  if (badge === "weather")    return "~";
  const id = label.toLowerCase();
  if (id.includes("trigger"))   return "▶";
  if (id.includes("data") || id.includes("research")) return "◈";
  if (id.includes("evacuation") || id.includes("brief")) return "✎";
  if (id.includes("response") || id.includes("terminal")) return "✔";
  if (id.includes("zone"))    return "⬡";
  if (id.includes("shelter")) return "⌂";
  if (id.includes("road"))    return "⚠";
  if (id.includes("fire") || id.includes("detect")) return "✦";
  if (id.includes("route"))   return "→";
  return "●";
}
