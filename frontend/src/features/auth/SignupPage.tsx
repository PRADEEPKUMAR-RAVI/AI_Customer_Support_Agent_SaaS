/** FE-Auth — `/signup`. A full-bleed split layout (not the shared centered `AuthLayout` column):
 * a permanently-dark brand rail on the left carries the pitch, a light form panel on the right
 * carries the work. Company name + email + password + industry pick in one step for a business
 * signing up to embed an AI support agent: the backend's `SignupRequest` already requires an
 * industry (it provisions the record schema + default agent_settings atomically), so there is no
 * separate "pick an industry" screen for the walking skeleton — this form *is* the Phase-1
 * "industry pick". */

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import {
  CheckCircle2,
  MailCheck,
  MessageSquare,
  MessagesSquare,
  Search,
  Users,
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

// ── brand rail (desktop only) ────────────────────────────────────────────────────────────────

function BrandMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm",
        className
      )}
    >
      <MessagesSquare className="size-4" />
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <p className="font-mono text-lg font-semibold tabular-nums text-white">{value}</p>
      <p className="mt-1 text-[11px] text-white/45">{label}</p>
    </div>
  );
}

const FLOW_TONE = {
  neutral: { ring: "border-white/15 bg-white/5 text-white/70", track: "via-white/40" },
  resolved: { ring: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300", track: "via-emerald-400" },
} as const;

/** Soft halo behind each step's icon — independent of the ring/border tone above, so all three
 * steps can carry their own glow without reintroducing flat, saturated per-step colors. */
const GLOW_TONE = {
  neutral: "bg-white/20",
  checking: "bg-brand-500/50",
  resolved: "bg-emerald-400/50",
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
    <div className="flex w-16 flex-col items-center gap-2 text-center">
      <div className="relative grid place-items-center">
        <div aria-hidden className={cn("absolute size-7 rounded-full blur-md", GLOW_TONE[glow])} />
        <div
          className={cn(
            "relative grid size-9 place-items-center rounded-full border",
            FLOW_TONE[tone].ring
          )}
        >
          <Icon className="size-4" />
        </div>
      </div>
      <span className="text-[10px] leading-tight font-medium text-white/50">{label}</span>
    </div>
  );
}

function FlowTrack({ tone }: { tone: keyof typeof FLOW_TONE }) {
  return (
    <div className="flex-1 pt-[18px]">
      <div className="relative h-px overflow-hidden bg-white/10">
        <span
          aria-hidden
          className={cn(
            "absolute inset-y-0 w-10 -translate-x-1/2 bg-gradient-to-r from-transparent to-transparent",
            FLOW_TONE[tone].track
          )}
          style={{ animation: "helm-flow 2.4s ease-in-out infinite" }}
        />
      </div>
    </div>
  );
}

/** Signature element: how a real turn resolves. A customer asks, Helm checks the question
 * against your content before answering, and the turn lands resolved. Every step stays the same
 * light tone against the dark rail; only the final, resolved state gets its own color, since
 * that's the one true status signal here. See CLAUDE.md non-negotiable #3 for the actual gate
 * this mirrors. */
function FlowGraphic() {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.04] p-4">
      <div className="flex items-start">
        <FlowStep icon={MessageSquare} label="Question" tone="neutral" glow="neutral" />
        <FlowTrack tone="neutral" />
        <FlowStep icon={Search} label="Checked" tone="neutral" glow="checking" />
        <FlowTrack tone="resolved" />
        <FlowStep icon={CheckCircle2} label="Resolved" tone="resolved" glow="resolved" />
      </div>
    </div>
  );
}

function BrandPanel() {
  return (
    <div className="relative hidden flex-col justify-between overflow-hidden bg-slate-950 px-12 py-12 text-white lg:flex">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.15]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.4) 1px, transparent 0)",
          backgroundSize: "24px 24px",
        }}
      />

      <Link to="/" className="relative flex items-center gap-2.5">
        <BrandMark />
        <span className="text-sm font-semibold tracking-tight">Helm</span>
      </Link>

      <div className="relative max-w-md space-y-5">
        <h1 className="text-2xl leading-[1.15] font-semibold tracking-tight text-balance">
          AI support that resolves customer conversations.
        </h1>
        <p className="text-sm leading-relaxed text-white/70">
          Helm uses your knowledge base and customer data to answer questions, verify responses,
          and escalate only the conversations that require human attention.
        </p>

        <FlowGraphic />

        <dl className="grid grid-cols-3 gap-6 border-t border-white/10 pt-5">
          <Stat value="24/7" label="Always available" />
          <Stat value="<2s" label="Median first response" />
          <Stat value="100%" label="Grounded in your knowledge" />
        </dl>
      </div>

      <ul className="relative space-y-2.5 text-xs text-white/70">
        <li className="flex items-center gap-2.5">
          <Zap className="size-3.5 shrink-0 text-white/70" />
          Resolves routine customer inquiries automatically.
        </li>
        <li className="flex items-center gap-2.5">
          <Users className="size-3.5 shrink-0 text-white/70" />
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
    <div className="grid min-h-svh bg-background lg:grid-cols-2">
      <BrandPanel />

      <div className="relative flex flex-col overflow-hidden px-6 py-8 sm:px-10 lg:px-16 lg:py-14">
        <div
          aria-hidden
          className="pointer-events-none absolute -top-32 -right-32 size-96 rounded-full bg-brand-500/15 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-40 -left-24 size-96 rounded-full bg-brand-700/10 blur-3xl"
        />

        <div className="relative flex items-center lg:justify-end">
          <Link to="/" className="flex items-center gap-2.5 lg:hidden">
            <BrandMark />
            <span className="text-sm font-semibold tracking-tight">Helm</span>
          </Link>
        </div>

        <div className="relative flex flex-1 items-center">
          <div className="mx-auto w-full max-w-sm" style={{ animation: "cswfadein 0.4s ease-out both" }}>
            {sentTo ? (
              <div className="space-y-6">
                <div className="grid size-11 place-items-center rounded-full bg-primary/10 text-primary">
                  <MailCheck className="size-5" />
                </div>
                <div className="space-y-2">
                  <h1 className="text-lg font-semibold tracking-tight">Check Your Email</h1>
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
                  <h1 className="text-lg font-semibold tracking-tight">Create Your Account</h1>
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
                              placeholder="Acme Inc."
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
                      className="w-full shadow-lg shadow-brand-900/20"
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
