import type { ActionItem, ActionPlan, ActionPriority } from "../intelligence/types";

const PRIORITY_LABEL: Record<ActionPriority, string> = {
  immediate: "IMMEDIATE",
  urgent:    "URGENT",
  monitor:   "MONITOR",
};

const PRIORITY_CLASS: Record<ActionPriority, string> = {
  immediate: "actPriority--immediate",
  urgent:    "actPriority--urgent",
  monitor:   "actPriority--monitor",
};

const PRIORITY_ORDER: Record<ActionPriority, number> = {
  immediate: 0,
  urgent:    1,
  monitor:   2,
};

function ActionCard({ item }: { item: ActionItem }) {
  const cls = PRIORITY_CLASS[item.priority] ?? "";
  return (
    <div className={`actCard actCard--${item.priority}`}>
      <span className={`actPriority ${cls}`}>{PRIORITY_LABEL[item.priority] ?? item.priority}</span>
      <span className="actCardTitle">{item.title}</span>
      {item.detail && <span className="actCardDetail">{item.detail}</span>}
      {item.owner && <span className="actCardOwner">{item.owner}</span>}
    </div>
  );
}

type Props = {
  plan: ActionPlan;
  onDismiss: () => void;
  onAct: (prompt: string) => void;
};

export function ActionsPanel({ plan, onDismiss, onAct }: Props) {
  const sorted = [...plan.actions].sort(
    (a, b) => (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9),
  );

  function handleAct() {
    const lines = sorted.map((a, i) =>
      `${i + 1}. [${(PRIORITY_LABEL[a.priority] ?? a.priority).toUpperCase()}] ${a.title}${a.detail ? ` — ${a.detail}` : ""}`
    ).join("\n");
    onAct(`Execute the following recommended actions now:\n${lines}\n\nProvide concrete next steps and confirm when each is initiated.`);
  }

  return (
    <div className="actionsPanel">
      <div className="actionsPanelHeader">
        <svg className="actionsPanelIcon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm.75 9.5h-1.5v-4h1.5v4zm0-5.5h-1.5V3.5h1.5V5z" fill="#facc15"/>
        </svg>
        <span className="actionsPanelTitle">RECOMMENDED ACTIONS</span>
        {plan.summary && <span className="actionsPanelSummary">{plan.summary}</span>}
        <button className="actionsPanelDismiss" type="button" onClick={onDismiss} title="Dismiss">✕</button>
      </div>
      <div className="actionsPanelBody">
        <div className="actionsPanelCards">
          {sorted.map((item) => (
            <ActionCard key={item.id} item={item} />
          ))}
        </div>
        <button className="actionsPanelActBtn" type="button" onClick={handleAct}>
          <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M8 1l2.5 4.5H14l-3 3 1 4.5L8 11l-4 2 1-4.5-3-3h3.5L8 1z" fill="currentColor"/>
          </svg>
          ACT
        </button>
      </div>
    </div>
  );
}
