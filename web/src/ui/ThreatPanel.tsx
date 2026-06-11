import type { ThreatPayload } from "../types";

type Props = {
  threat: ThreatPayload;
  onOpenIntelligence: () => void;
};

export function ThreatPanel({ threat, onOpenIntelligence }: Props) {
  const { hotspot, zone } = threat;
  return (
    <div className="threatPanel">
      <div className="threatPanelHeader">
        <span className="threatPanelTitle">THREAT DETECTED</span>
        <span className="threatPanelZone">{zone.name}</span>
      </div>
      <div className="threatPanelGrid">
        <Row k="FRP" v={`${hotspot.frp.toFixed(1)} MW`} />
        <Row k="CONFIDENCE" v={hotspot.confidence ?? "—"} />
        <Row k="DISTANCE" v={zone.distance_km != null ? `${zone.distance_km.toFixed(1)} km` : "—"} />
        <Row k="SOURCE" v={hotspot.source} />
        <Row k="POPULATION" v={zone.population != null ? zone.population.toLocaleString() : "—"} />
        <Row k="HOMES" v={zone.homes != null ? zone.homes.toLocaleString() : "—"} />
        <Row k="ACQUIRED" v={hotspot.acquired_at.slice(0, 16).replace("T", " ")} />
        <Row k="POSITION" v={`${hotspot.lat.toFixed(4)}, ${hotspot.lon.toFixed(4)}`} />
      </div>
      <button className="threatPanelBtn" type="button" onClick={onOpenIntelligence}>
        OPEN INTELLIGENCE
      </button>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="threatPanelRow">
      <span className="threatPanelKey">{k}</span>
      <span className="threatPanelVal">{v}</span>
    </div>
  );
}
