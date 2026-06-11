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

function ActionRow({ item }: { item: ActionItem }) {
  const cls = PRIORITY_CLASS[item.priority] ?? "";
  return (
    <li className="actItem">
      <div className="actItemTop">
        <span className={`actPriority ${cls}`}>{PRIORITY_LABEL[item.priority] ?? item.priority}</span>
        <span className="actTitle">{item.title}</span>
      </div>
      {item.detail && <p className="actDetail">{item.detail}</p>}
      {item.owner && <span className="actOwner">{item.owner}</span>}
    </li>
  );
}

type Props = {
  plan: ActionPlan;
  onDismiss: () => void;
};

export function ActionsPanel({ plan, onDismiss }: Props) {
  const sorted = [...plan.actions].sort(
    (a, b) => (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9),
  );

  return (
    <div className="actionsPanel">
      <div className="actHeader">
        <div className="actHeaderLeft">
          <svg className="actHeaderIcon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm.75 9.5h-1.5v-4h1.5v4zm0-5.5h-1.5V3.5h1.5V5z" fill="#facc15"/>
          </svg>
          <span className="actHeaderTitle">RECOMMENDED ACTIONS</span>
          <span className="actCount">{sorted.length}</span>
        </div>
        <button className="actDismiss" type="button" onClick={onDismiss} title="Dismiss">
          <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </button>
      </div>
      {plan.summary && <p className="actSummary">{plan.summary}</p>}
      <ul className="actList">
        {sorted.map((item) => (
          <ActionRow key={item.id} item={item} />
        ))}
      </ul>
    </div>
  );
}
