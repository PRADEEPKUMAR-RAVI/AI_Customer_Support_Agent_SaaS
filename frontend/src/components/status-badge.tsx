import { cn } from "@/lib/utils";

type Tone = "muted" | "primary" | "success" | "warning" | "info" | "danger";

const TONE: Record<Tone, { pill: string; dot: string }> = {
  muted: { pill: "bg-secondary text-muted-foreground border-border", dot: "bg-muted-foreground/60" },
  primary: { pill: "bg-accent text-accent-foreground", dot: "bg-primary" },
  success: { pill: "bg-success/12 text-success", dot: "bg-success" },
  warning: { pill: "bg-warning/20 text-warning-foreground", dot: "bg-warning" },
  info: { pill: "bg-info/12 text-info", dot: "bg-info" },
  danger: { pill: "bg-destructive/12 text-destructive", dot: "bg-destructive" },
};

// Canonical status/priority/state values → label + tone. Falls back to a humanized muted pill.
const MAP: Record<string, { label: string; tone: Tone; pulse?: boolean }> = {
  // ticket lifecycle
  new: { label: "New", tone: "muted" },
  ai_handling: { label: "AI handling", tone: "primary" },
  escalated: { label: "Escalated", tone: "warning" },
  with_agent: { label: "With agent", tone: "info" },
  resolved: { label: "Resolved", tone: "success" },
  closed: { label: "Closed", tone: "muted" },
  reopened: { label: "Reopened", tone: "warning" },
  // priority
  low: { label: "Low", tone: "muted" },
  normal: { label: "Normal", tone: "muted" },
  high: { label: "High", tone: "warning" },
  urgent: { label: "Urgent", tone: "danger" },
  // ingestion / source
  queued: { label: "Queued", tone: "muted" },
  ingesting: { label: "Ingesting", tone: "info", pulse: true },
  ready: { label: "Ready", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  // tag approval + presence
  approved: { label: "Approved", tone: "success" },
  pending: { label: "Pending", tone: "warning" },
  available: { label: "Available", tone: "success" },
  away: { label: "Away", tone: "muted" },
  active: { label: "Active", tone: "success" },
  suspended: { label: "Suspended", tone: "danger" },
};

function humanize(v: string): string {
  return v.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function StatusBadge({ value, className }: { value: string; className?: string }) {
  const entry = MAP[value] ?? { label: humanize(value), tone: "muted" as Tone };
  const tone = TONE[entry.tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-transparent px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        tone.pill,
        className
      )}
    >
      <span className={cn("size-1.5 rounded-full", tone.dot, entry.pulse && "animate-pulse")} />
      {entry.label}
    </span>
  );
}
