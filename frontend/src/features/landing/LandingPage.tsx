import { ArrowRight, Handshake, MessagesSquare, ShieldCheck, Sparkles } from "lucide-react";
import { Link, Navigate } from "react-router-dom";

import { homePathForRole } from "@/app/nav";
import { useAuth } from "@/app/providers";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

const FEATURES = [
  {
    icon: Sparkles,
    title: "Answers backed by your content",
    body: "The AI answers only from your help content and customer records, with citations, so it never makes things up.",
  },
  {
    icon: Handshake,
    title: "Human handoff",
    body: "When it can't help, it escalates to your team with the full transcript and a suggested reply, so nothing falls through the cracks.",
  },
  {
    icon: ShieldCheck,
    title: "Private by design",
    body: "Every business's data and conversations are kept completely separate, so nothing ever crosses between customers.",
  },
];

export function LandingPage() {
  const { authenticated, ready, role } = useAuth();

  // Already signed in? Skip the marketing page and go straight to the console home.
  if (ready && authenticated) return <Navigate to={homePathForRole(role)} replace />;

  return (
    <div className="relative min-h-svh overflow-hidden bg-background">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-48 left-1/2 size-[40rem] -translate-x-1/2 rounded-full bg-brand-500/10 blur-3xl"
      />

      <header className="relative mx-auto flex h-16 w-full max-w-6xl items-center gap-3 px-4 md:px-8">
        <div className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
          <MessagesSquare className="size-4" />
        </div>
        <span className="text-lg font-semibold tracking-tight">Helm</span>
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
        <section className="flex flex-col items-center py-20 text-center md:py-28">
          <h1 className="max-w-3xl text-balance text-4xl font-semibold tracking-tight md:text-6xl">
            Resolve every customer question, around the clock.
          </h1>
          <p className="mt-6 max-w-2xl text-pretty text-lg text-muted-foreground">
            Point the AI at your help content and customer records, embed a chat widget, and let it
            handle the conversation: answering what it can, and looping in your team for the rest.
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

        <section className="grid gap-4 pb-24 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-xl border bg-card p-6 shadow-sm">
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
        <div className="border-t pt-6">Helm · AI customer support for every conversation.</div>
      </footer>
    </div>
  );
}
