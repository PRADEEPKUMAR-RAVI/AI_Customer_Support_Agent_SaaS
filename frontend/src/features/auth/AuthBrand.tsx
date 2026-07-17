/** Shared visual language for the full-page auth surfaces (`/signup`, `/login`, `/forgot`): the
 * sun/moon theme switch, the "Relay" brand mark, and the pitch panel with its signature relay
 * graphic (question → verified → resolved). Extracted so every future tweak to this identity
 * (colors, copy, motion) applies to every entry point at once instead of drifting between
 * copies. `/verify` and `/reset` stay on the plain shared `AuthLayout` — they're one-shot,
 * token-driven landings (usually opened from an email link) rather than a page a user chooses
 * to visit, so they don't need the pitch. */

import { CheckCircle2, Lock, MessageSquare, Users, Waypoints, Zap, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { ThemeSwitch } from "@/components/theme-switch";
import { cn } from "@/lib/utils";

// ── brand mark ───────────────────────────────────────────────────────────────────────────────

export function BrandMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm",
        className
      )}
    >
      <Waypoints className="size-4" />
    </div>
  );
}

export function BrandWordmark({ className }: { className?: string }) {
  return (
    <Link to="/" className={cn("relative flex items-center gap-2.5", className)}>
      <BrandMark />
      <span className="text-sm font-semibold tracking-tight">Relay</span>
    </Link>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <p className="font-mono text-xl font-semibold tabular-nums text-foreground">{value}</p>
      <p className="mt-1 text-[11px] text-muted-foreground">{label}</p>
    </div>
  );
}

// ── signature: question → verified → resolved ───────────────────────────────────────────────────

const FLOW_TONE = {
  question: { ring: "border-warning/40 bg-warning/15 text-warning", track: "via-blue-500/80" },
  verified: { ring: "border-blue-500/40 bg-blue-500/10 text-blue-600 dark:text-blue-400", track: "via-success" },
  resolved: { ring: "border-success/40 bg-success/10 text-success", track: "" },
} as const;

/** Soft halo behind each step's icon — all three steps glow at the same intensity, since every
 * gate matters equally; only the hue changes as a turn moves from asked, to checked, to landed. */
const GLOW_TONE = {
  question: "bg-warning/25",
  verified: "bg-blue-500/25",
  resolved: "bg-success/25",
} as const;

function FlowStep({
  icon: Icon,
  label,
  tone,
  glow,
}: {
  icon: LucideIcon;
  label: string;
  tone: keyof typeof FLOW_TONE;
  glow: keyof typeof GLOW_TONE;
}) {
  return (
    <div className="flex w-16 flex-col items-center gap-2.5 text-center">
      <div className="relative grid place-items-center">
        <div aria-hidden className={cn("absolute size-9 rounded-full blur-md", GLOW_TONE[glow])} />
        <div
          className={cn(
            "relative grid size-10 place-items-center rounded-full border",
            FLOW_TONE[tone].ring
          )}
        >
          <Icon className="size-4" />
        </div>
      </div>
      <span className="text-[10px] leading-tight font-medium text-muted-foreground">{label}</span>
    </div>
  );
}

function FlowTrack({ tone }: { tone: keyof typeof FLOW_TONE }) {
  return (
    <div className="flex-1 pt-5">
      <div className="relative h-px overflow-hidden bg-border">
        <span
          aria-hidden
          className={cn(
            "absolute inset-y-0 w-10 -translate-x-1/2 bg-gradient-to-r from-transparent to-transparent",
            FLOW_TONE[tone].track
          )}
          style={{ animation: "relay-flow 2.4s ease-in-out infinite" }}
        />
      </div>
    </div>
  );
}

/** Signature element: how a real turn resolves. A customer asks, Relay checks the question
 * against your content before answering, and the turn lands resolved. See CLAUDE.md non-negotiable
 * #3 for the actual gate this mirrors. */
export function FlowGraphic() {
  return (
    <div className="rounded-2xl border border-border bg-card/60 p-5 shadow-sm">
      <div className="flex items-start">
        <FlowStep icon={MessageSquare} label="Question" tone="question" glow="question" />
        <FlowTrack tone="question" />
        <FlowStep icon={Lock} label="Verified" tone="verified" glow="verified" />
        <FlowTrack tone="verified" />
        <FlowStep icon={CheckCircle2} label="Resolved" tone="resolved" glow="resolved" />
      </div>
    </div>
  );
}

// ── pitch panel (desktop only) ───────────────────────────────────────────────────────────────

export function BrandPanel() {
  return (
    <div className="relative hidden flex-col justify-between bg-gradient-to-br from-secondary/70 to-secondary/25 px-10 py-10 lg:flex lg:px-11 lg:py-11">
      <BrandWordmark />

      <div className="relative w-full space-y-6">
        <div className="space-y-4">
          <div aria-hidden className="h-1 w-10 rounded-full bg-ai-accent" />
          <h1 className="text-[1.9rem] leading-[1.15] font-semibold tracking-tight text-balance">
            AI support that verifies before it answers.
          </h1>
          <p className="text-[15px] leading-relaxed text-muted-foreground">
            Relay uses your knowledge base and customer records to answer questions, verify
            identity in code, and escalate only the conversations that need a human.
          </p>
        </div>

        <FlowGraphic />

        <dl className="grid grid-cols-3 gap-4 border-t border-border pt-6">
          <Stat value="24/7" label="Always available" />
          <Stat value="<2s" label="Median first response" />
          <Stat value="100%" label="Grounded in your knowledge" />
        </dl>
      </div>

      <ul className="relative w-full space-y-2.5 text-xs text-muted-foreground">
        <li className="flex items-center gap-2.5">
          <Zap className="size-3.5 shrink-0 text-ai-accent" />
          Resolves routine customer inquiries automatically.
        </li>
        <li className="flex items-center gap-2.5">
          <Users className="size-3.5 shrink-0 text-ai-accent" />
          Escalates complex conversations with complete context.
        </li>
      </ul>
    </div>
  );
}

/** The shared page shell: near-full-viewport split card, theme switch pinned to its top-right
 * corner, pitch panel on the left (hidden on mobile), caller's form content on the right. */
export function AuthSplitShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative grid min-h-svh place-items-center bg-background p-3 text-foreground sm:p-6">
      <div className="relative grid min-h-[calc(100svh-1.5rem)] w-full max-w-7xl overflow-hidden rounded-3xl border border-border bg-card shadow-xl sm:min-h-[calc(100svh-3rem)] lg:grid-cols-2">
        <ThemeSwitch className="absolute right-5 top-5 z-20" />
        <BrandPanel />
        <div className="flex flex-col items-center justify-center px-6 py-10 sm:px-10 lg:px-14 lg:py-11">
          <BrandWordmark className="mb-6 lg:hidden" />
          <div className="w-full max-w-sm" style={{ animation: "cswfadein 0.4s ease-out both" }}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
