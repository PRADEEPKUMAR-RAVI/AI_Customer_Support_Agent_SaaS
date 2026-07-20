import { Building2, Code2, FileText, Globe, MessageSquare, Upload, Users, type LucideIcon } from "lucide-react";

/** Shared between `OnboardingPage.tsx` (renders the active step's content) and `app-sidebar.tsx`
 * (renders the step list itself, replacing the normal console nav while setup is incomplete —
 * see `useOnboardingProgress.ts` for why the sidebar needs the same step metadata). */
export type StepKey =
  | "industry"
  | "templates"
  | "knowledge"
  | "records"
  | "config"
  | "domains"
  | "staff"
  | "embed";

export interface OnboardingStep {
  key: StepKey;
  label: string;
  hint: string;
  description: string;
  icon: LucideIcon;
  /** Steps the wizard lets you move past without completing them: a tenant can whitelist embed
   * origins and invite teammates later from the console, and neither is part of the server-side
   * `completed` check (`app/api/v1/onboarding.py`). The step's own `done` signal — and its sidebar
   * checkmark — still reflects whether the work was actually done; this only ungates "Next". */
  optional?: boolean;
}

export const STEPS: OnboardingStep[] = [
  {
    key: "industry",
    label: "Industry",
    hint: "Your vertical",
    description: "Select your industry to customize your AI agent for your business.",
    icon: Building2,
  },
  {
    key: "templates",
    label: "Record templates",
    hint: "Download CSVs",
    description: "Download a CSV template for each record type, fill it with your own customer data, then upload it in the Customer records step.",
    icon: FileText,
  },
  {
    key: "knowledge",
    label: "Knowledge base",
    hint: "Docs, FAQs & URLs",
    description: "Add the documents, FAQs, and pages the agent should ground its answers in. Sources are chunked and indexed after upload.",
    icon: MessageSquare,
  },
  {
    key: "records",
    label: "Customer records",
    hint: "Upload datasets",
    description: "Upload the filled-in templates so the agent can look up and verify orders, shipments, appointments and more.",
    icon: Upload,
  },
  {
    key: "config",
    label: "Agent configuration",
    hint: "Persona & escalation",
    description: "Set your agent's voice, greeting, language, and the triggers that hand a conversation to a human.",
    icon: MessageSquare,
  },
  {
    key: "domains",
    label: "Allowed domains",
    hint: "Where it runs",
    description: "Whitelist the sites permitted to embed your chat widget. Requests from other origins are refused.",
    icon: Globe,
    optional: true,
  },
  {
    key: "staff",
    label: "Invite your team",
    hint: "Agents & admins",
    description: "Invite teammates who will handle escalated conversations or manage the account.",
    icon: Users,
    optional: true,
  },
  {
    key: "embed",
    label: "Embed the widget",
    hint: "Go live",
    description: "Drop the snippet onto your site and you're live. Copy it, add the CSP rules if you enforce one, and ship.",
    icon: Code2,
  },
];
