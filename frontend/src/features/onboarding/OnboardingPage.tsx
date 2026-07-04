/** FE-Onboarding — the guided setup wizard: templates -> knowledge/records -> configure agent
 * -> embed snippet + preview. Industry itself is picked at signup (the backend's
 * `SignupRequest` already requires it), so there is no separate industry-pick step here.
 *
 * Full server-derived resumability (the plan's "resumable wizard" note) needs
 * `GET /knowledge/sources` and `GET /records/datasets`, which don't exist yet (person-2's
 * M3/M4) — until then this is a free-navigation tab strip rather than a strictly gated stepper.
 */

import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Spinner } from "../../components";
import { getAccessToken } from "../../lib/auth";
import { api, unwrap } from "../../lib/api";
import { RECORD_TYPES_BY_INDUSTRY } from "./recordTypes";

type StepKey = "templates" | "data" | "configure" | "embed";

const STEPS: { key: StepKey; label: string }[] = [
  { key: "templates", label: "1. Templates" },
  { key: "data", label: "2. Knowledge & records" },
  { key: "configure", label: "3. Configure agent" },
  { key: "embed", label: "4. Embed & preview" },
];

interface Tenant {
  name: string;
  industry: string;
  status: string;
}

interface Settings {
  config: {
    persona?: string;
    welcome_message?: string;
    default_language?: string;
    active_triggers?: string[];
    sensitive_intent_list?: string[];
    sla_followup_text?: string;
    // `relevance_threshold` also lives in this config blob but is person-2's field (RAG
    // calibration) — deliberately not read or rendered by this form.
    [key: string]: unknown;
  };
}

// Mirrors `app/domain/escalation/reasons.py::EscalationReason` for display only — the backend
// is the source of truth and validates independently of what this checklist shows.
const ESCALATION_TRIGGERS = [
  { value: "no_grounding", label: "No grounded answer found" },
  { value: "explicit", label: "Customer explicitly asks for a human" },
  { value: "sensitive", label: "Sensitive-intent keyword match" },
  { value: "dispute", label: "Deterministic record-state dispute" },
  { value: "n_fails", label: "Repeated verification failures" },
  { value: "proactive", label: "Customer accepts a proactive human offer" },
  { value: "timeout", label: "Per-turn timeout" },
];

interface EmbedSnippet {
  widget_key: string;
  snippet: string;
}

function useTenant() {
  return useQuery({
    queryKey: ["tenant"],
    queryFn: async () => unwrap<Tenant>(await api.GET("/api/v1/admin/tenant")),
  });
}

async function downloadTemplate(recordType: string): Promise<void> {
  const token = getAccessToken();
  const res = await fetch(`/api/v1/records/templates/${recordType}?format=csv`, {
    headers: token ? { authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${recordType}_template.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function TemplatesStep({ industry }: { industry: string }) {
  const recordTypes = RECORD_TYPES_BY_INDUSTRY[industry] ?? [];
  return (
    <div>
      <p>
        Download a template for each record type your industry supports, fill it in with your
        own customer data, and upload it in the next step.
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {recordTypes.map((rt) => (
          <Button key={rt} variant="ghost" onClick={() => void downloadTemplate(rt)}>
            Download {rt} template (CSV)
          </Button>
        ))}
      </div>
    </div>
  );
}

function DataStep() {
  return (
    <div>
      <p>
        Upload your knowledge base (docs/FAQs/URLs) and the customer-record datasets you filled
        in from the templates above.
      </p>
      <p style={{ color: "#6b7280" }}>
        This step mounts the Knowledge and Records upload screens once those modules ship — the
        upload endpoints (<code>/knowledge/sources</code>, <code>/records/datasets</code>) aren't
        built yet. Come back once they land, or skip ahead and configure your agent now.
      </p>
    </div>
  );
}

function ConfigureStep() {
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState(false);
  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: async () => unwrap<Settings>(await api.GET("/api/v1/admin/settings")),
  });

  const patch = useMutation({
    mutationFn: async (config: Record<string, unknown>) =>
      unwrap(await api.PATCH("/api/v1/admin/settings", { body: { config } })),
    onSuccess: () => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setSaved(false);
    const triggers = ESCALATION_TRIGGERS.filter(
      (t) => (form.elements.namedItem(`trigger_${t.value}`) as HTMLInputElement).checked
    ).map((t) => t.value);
    const sensitiveIntentRaw = (
      form.elements.namedItem("sensitive_intent_list") as HTMLInputElement
    ).value;
    patch.mutate({
      persona: (form.elements.namedItem("persona") as HTMLTextAreaElement).value,
      welcome_message: (form.elements.namedItem("welcome_message") as HTMLInputElement).value,
      default_language: (form.elements.namedItem("default_language") as HTMLSelectElement).value,
      active_triggers: triggers,
      sensitive_intent_list: sensitiveIntentRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      sla_followup_text: (form.elements.namedItem("sla_followup_text") as HTMLInputElement).value,
    });
  }

  if (isLoading) return <Spinner />;

  const activeTriggers = settings?.config.active_triggers ?? ESCALATION_TRIGGERS.map((t) => t.value);

  return (
    <form onSubmit={handleSubmit} style={{ display: "grid", gap: 10, maxWidth: 480 }}>
      <label>
        Persona
        <textarea
          name="persona"
          defaultValue={settings?.config.persona ?? ""}
          rows={3}
          style={{ width: "100%" }}
        />
      </label>
      <label>
        Welcome message
        <input
          name="welcome_message"
          defaultValue={settings?.config.welcome_message ?? ""}
          style={{ width: "100%" }}
        />
      </label>
      <label>
        Default language
        <select name="default_language" defaultValue={settings?.config.default_language ?? "en"}>
          <option value="en">English</option>
          <option value="es">Spanish</option>
          <option value="fr">French</option>
          <option value="de">German</option>
          <option value="hi">Hindi</option>
        </select>
      </label>

      <h4 style={{ marginBottom: 0 }}>Escalation (M6)</h4>
      <fieldset style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 10 }}>
        <legend style={{ fontSize: 13, color: "#6b7280" }}>Active hand-off triggers</legend>
        {ESCALATION_TRIGGERS.map((t) => (
          <label key={t.value} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 14 }}>
            <input
              type="checkbox"
              name={`trigger_${t.value}`}
              defaultChecked={activeTriggers.includes(t.value)}
            />
            {t.label}
          </label>
        ))}
      </fieldset>
      <label>
        Sensitive-intent keywords (comma-separated)
        <input
          name="sensitive_intent_list"
          defaultValue={(settings?.config.sensitive_intent_list ?? []).join(", ")}
          style={{ width: "100%" }}
        />
      </label>
      <label>
        After-hours SLA promise shown to customers
        <input
          name="sla_followup_text"
          defaultValue={settings?.config.sla_followup_text ?? ""}
          style={{ width: "100%" }}
        />
      </label>
      <p style={{ fontSize: 12, color: "#6b7280", marginTop: -6 }}>
        The relevance-threshold (RAG grounding) field lives here too but is person-2's — it
        isn't shown on this form.
      </p>

      <Button type="submit" disabled={patch.isPending}>
        {patch.isPending ? "Saving…" : "Save configuration"}
      </Button>
      {saved && <p style={{ color: "#16a34a" }}>Saved.</p>}
    </form>
  );
}

function EmbedStep() {
  const { data: snippet, isLoading } = useQuery({
    queryKey: ["embed-snippet"],
    queryFn: async () => unwrap<EmbedSnippet>(await api.GET("/api/v1/admin/embed-snippet")),
  });

  if (isLoading) return <Spinner />;
  if (!snippet) return <p>Configure your agent first, then come back for the embed snippet.</p>;

  return (
    <div>
      <p>Paste this snippet before the closing <code>&lt;/body&gt;</code> tag on your site:</p>
      <pre style={{ background: "#111827", color: "#e5e7eb", padding: 12, borderRadius: 8, overflowX: "auto" }}>
        {snippet.snippet}
      </pre>
      <Button variant="ghost" onClick={() => void navigator.clipboard.writeText(snippet.snippet)}>
        Copy snippet
      </Button>

      <h4 style={{ marginTop: 16 }}>Embedding requirements ([IMP-FE-3])</h4>
      <p>If your site enforces a strict Content-Security-Policy, add:</p>
      <pre style={{ background: "#f3f4f6", padding: 12, borderRadius: 8, overflowX: "auto" }}>
{`script-src <widget-origin>;
connect-src <api-origin>;
img-src data:;`}
      </pre>

      <h4 style={{ marginTop: 16 }}>Live preview</h4>
      <p style={{ color: "#6b7280" }}>
        The live widget preview mounts chat-core directly once that shared component ships
        (person-1's FE-Chat) — this snippet and the embed requirements above are already final.
      </p>
    </div>
  );
}

export function OnboardingPage() {
  const [step, setStep] = useState<StepKey>("templates");
  const { data: tenant, isLoading, isError } = useTenant();

  if (isLoading) return <Spinner />;
  if (isError || !tenant)
    return (
      <Card>
        <p role="alert" style={{ color: "#dc2626" }}>
          Failed to load your workspace.
        </p>
      </Card>
    );

  return (
    <Card>
      <h2>Set up {tenant.name}</h2>
      <nav style={{ display: "flex", gap: 8, marginBottom: 16, borderBottom: "1px solid #e5e7eb" }}>
        {STEPS.map((s) => (
          <button
            key={s.key}
            onClick={() => setStep(s.key)}
            style={{
              padding: "8px 10px",
              border: "none",
              background: "transparent",
              borderBottom: step === s.key ? "2px solid #2563eb" : "2px solid transparent",
              fontWeight: step === s.key ? 600 : 400,
              cursor: "pointer",
            }}
          >
            {s.label}
          </button>
        ))}
      </nav>
      {step === "templates" && <TemplatesStep industry={tenant.industry} />}
      {step === "data" && <DataStep />}
      {step === "configure" && <ConfigureStep />}
      {step === "embed" && <EmbedStep />}
    </Card>
  );
}
