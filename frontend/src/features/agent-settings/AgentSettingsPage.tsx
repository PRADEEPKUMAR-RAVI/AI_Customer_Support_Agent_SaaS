/** FE-AgentSettings: the tenant's agent configuration form + the pending-tag approval tray.
 *
 * Two independent backends with different write semantics (see ./api.ts):
 *   • the config FORM is a single bulk PATCH /admin/settings (M1);
 *   • the tag TRAY is per-item POST /admin/tags/{id}/approve|reject (M5), with optimistic per-row
 *     actions that must NEVER ride on the form save.
 * The relevance-threshold control is GUARDED ([IMP-RAG-1]) — it's a code-enforced non-negotiable
 * input, so we expose a coarse strict/balanced/lenient dial (never a raw number field) mapped to the
 * eval-calibrated bands, with an explicit "eval default" for the per-tenant calibrated cutoff.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ShieldAlert, Tags, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/app/providers";
import { DataTable } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { hasPermission } from "@/lib/rbac";

import {
  approveTag,
  getAgentSettings,
  listPendingTags,
  rejectTag,
  updateAgentSettings,
  type AgentSettings,
  type TagApprovalResponse,
} from "./api";

const SETTINGS_KEY = ["agent-settings", "config"] as const;
const PENDING_TAGS_KEY = ["agent-settings", "pending-tags"] as const;

// Escalation triggers ([C6] canonical enum, owned by M2/P3 domain/escalation).
const TRIGGERS: { value: string; label: string; hint: string }[] = [
  { value: "no_grounding", label: "No grounding", hint: "Retrieval missed the knowledge gate" },
  { value: "explicit", label: "Explicit request", hint: "Customer asks for a human" },
  { value: "sensitive", label: "Sensitive intent", hint: "Matches the sensitive-intent list" },
  { value: "dispute", label: "Dispute", hint: "Refund / warranty / delivery dispute" },
  { value: "n_fails", label: "Repeated failures", hint: "Too many failed verification attempts" },
  { value: "proactive", label: "Proactive", hint: "AI judges it should hand off" },
  { value: "timeout", label: "Timeout", hint: "After-hours or per-turn timeout" },
];

// Threshold guard bands (bge-reranker-v2-m3 score scale; re-tune if the reranker changes).
const THRESHOLD_OPTIONS: { key: string; label: string; value: number | null; hint: string }[] = [
  {
    key: "default",
    label: "Eval default (calibrated)",
    value: null,
    hint: "Use the per-tenant cutoff calibrated on a labelled eval set. Recommended.",
  },
  {
    key: "lenient",
    label: "Lenient",
    value: 0.5,
    hint: "Answers more often — higher coverage, higher risk of ungrounded replies.",
  },
  {
    key: "balanced",
    label: "Balanced",
    value: 1.0,
    hint: "A middle cutoff for the top-1 rerank score.",
  },
  {
    key: "strict",
    label: "Strict",
    value: 1.5,
    hint: "Answers only on strong matches — safest, but refuses more borderline questions.",
  },
];

const thresholdKeyFor = (value: number | null): string =>
  value === null ? "default" : (THRESHOLD_OPTIONS.find((o) => o.value === value)?.key ?? "custom");

/** Chip-based editor for a string list (languages, sensitive intents, allowed tags). */
function StringListEditor({
  id,
  values,
  onChange,
  placeholder,
  emptyLabel = "None yet.",
}: {
  id: string;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  emptyLabel?: string;
}) {
  const [draft, setDraft] = useState("");
  const list = values ?? [];

  const add = () => {
    const v = draft.trim();
    if (v && !list.includes(v)) onChange([...list, v]);
    setDraft("");
  };
  const remove = (v: string) => onChange(list.filter((x) => x !== v));

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap gap-1.5">
        {list.length === 0 ? (
          <span className="text-sm text-muted-foreground">{emptyLabel}</span>
        ) : (
          list.map((v) => (
            <Badge key={v} variant="secondary" className="gap-1 py-1 pr-1 pl-2.5 font-normal">
              {v}
              <button
                type="button"
                aria-label={`Remove ${v}`}
                onClick={() => remove(v)}
                className="grid size-4 place-items-center rounded-sm text-muted-foreground transition-colors hover:bg-background hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))
        )}
      </div>
      <div className="flex gap-2">
        <Input
          id={id}
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" variant="outline" onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}

/** A number field with a trailing unit and tabular figures. */
function NumberField({
  id,
  label,
  value,
  onChange,
  unit,
  min = 0,
  step = 1,
  hint,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (n: number) => void;
  unit?: string;
  min?: number;
  step?: number;
  hint?: string;
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          min={min}
          step={step}
          value={Number.isFinite(value) ? value : 0}
          onChange={(e) => onChange(Number(e.target.value))}
          className="max-w-36 tabular-nums"
        />
        {unit ? <span className="text-sm text-muted-foreground">{unit}</span> : null}
      </div>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/** Per-row optimistic Approve/Reject tray — deliberately independent of the settings form save. */
function PendingTagsTray() {
  const qc = useQueryClient();
  const tagsQ = useQuery({
    queryKey: PENDING_TAGS_KEY,
    queryFn: listPendingTags,
  });

  const optsFor = (fn: (id: string) => Promise<TagApprovalResponse>, verb: string) => ({
    mutationFn: fn,
    onMutate: async (id: string) => {
      await qc.cancelQueries({ queryKey: PENDING_TAGS_KEY });
      const prev = qc.getQueryData<TagApprovalResponse[]>(PENDING_TAGS_KEY);
      qc.setQueryData<TagApprovalResponse[]>(PENDING_TAGS_KEY, (t) =>
        (t ?? []).filter((x) => x.id !== id)
      );
      return { prev };
    },
    onError: (_e: unknown, _id: string, ctx: { prev?: TagApprovalResponse[] } | undefined) => {
      if (ctx?.prev) qc.setQueryData(PENDING_TAGS_KEY, ctx.prev);
      toast.error(`Could not ${verb} tag`, {
        description: _e instanceof Error ? _e.message : undefined,
      });
    },
    onSuccess: () => toast.success(`Tag ${verb}d`),
    onSettled: () => void qc.invalidateQueries({ queryKey: PENDING_TAGS_KEY }),
  });

  const approve = useMutation(optsFor(approveTag, "approve"));
  const reject = useMutation(optsFor(rejectTag, "reject"));

  const columns = useMemo<ColumnDef<TagApprovalResponse>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Tag",
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge value={row.original.status} />,
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        cell: ({ row }) => (
          <div className="flex justify-end gap-2">
            <Button size="sm" onClick={() => approve.mutate(row.original.id)}>
              Approve
            </Button>
            <Button size="sm" variant="outline" onClick={() => reject.mutate(row.original.id)}>
              Reject
            </Button>
          </div>
        ),
      },
    ],
    [approve, reject]
  );

  return (
    <DataTable
      columns={columns}
      data={tagsQ.data ?? []}
      loading={tagsQ.isLoading}
      error={tagsQ.isError}
      onRetry={() => void tagsQ.refetch()}
      empty={
        <EmptyState
          icon={Tags}
          title="No tags awaiting approval"
          description="When the AI proposes a new conversation tag, it lands here for a human to approve before it can be applied."
        />
      }
    />
  );
}

function SettingsForm({ initial }: { initial: AgentSettings }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<AgentSettings>(initial);
  useEffect(() => setForm(initial), [initial]);

  const set = <K extends keyof AgentSettings>(k: K, v: AgentSettings[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(initial), [form, initial]);

  const save = useMutation({
    mutationFn: () => updateAgentSettings(form),
    onSuccess: (saved) => {
      qc.setQueryData(SETTINGS_KEY, saved);
      toast.success("Settings saved");
    },
    onError: (err: unknown) =>
      toast.error("Save failed", {
        description: err instanceof Error ? err.message : undefined,
      }),
  });

  const languages = form.supported_languages ?? [];
  const triggers = form.active_triggers ?? [];
  const thresholdKey = thresholdKeyFor(form.relevance_threshold);
  const activeThreshold = THRESHOLD_OPTIONS.find((o) => o.key === thresholdKey);

  const toggleTrigger = (value: string, on: boolean) =>
    set("active_triggers", on ? [...triggers, value] : triggers.filter((x) => x !== value));

  return (
    <div className="space-y-6">
      {/* Persona & tone */}
      <Card>
        <CardHeader>
          <CardTitle>Persona &amp; tone</CardTitle>
          <CardDescription>
            How the assistant introduces itself and the voice it answers in.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <div className="grid gap-2">
            <Label htmlFor="persona">Persona</Label>
            <Textarea
              id="persona"
              rows={3}
              value={form.persona ?? ""}
              onChange={(e) => set("persona", e.target.value)}
              placeholder="A helpful, concise customer-support assistant."
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="welcome">Welcome message</Label>
            <Input
              id="welcome"
              value={form.welcome_message ?? ""}
              onChange={(e) => set("welcome_message", e.target.value)}
              placeholder="Hi! How can I help you today?"
            />
          </div>
          <Separator />
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Label htmlFor="autonomy">Autonomy</Label>
              <p className="text-sm text-muted-foreground">
                Let the AI answer customers without a human in the loop.
              </p>
            </div>
            <Switch
              id="autonomy"
              checked={!!form.autonomy_enabled}
              onCheckedChange={(c) => set("autonomy_enabled", c)}
            />
          </div>
        </CardContent>
      </Card>

      {/* Languages */}
      <Card>
        <CardHeader>
          <CardTitle>Languages</CardTitle>
          <CardDescription>
            Languages the assistant will detect and reply in, and the fallback default.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <div className="grid gap-2">
            <Label htmlFor="languages">Supported languages</Label>
            <StringListEditor
              id="languages"
              values={languages}
              onChange={(next) => {
                set("supported_languages", next);
                if (!next.includes(form.default_language) && next.length > 0) {
                  set("default_language", next[0]);
                }
              }}
              placeholder="Add a language code, e.g. en"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="default-language">Default language</Label>
            <Select
              value={form.default_language || undefined}
              onValueChange={(v) => set("default_language", v)}
            >
              <SelectTrigger id="default-language" className="w-full sm:max-w-64">
                <SelectValue placeholder="Select a default language" />
              </SelectTrigger>
              <SelectContent>
                {languages.map((l) => (
                  <SelectItem key={l} value={l}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Used when a customer&apos;s language can&apos;t be detected.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Relevance threshold */}
      <Card>
        <CardHeader>
          <CardTitle>Relevance threshold</CardTitle>
          <CardDescription>
            The grounding gate answers only when the top-1 rerank score clears this cutoff. A
            code-enforced guardrail — pick a calibrated band rather than a raw number.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2">
          <Label htmlFor="threshold">Cutoff</Label>
          <Select
            value={thresholdKey}
            onValueChange={(key) => {
              const opt = THRESHOLD_OPTIONS.find((o) => o.key === key);
              if (opt) set("relevance_threshold", opt.value);
            }}
          >
            <SelectTrigger id="threshold" className="w-full sm:max-w-72">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {THRESHOLD_OPTIONS.map((o) => (
                <SelectItem key={o.key} value={o.key}>
                  {o.label}
                </SelectItem>
              ))}
              {thresholdKey === "custom" ? (
                <SelectItem value="custom">
                  Custom ({String(form.relevance_threshold)})
                </SelectItem>
              ) : null}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            {thresholdKey === "custom"
              ? "A calibrated custom cutoff is set. Choose a preset to change it."
              : activeThreshold?.hint}
          </p>
        </CardContent>
      </Card>

      {/* Escalation */}
      <Card>
        <CardHeader>
          <CardTitle>Escalation</CardTitle>
          <CardDescription>
            When the AI should stop and hand the conversation to a human.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6">
          <fieldset className="grid gap-3">
            <legend className="mb-1 text-sm font-medium">Active triggers</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {TRIGGERS.map((t) => {
                const on = triggers.includes(t.value);
                return (
                  <label
                    key={t.value}
                    htmlFor={`trigger-${t.value}`}
                    className="flex cursor-pointer items-start gap-3 rounded-lg border bg-card p-3 transition-colors hover:bg-accent/50"
                  >
                    <Checkbox
                      id={`trigger-${t.value}`}
                      checked={on}
                      onCheckedChange={(c) => toggleTrigger(t.value, c === true)}
                      className="mt-0.5"
                    />
                    <span className="grid gap-0.5">
                      <span className="text-sm font-medium leading-none">{t.label}</span>
                      <span className="text-xs text-muted-foreground">{t.hint}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <Separator />

          <NumberField
            id="verify-attempts"
            label="Failed verification attempts before escalation"
            value={Number(form.verify_max_attempts ?? 0)}
            onChange={(n) => set("verify_max_attempts", n)}
            unit="attempts"
            min={1}
            step={1}
            hint="After this many failed identity checks, the AI escalates instead of retrying. Healthcare tenants are capped at 1."
          />

          <div className="grid gap-2">
            <Label htmlFor="sensitive-intents">Sensitive-intent list</Label>
            <StringListEditor
              id="sensitive-intents"
              values={form.sensitive_intent_list ?? []}
              onChange={(next) => set("sensitive_intent_list", next)}
              placeholder="Add an intent, e.g. refund dispute"
              emptyLabel="No sensitive intents configured."
            />
            <p className="text-xs text-muted-foreground">
              Matching intents trigger the <span className="font-medium">Sensitive intent</span>{" "}
              escalation.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Allowed tags */}
      <Card>
        <CardHeader>
          <CardTitle>Allowed tags</CardTitle>
          <CardDescription>
            The only tags the AI may apply to a conversation. New tags it proposes wait in the
            approval tray below.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <StringListEditor
            id="allowed-tags"
            values={form.allowed_tags ?? []}
            onChange={(next) => set("allowed_tags", next)}
            placeholder="Add a tag, e.g. order_status"
            emptyLabel="No tags allowed yet."
          />
        </CardContent>
      </Card>

      {/* SLA & lifecycle */}
      <Card>
        <CardHeader>
          <CardTitle>SLA &amp; lifecycle timers</CardTitle>
          <CardDescription>
            Follow-up copy and how long a conversation waits before it auto-resolves, closes, or can
            be reopened.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <div className="grid gap-2">
            <Label htmlFor="sla-text">SLA follow-up text</Label>
            <Textarea
              id="sla-text"
              rows={2}
              value={form.sla_followup_text ?? ""}
              onChange={(e) => set("sla_followup_text", e.target.value)}
              placeholder="We'll get back to you within one business day."
            />
          </div>
          <div className="grid gap-5 sm:grid-cols-3">
            <NumberField
              id="resolve-idle"
              label="Auto-resolve after idle"
              value={Number(form.resolve_after_idle_seconds ?? 0)}
              onChange={(n) => set("resolve_after_idle_seconds", n)}
              unit="seconds"
            />
            <NumberField
              id="close-idle"
              label="Auto-close after idle"
              value={Number(form.close_after_idle_seconds ?? 0)}
              onChange={(n) => set("close_after_idle_seconds", n)}
              unit="seconds"
            />
            <NumberField
              id="reopen-window"
              label="Reopen window"
              value={Number(form.reopen_window_seconds ?? 0)}
              onChange={(n) => set("reopen_window_seconds", n)}
              unit="seconds"
            />
          </div>
        </CardContent>
      </Card>

      {/* Notifications & links */}
      <Card>
        <CardHeader>
          <CardTitle>Notifications &amp; links</CardTitle>
          <CardDescription>
            Where after-hours escalations notify, and an optional carrier tracking-URL template.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <div className="grid gap-2">
            <Label htmlFor="support-email">Support notification email</Label>
            <Input
              id="support-email"
              type="email"
              value={form.support_notification_email ?? ""}
              onChange={(e) => set("support_notification_email", e.target.value || null)}
              placeholder="support@company.com"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="carrier-url">Carrier tracking-URL template</Label>
            <Input
              id="carrier-url"
              value={form.carrier_url_template ?? ""}
              onChange={(e) => set("carrier_url_template", e.target.value || null)}
              placeholder="https://carrier/track/{tracking_ref}"
            />
            <p className="text-xs text-muted-foreground">
              Optional. Use <code className="font-mono">{"{tracking_ref}"}</code> where the tracking
              number goes.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Save bar */}
      <div className="flex flex-wrap items-center justify-end gap-3 border-t pt-4">
        <span className="mr-auto text-sm text-muted-foreground" aria-live="polite">
          {dirty ? "You have unsaved changes." : "All changes saved."}
        </span>
        <Button
          variant="outline"
          disabled={!dirty || save.isPending}
          onClick={() => setForm(initial)}
        >
          Reset
        </Button>
        <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

function SettingsSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <CardHeader className="gap-2">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-72 max-w-full" />
          </CardHeader>
          <CardContent className="grid gap-4">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-2/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function AgentSettingsPage() {
  const { role } = useAuth();
  const settingsQ = useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: getAgentSettings,
  });

  const canManageSettings = !role || hasPermission(role, "settings:manage");
  const canApproveTags = !role || hasPermission(role, "tags:approve");

  if (!canManageSettings) {
    return (
      <div>
        <PageHeader
          title="Agent settings"
          description="Configure how the AI assistant answers, escalates, and tags conversations."
        />
        <EmptyState
          icon={ShieldAlert}
          title="You don't have access"
          description="Managing agent settings requires an admin role. Ask a workspace admin if you need changes."
        />
      </div>
    );
  }

  return (
    <div className="space-y-10">
      <div>
        <PageHeader
          title="Agent settings"
          description="Configure how the AI assistant answers, escalates, and tags conversations for this workspace."
        />
        {settingsQ.isLoading ? (
          <SettingsSkeleton />
        ) : settingsQ.isError ? (
          <ErrorState
            title="Couldn't load settings"
            message="The agent-settings endpoint didn't respond. Check your connection and try again."
            onRetry={() => void settingsQ.refetch()}
          />
        ) : (
          <SettingsForm initial={settingsQ.data!} />
        )}
      </div>

      {canApproveTags ? (
        <section className="space-y-4">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold tracking-tight">Pending tags</h2>
            <p className="text-sm text-muted-foreground">
              Approve or reject tags the AI proposed. These actions apply immediately and are
              independent of the settings above.
            </p>
          </div>
          <PendingTagsTray />
        </section>
      ) : null}
    </div>
  );
}
