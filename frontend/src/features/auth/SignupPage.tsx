/** FE-Auth — `/signup`. A single centered split card (not the shared centered `AuthLayout`
 * column): the pitch sits on the left on a softly tinted panel, the form on the right on the
 * card surface — separated by a background shift, not a hairline. Company name + email +
 * password + industry pick in one step for a business signing up to embed an AI support agent:
 * the backend's `SignupRequest` already requires an industry (it provisions the record schema +
 * default agent_settings atomically), so there is no separate "pick an industry" screen for the
 * walking skeleton — this form *is* the Phase-1 "industry pick".
 *
 * Follows the app's normal light/dark theme (the `.dark` class on `<html>`) via the standard
 * semantic tokens — no pinned palette — with its own compact sun/moon switch since this page has
 * no top bar of its own. */

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import {
  CheckCircle2,
  Lock,
  MailCheck,
  MessageSquare,
  Moon,
  Sun,
  Users,
  Waypoints,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTheme } from "@/lib/useTheme";
import { cn } from "@/lib/utils";

import { signup, type Industry } from "../../lib/auth";

const INDUSTRIES: { value: Industry; label: string }[] = [
  { value: "retail", label: "Retail / E-commerce" },
  { value: "logistics", label: "Logistics / Courier" },
  { value: "telecom", label: "Telecom / ISP" },
  { value: "healthcare", label: "Healthcare / Clinic" },
  { value: "travel", label: "Travel / Hospitality" },
];

const signupSchema = z.object({
  company_name: z.string().min(1, "Company is required"),
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(8, "Use at least 8 characters"),
  industry: z.enum(["retail", "logistics", "telecom", "healthcare", "travel"]),
});

type SignupValues = z.infer<typeof signupSchema>;

// ── theme switch — a compact two-state track with both icons always visible ────────────────────

function ThemeSwitch({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={() => setTheme(dark ? "light" : "dark")}
      className={cn(
        "relative inline-flex h-8 w-[3.75rem] shrink-0 items-center rounded-full border border-border bg-card shadow-md transition-colors",
        className
      )}
    >
      <Sun className="absolute left-1.5 size-4 text-muted-foreground" />
      <Moon className="absolute right-1.5 size-4 text-muted-foreground" />
      <span
        className={cn(
          "absolute left-0.5 grid size-7 place-items-center rounded-full bg-primary text-primary-foreground shadow-sm transition-transform duration-200",
          dark && "translate-x-[1.75rem]"
        )}
      >
        {dark ? <Moon className="size-3.5" /> : <Sun className="size-3.5" />}
      </span>
    </button>
  );
}

// ── brand rail (desktop only) ────────────────────────────────────────────────────────────────

function BrandMark({ className }: { className?: string }) {
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

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <p className="font-mono text-xl font-semibold tabular-nums text-foreground">{value}</p>
      <p className="mt-1 text-[11px] text-muted-foreground">{label}</p>
    </div>
  );
}

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
function FlowGraphic() {
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

function BrandPanel() {
  return (
    <div className="relative hidden flex-col justify-between bg-gradient-to-br from-secondary/70 to-secondary/25 px-10 py-10 lg:flex lg:px-11 lg:py-11">
      <Link to="/" className="relative flex items-center gap-2.5">
        <BrandMark />
        <span className="text-sm font-semibold tracking-tight">Relay</span>
      </Link>

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

// ── page ─────────────────────────────────────────────────────────────────────────────────────

export function SignupPage() {
  const [sentTo, setSentTo] = useState<string | null>(null);

  const form = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: {
      company_name: "",
      email: "",
      password: "",
      industry: "retail",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: SignupValues) => signup(values),
    onSuccess: (_data, values) => setSentTo(values.email),
    onError: (err) =>
      toast.error("Couldn't create account", {
        description: err instanceof Error ? err.message : "Please try again.",
      }),
  });

  return (
    <div className="relative grid min-h-svh place-items-center bg-background p-3 text-foreground sm:p-6">
      <div className="relative grid min-h-[calc(100svh-1.5rem)] w-full max-w-7xl overflow-hidden rounded-3xl border border-border bg-card shadow-xl sm:min-h-[calc(100svh-3rem)] lg:grid-cols-2">
        <ThemeSwitch className="absolute right-5 top-5 z-20" />

        <BrandPanel />

        <div className="flex flex-col items-center justify-center px-6 py-10 sm:px-10 lg:px-14 lg:py-11">
          <Link to="/" className="mb-6 flex items-center gap-2.5 lg:hidden">
            <BrandMark />
            <span className="text-sm font-semibold tracking-tight">Relay</span>
          </Link>

          <div
            className="w-full max-w-sm"
            style={{ animation: "cswfadein 0.4s ease-out both" }}
          >
            {sentTo ? (
              <div className="space-y-6">
                <div className="grid size-11 place-items-center rounded-full bg-primary/10 text-primary">
                  <MailCheck className="size-5" />
                </div>
                <div className="space-y-2">
                  <h1 className="text-xl font-semibold tracking-tight">Check Your Email</h1>
                  <p className="text-xs text-muted-foreground">
                    We sent a verification link to{" "}
                    <span className="font-medium text-foreground">{sentTo}</span>. Follow it to
                    activate your account.
                  </p>
                </div>
                <div className="space-y-3">
                  <Button asChild className="w-full">
                    <Link to="/login">Back to sign in</Link>
                  </Button>
                  <p className="text-center text-xs text-muted-foreground">
                    Didn&apos;t get it? Check your spam folder or try signing up again.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                <div className="space-y-1.5">
                  <h1 className="text-xl font-semibold tracking-tight">Create Your Account</h1>
                  <p className="text-xs text-muted-foreground">
                    Set up your AI support agent to deliver fast, accurate customer support around
                    the clock.
                  </p>
                </div>

                <Form {...form}>
                  <form
                    onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
                    className="space-y-4"
                  >
                    <FormField
                      control={form.control}
                      name="company_name"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs">Company</FormLabel>
                          <FormControl>
                            <Input
                              placeholder="Soft Suave"
                              autoComplete="organization"
                              className="text-sm"
                              {...field}
                            />
                          </FormControl>
                          <FormDescription className="text-[11px]">
                            The organization your AI support agent represents in customer
                            conversations.
                          </FormDescription>
                          <FormMessage className="text-xs" />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="email"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs">Work email</FormLabel>
                          <FormControl>
                            <Input
                              type="email"
                              placeholder="you@company.com"
                              autoComplete="email"
                              className="text-sm"
                              {...field}
                            />
                          </FormControl>
                          <FormMessage className="text-xs" />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="password"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs">Password</FormLabel>
                          <FormControl>
                            <Input
                              type="password"
                              placeholder="At least 8 characters"
                              autoComplete="new-password"
                              className="text-sm"
                              {...field}
                            />
                          </FormControl>
                          <FormMessage className="text-xs" />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="industry"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs">Industry</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger className="w-full text-sm">
                                <SelectValue placeholder="Select your industry" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {INDUSTRIES.map((i) => (
                                <SelectItem key={i.value} value={i.value}>
                                  {i.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <FormDescription className="text-[11px]">
                            Tailors your agent to your industry&apos;s records, terminology, and
                            workflows.
                          </FormDescription>
                          <FormMessage className="text-xs" />
                        </FormItem>
                      )}
                    />

                    <Button
                      type="submit"
                      size="lg"
                      className="w-full shadow-lg shadow-brand-900/20 transition-shadow hover:shadow-xl hover:shadow-brand-900/25"
                      disabled={mutation.isPending}
                    >
                      {mutation.isPending ? "Creating…" : "Create Account"}
                    </Button>
                  </form>
                </Form>

                <p className="text-center text-xs text-muted-foreground">
                  Already have an account?{" "}
                  <Link to="/login" className="font-medium text-foreground hover:text-primary">
                    Sign in
                  </Link>
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
