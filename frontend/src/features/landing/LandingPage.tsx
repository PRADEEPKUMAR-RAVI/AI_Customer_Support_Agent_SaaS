import { ArrowRight, CheckCircle2, Lock, MessageSquare, ShieldCheck, UserCheck, Waypoints } from "lucide-react";
import { Link, Navigate } from "react-router-dom";

import { homePathForRole } from "@/app/nav";
import { useAuth } from "@/app/providers";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const FEATURES = [
  {
    icon: ShieldCheck,
    title: "Grounded in your content",
    body: "Every answer is checked against your help center and records before it's sent — nothing above the relevance threshold gets through, so the AI never improvises.",
  },
  {
    icon: UserCheck,
    title: "Verified in code, not by the model",
    body: "Order numbers, warranties, account lookups — the match runs in your application logic. The AI can ask for the value; it never decides it's correct.",
  },
  {
    icon: Waypoints,
    title: "Relayed with full context",
    body: "What it can't resolve, it hands to your team with the complete transcript and a suggested reply attached — nothing repeated, nothing lost in the handoff.",
  },
];

// ── signature: the relay itself — a question closes the circuit only once it clears each gate ──

const STEPS = [
  { icon: MessageSquare, label: "Question", detail: "Comes in on any channel", glow: "bg-warning/25", ring: "border-warning/40 text-warning" },
  { icon: Lock, label: "Verified", detail: "Checked against your content", glow: "bg-blue-500/25", ring: "border-blue-500/40 text-blue-600 dark:text-blue-400" },
  { icon: CheckCircle2, label: "Resolved", detail: "Or relayed to your team", glow: "bg-success/25", ring: "border-success/40 text-success" },
] as const;

// Track color = the tone of the step being arrived at.
const STEP_TRACK = ["via-blue-500/70", "via-success/70"] as const;

function RelaySignature() {
  return (
    <div
      className="relative mx-auto mt-16 w-full max-w-3xl"
      style={{ animation: "cswfadein 0.5s 0.15s ease-out both" }}
    >
      <div className="rounded-2xl border border-border bg-card/60 p-8 shadow-sm backdrop-blur-sm sm:p-10">
        <div className="flex items-start justify-between">
          {STEPS.map((step, i) => (
            <div key={step.label} className="contents">
              <div className="flex w-28 flex-col items-center gap-3 text-center sm:w-36">
                <span className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground">
                  0{i + 1}
                </span>
                <div className="relative grid place-items-center">
                  <div aria-hidden className={cn("absolute size-11 rounded-full blur-md", step.glow)} />
                  <div
                    className={cn(
                      "relative grid size-14 place-items-center rounded-full border-2 bg-background",
                      step.ring
                    )}
                  >
                    <step.icon className="size-6" />
                  </div>
                </div>
                <div>
                  <p className="text-sm font-semibold tracking-tight">{step.label}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{step.detail}</p>
                </div>
              </div>
              {i < STEPS.length - 1 && (
                <div className="mt-7 flex-1 px-1 sm:px-2">
                  <div className="relative h-px overflow-hidden bg-border">
                    <span
                      aria-hidden
                      className={cn(
                        "absolute inset-y-0 w-12 -translate-x-1/2 bg-gradient-to-r from-transparent to-transparent",
                        STEP_TRACK[i]
                      )}
                      style={{ animation: `relay-flow 2.6s ${i * 0.3}s ease-in-out infinite` }}
                    />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <p className="mt-4 text-center text-xs text-muted-foreground">
        No step is skipped — a question only resolves once it's cleared the one before it.
      </p>
    </div>
  );
}

export function LandingPage() {
  const { authenticated, ready, role } = useAuth();

  // Already signed in? Skip the marketing page and go straight to the console home.
  if (ready && authenticated) return <Navigate to={homePathForRole(role)} replace />;

  return (
    <div className="relative min-h-svh overflow-hidden bg-background">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-48 left-1/2 size-[44rem] -translate-x-1/2 rounded-full bg-ai-accent/10 blur-3xl"
      />

      <header className="relative mx-auto flex h-16 w-full max-w-6xl items-center gap-3 px-4 md:px-8">
        <div className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
          <Waypoints className="size-4" />
        </div>
        <span className="text-lg font-semibold tracking-tight">Relay</span>
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          <Button variant="ghost" asChild>
            <Link to="/login">Sign in</Link>
          </Button>
          <Button asChild>
            <Link to="/signup">Get started</Link>
          </Button>
        </div>
      </header>

      <main className="relative mx-auto w-full max-w-6xl px-4 md:px-8">
        <section className="flex flex-col items-center pt-20 text-center md:pt-28">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 font-mono text-[11px] tracking-[0.14em] text-muted-foreground">
            <span className="size-1.5 rounded-full bg-ai-accent" />
            GROUNDED · VERIFIED · ESCALATED
          </div>
          <h1 className="max-w-3xl text-balance text-4xl font-semibold tracking-tight md:text-6xl">
            Every answer is checked before it's sent.
          </h1>
          <p className="mt-6 max-w-2xl text-pretty text-lg text-muted-foreground">
            Point Relay at your help content and customer records, embed a chat widget, and let it
            handle the conversation — answering only what it can verify, and looping in your team
            for the rest.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Button size="lg" asChild>
              <Link to="/signup">
                Create your account
                <ArrowRight className="size-4" />
              </Link>
            </Button>
            <Button size="lg" variant="outline" asChild>
              <Link to="/login">I already have an account</Link>
            </Button>
          </div>
        </section>

        <RelaySignature />

        <section className="grid gap-4 py-24 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="rounded-xl border border-border bg-card p-6 shadow-sm transition-colors hover:border-ai-accent/40"
            >
              <div className="mb-4 grid size-10 place-items-center rounded-lg bg-accent text-accent-foreground">
                <f.icon className="size-5" />
              </div>
              <h3 className="text-base font-semibold">{f.title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground">{f.body}</p>
            </div>
          ))}
        </section>
      </main>

      <footer className="relative mx-auto w-full max-w-6xl px-4 pb-10 text-sm text-muted-foreground md:px-8">
        <div className="border-t pt-6">Relay · AI customer support, wired to your own data.</div>
      </footer>
    </div>
  );
}
