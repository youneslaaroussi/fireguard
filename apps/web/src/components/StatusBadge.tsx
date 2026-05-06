type Props = {
  label: string;
  tone?: "neutral" | "ok" | "warn" | "danger" | "info";
};

const tones = {
  neutral: "border-line bg-slate-900 text-slate-200",
  ok: "border-emerald-500/50 bg-emerald-500/15 text-emerald-100",
  warn: "border-amber/50 bg-amber/15 text-amber-100",
  danger: "border-fire/60 bg-fire/15 text-orange-100",
  info: "border-shelter/50 bg-shelter/15 text-sky-100",
};

export function StatusBadge({ label, tone = "neutral" }: Props) {
  return <span className={`inline-flex items-center border px-2 py-1 text-xs font-medium ${tones[tone]}`}>{label}</span>;
}
