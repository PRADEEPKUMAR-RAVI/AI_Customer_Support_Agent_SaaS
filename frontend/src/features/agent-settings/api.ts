/**
 * FE-AgentSettings API layer.
 *
 * This screen talks to TWO of Person-3's backends with different write semantics, both now part of
 * the generated OpenAPI client:
 *   • bulk  GET / PATCH  /api/v1/admin/settings          (M1 — agent_settings config form)
 *   • per-item POST      /api/v1/admin/tags/{id}/approve|reject  (M5 — pending-tag tray)
 *
 * Everything goes through the typed `{ api, unwrap }` client (Bearer + 401-refresh handled there),
 * so there is no hand-rolled fetch wrapper here. The wire shape for settings wraps the config blob
 * in `{ config }`; we unwrap that on read and re-wrap on write. `AgentSettings` is a typed *view* of
 * the knobs this screen edits — unknown knobs ride through untouched via the index signature so the
 * FE never drops a field it doesn't render.
 */

import type { components } from "@/api/generated/schema";
import { api, unwrap } from "@/lib/api";

/** Pending-tag tray row — the generated M5 DTO. Note the field is `name` (not `label`). */
export type TagApprovalResponse = components["schemas"]["TagApprovalResponse"];

/** Typed view of the M1 `agent_settings.config` blob. Loosely typed: unknown knobs pass through
 * untouched on save so the FE never drops a field it doesn't render. */
export interface AgentSettings {
  persona: string;
  welcome_message: string;
  supported_languages: string[];
  default_language: string;
  active_triggers: string[];
  sensitive_intent_list: string[];
  relevance_threshold: number | null;
  verify_max_attempts: number;
  sla_followup_text: string;
  carrier_url_template: string | null;
  support_notification_email: string | null;
  allowed_tags: string[];
  autonomy_enabled: boolean;
  resolve_after_idle_seconds: number;
  close_after_idle_seconds: number;
  reopen_window_seconds: number;
  [key: string]: unknown; // preserve knobs this screen doesn't edit
}

export async function getAgentSettings(): Promise<AgentSettings> {
  const res = unwrap(await api.GET("/api/v1/admin/settings"));
  return (res.config ?? {}) as AgentSettings;
}

/** Bulk save. The full settings object round-trips (index signature preserves un-rendered knobs);
 * M1 PATCH shallow-merges the `config` payload. */
export async function updateAgentSettings(patch: Partial<AgentSettings>): Promise<AgentSettings> {
  const res = unwrap(
    await api.PATCH("/api/v1/admin/settings", {
      body: { config: patch as Record<string, unknown> },
    })
  );
  return (res.config ?? {}) as AgentSettings;
}

export async function listPendingTags(): Promise<TagApprovalResponse[]> {
  return unwrap(
    await api.GET("/api/v1/admin/tags", { params: { query: { status: "pending" } } })
  );
}

export async function approveTag(id: string): Promise<TagApprovalResponse> {
  return unwrap(
    await api.POST("/api/v1/admin/tags/{tag_def_id}/approve", {
      params: { path: { tag_def_id: id } },
    })
  );
}

export async function rejectTag(id: string): Promise<TagApprovalResponse> {
  return unwrap(
    await api.POST("/api/v1/admin/tags/{tag_def_id}/reject", {
      params: { path: { tag_def_id: id } },
    })
  );
}
