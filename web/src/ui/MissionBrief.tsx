import type { FireEvent, ThreatPayload } from "../types";

type Props = {
  events: FireEvent[];
  threat: ThreatPayload | null;
  simDate: string | null;
};

export function MissionBrief({ events, threat, simDate }: Props) {
  const critical = events.reduce(
    (n, e) => n + ((e.threat_score ?? 0) >= 75 ? 1 : 0),
    0,
  );
  const phaseLabel = threat
    ? "PHASE 3 · EVACUATION DECISIONING"
    : critical > 0
      ? "PHASE 2 · THREAT TRACKING"
      : events.length > 0
        ? "PHASE 1 · ACTIVE MONITORING"
        : "PHASE 0 · READY";

  const phaseClass = threat
    ? "missionBrief--decision"
    : critical > 0
      ? "missionBrief--tracking"
      : events.length > 0
        ? "missionBrief--monitoring"
        : "missionBrief--ready";

  return (
    <div className={`missionBrief ${phaseClass}`}>
      <div className="missionBriefHead">
        <span className="missionBriefBadge">FG-OPS</span>
        <span className="missionBriefTitle">WILLIAMS LAKE</span>
      </div>
      <div className="missionBriefRows">
        <div className="missionBriefRow">
          <span className="missionBriefKey">MISSION</span>
          <span className="missionBriefVal">WILDFIRE EVAC RECON</span>
        </div>
        <div className="missionBriefRow">
          <span className="missionBriefKey">REGION</span>
          <span className="missionBriefVal">CARIBOO FIRE CENTRE · BC</span>
        </div>
        <div className="missionBriefRow">
          <span className="missionBriefKey">CLOCK</span>
          <span className="missionBriefVal">{simDate ?? "STANDBY"}</span>
        </div>
        <div className="missionBriefRow">
          <span className="missionBriefKey">AUTH</span>
          <span className="missionBriefVal">BCWS · MUNICIPAL EOC</span>
        </div>
      </div>
      <div className="missionBriefPhase">
        <span className="missionBriefPhaseDot" />
        <span className="missionBriefPhaseText">{phaseLabel}</span>
      </div>
    </div>
  );
}
