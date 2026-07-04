/** FE-AgentSettings: the tenant's agent configuration form + the pending-tag approval tray.
 *
 * Two independent backends with different write semantics (see ./api.ts):
 *   • the config FORM is a single bulk PATCH /admin/settings (M1);
 *   • the tag TRAY is per-item POST /admin/tags/{id}/approve|reject (M5), with optimistic per-row
 *     actions that must NEVER ride on the form save.
 * The relevance-threshold control is GUARDED ([IMP-RAG-1]) — it's a code-enforced non-negotiable
 * input, so we offer a coarse strict/balanced/lenient dial + an advanced numeric override that warns
 * when it leaves the eval-recommended band, rather than a bare number field.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useAuth } from "../../app/providers";
import { Button, Card, Spinner } from "../../components";
import { hasPermission } from "../../lib/rbac";
import {
  AgentSettingsUnavailable,
  approveTag,
  getAgentSettings,
  listPendingTags,
  rejectTag,
  updateAgentSettings,
  type AgentSettings,
  type PendingTag,
} from "./api";

// Escalation triggers ([C6] canonical enum, owned by M2/P3 domain/escalation).
const TRIGGERS = ["no_grounding", "explicit", "sensitive", "dispute", "n_fails", "proactive", "timeout"];

// Threshold guard bands (bge-reranker-v2-m3 score scale; re-tune if the reranker changes).
const THRESHOLD_PRESETS = { lenient: 0.5, balanced: 1.0, strict: 1.5 } as const;
const RECOMMENDED_MIN = 0.8;
const RECOMMENDED_MAX = 1.6;

const textStyle: React.CSSProperties = { width: "100%", padding: 6, fontSize: 14 };
const commaJoin = (a: string[] | undefined) => (a ?? []).join(", ");
const commaSplit = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

function ThresholdControl({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  const effective = value ?? THRESHOLD_PRESETS.balanced;
  const preset =
    value === null
      ? "default"
      : (Object.entries(THRESHOLD_PRESETS).find(([, v]) => v === value)?.[0] ?? "custom");
  const outOfBand = value !== null && (value < RECOMMENDED_MIN || value > RECOMMENDED_MAX);

  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {(["lenient", "balanced", "strict"] as const).map((k) => (
          <Button
            key={k}
            variant={preset === k ? "primary" : "ghost"}
            onClick={() => onChange(THRESHOLD_PRESETS[k])}
          >
            {k} ({THRESHOLD_PRESETS[k]})
          </Button>
        ))}
        <Button variant={value === null ? "primary" : "ghost"} onClick={() => onChange(null)}>
          eval default
        </Button>
      </div>
      <label style={{ fontSize: 13 }}>
        advanced — exact top-1 rerank cutoff:{" "}
        <input
          type="number"
          step="0.05"
          min="0"
          value={effective}
          onChange={(e) => onChange(Number(e.target.value))}
          style={{ width: 90 }}
        />
      </label>
      {value === null ? (
        <p style={{ fontSize: 12, color: "#6b7280" }}>
          Using the calibrated per-tenant default (recommended). The grounding gate answers only when
          the top-1 rerank score clears this cutoff.
        </p>
      ) : outOfBand ? (
        <p style={{ fontSize: 12, color: "#b45309" }} role="alert">
          ⚠ {value} is outside the eval-recommended band ({RECOMMENDED_MIN}–{RECOMMENDED_MAX}). Too low
          lets ungrounded answers through; too high refuses good questions. Prefer the presets unless
          you've re-calibrated on a labelled set.
        </p>
      ) : (
        <p style={{ fontSize: 12, color: "#15803d" }}>Within the recommended band.</p>
      )}
    </div>
  );
}

function TagTray() {
  const qc = useQueryClient();
  const key = ["agent-settings", "pending-tags"];
  const tagsQ = useQuery({
    queryKey: key,
    queryFn: listPendingTags,
    retry: false,
  });

  // Per-row optimistic action config — deliberately independent of the settings-form save.
  // (A plain factory returning options; the hooks themselves are called unconditionally below.)
  const optsFor = (fn: (id: string) => Promise<void>) => ({
    mutationFn: fn,
    onMutate: async (id: string) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<PendingTag[]>(key);
      qc.setQueryData<PendingTag[]>(key, (t) => (t ?? []).filter((x) => x.id !== id));
      return { prev };
    },
    onError: (_e: unknown, _id: string, ctx: { prev?: PendingTag[] } | undefined) =>
      ctx?.prev && qc.setQueryData(key, ctx.prev),
    onSettled: () => qc.invalidateQueries({ queryKey: key }),
  });
  const approve = useMutation(optsFor(approveTag));
  const reject = useMutation(optsFor(rejectTag));

  if (tagsQ.isError && tagsQ.error instanceof AgentSettingsUnavailable) {
    return <p style={{ fontSize: 13, color: "#6b7280" }}>Tag approvals will appear here once M5 (ticketing) is wired.</p>;
  }
  if (tagsQ.isLoading) return <Spinner />;
  const tags = tagsQ.data ?? [];
  if (tags.length === 0) return <p style={{ fontSize: 13, color: "#6b7280" }}>No tags awaiting approval.</p>;

  return (
    <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: 8 }}>
      {tags.map((t) => (
        <li key={t.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ flex: 1 }}>
            <b>{t.label}</b>
            {t.ticket_id && <span style={{ color: "#6b7280", fontSize: 12 }}> · ticket {t.ticket_id}</span>}
          </span>
          <Button onClick={() => approve.mutate(t.id)} disabled={approve.isPending}>Approve</Button>
          <Button variant="ghost" onClick={() => reject.mutate(t.id)} disabled={reject.isPending}>Reject</Button>
        </li>
      ))}
    </ul>
  );
}

function SettingsForm({ initial }: { initial: AgentSettings }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<AgentSettings>(initial);
  useEffect(() => setForm(initial), [initial]);
  const set = <K extends keyof AgentSettings>(k: K, v: AgentSettings[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: () => updateAgentSettings(form),
    onSuccess: (saved) => qc.setQueryData(["agent-settings", "config"], saved),
  });

  return (
    <Card>
      <h3>Agent configuration</h3>
      <div style={{ display: "grid", gap: 12, maxWidth: 640 }}>
        <label>
          Persona / tone
          <textarea style={textStyle} rows={2} value={form.persona} onChange={(e) => set("persona", e.target.value)} />
        </label>
        <label>
          Welcome message
          <input style={textStyle} value={form.welcome_message} onChange={(e) => set("welcome_message", e.target.value)} />
        </label>
        <label>
          Supported languages (comma-separated)
          <input
            style={textStyle}
            value={commaJoin(form.supported_languages)}
            onChange={(e) => set("supported_languages", commaSplit(e.target.value))}
          />
        </label>
        <label>
          Default language
          <select value={form.default_language} onChange={(e) => set("default_language", e.target.value)}>
            {(form.supported_languages ?? []).map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </label>

        <fieldset style={{ border: "1px solid #e5e7eb", borderRadius: 8 }}>
          <legend style={{ fontSize: 13 }}>Relevance threshold (grounding gate)</legend>
          <ThresholdControl value={form.relevance_threshold} onChange={(v) => set("relevance_threshold", v)} />
        </fieldset>

        <fieldset style={{ border: "1px solid #e5e7eb", borderRadius: 8 }}>
          <legend style={{ fontSize: 13 }}>Active escalation triggers</legend>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {TRIGGERS.map((t) => {
              const on = (form.active_triggers ?? []).includes(t);
              return (
                <label key={t} style={{ fontSize: 13 }}>
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={(e) =>
                      set(
                        "active_triggers",
                        e.target.checked
                          ? [...(form.active_triggers ?? []), t]
                          : (form.active_triggers ?? []).filter((x) => x !== t)
                      )
                    }
                  />{" "}
                  {t}
                </label>
              );
            })}
          </div>
        </fieldset>

        <label>
          Sensitive-intent list (comma-separated)
          <input
            style={textStyle}
            value={commaJoin(form.sensitive_intent_list)}
            onChange={(e) => set("sensitive_intent_list", commaSplit(e.target.value))}
          />
        </label>
        <label>
          Allowed tags (comma-separated)
          <input
            style={textStyle}
            value={commaJoin(form.allowed_tags)}
            onChange={(e) => set("allowed_tags", commaSplit(e.target.value))}
          />
        </label>
        <label>
          SLA follow-up text
          <input style={textStyle} value={form.sla_followup_text} onChange={(e) => set("sla_followup_text", e.target.value)} />
        </label>
        <label>
          Carrier tracking-URL template (optional, {"{tracking_ref}"})
          <input
            style={textStyle}
            value={form.carrier_url_template ?? ""}
            onChange={(e) => set("carrier_url_template", e.target.value || null)}
            placeholder="https://carrier/track/{tracking_ref}"
          />
        </label>
        <label>
          Support notification email (after-hours escalations)
          <input
            style={textStyle}
            value={form.support_notification_email ?? ""}
            onChange={(e) => set("support_notification_email", e.target.value || null)}
          />
        </label>
        <label style={{ fontSize: 14 }}>
          <input
            type="checkbox"
            checked={form.autonomy_enabled}
            onChange={(e) => set("autonomy_enabled", e.target.checked)}
          />{" "}
          Autonomy enabled (AI answers without a human in the loop)
        </label>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save settings"}
          </Button>
          {save.isSuccess && <span style={{ color: "#15803d", fontSize: 13 }}>✓ Saved</span>}
          {save.isError && <span style={{ color: "#b91c1c", fontSize: 13 }}>Save failed</span>}
        </div>
      </div>
    </Card>
  );
}

export function AgentSettingsPage() {
  const { role } = useAuth();
  const settingsQ = useQuery({
    queryKey: ["agent-settings", "config"],
    queryFn: getAgentSettings,
    retry: false,
  });

  if (role && !hasPermission(role, "settings:manage")) {
    return <Card><p>You don't have permission to manage agent settings.</p></Card>;
  }

  const canApproveTags = !role || hasPermission(role, "tags:approve");

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 820 }}>
      <h2>Agent settings</h2>

      {settingsQ.isLoading ? (
        <Spinner />
      ) : settingsQ.isError && settingsQ.error instanceof AgentSettingsUnavailable ? (
        <Card>
          <p style={{ color: "#6b7280" }}>
            The settings backend (M1 <code>/admin/settings</code>) isn't wired yet. This screen is
            ready and will load the tenant's configuration as soon as that endpoint ships.
          </p>
        </Card>
      ) : settingsQ.isError ? (
        <p role="alert">Failed to load agent settings.</p>
      ) : (
        <SettingsForm initial={settingsQ.data!} />
      )}

      {canApproveTags && (
        <Card>
          <h3>Pending tag approvals</h3>
          <p style={{ fontSize: 12, color: "#6b7280" }}>
            Per-item actions — independent of the settings save above.
          </p>
          <TagTray />
        </Card>
      )}
    </div>
  );
}
