/**
 * FE-AgentSettings API layer.
 *
 * This screen talks to TWO of Person-3's backends with different write semantics:
 *   • bulk  GET / PATCH  /api/v1/admin/settings          (M1 — agent_settings config form)
 *   • per-item POST      /api/v1/admin/tags/{id}/approve|reject  (M5 — pending-tag tray)
 *
 * Those endpoints are owned by M1/M5 and may not be wired yet. They are NOT in the generated
 * OpenAPI client, so we use a small tolerant `fetch` wrapper (Bearer from the shared auth store)
 * rather than the typed client. `AgentSettingsUnavailable` (404/501) lets the page degrade to a
 * clear "waiting on M1/M5" state instead of crashing — the UI is complete and lights up the moment
 * those endpoints ship. Keep the paths/DTOs in lockstep with M1/M5 when they freeze.
 */

import { getAccessToken } from "../../lib/auth";

const SETTINGS_PATH = "/api/v1/admin/settings";
const TAGS_PATH = "/api/v1/admin/tags";

/** A record's config blob (M1 `agent_settings.config`). Typed loosely: unknown knobs pass through
 * untouched on save so the FE never drops a field it doesn't render. */
export interface AgentSettings {
  persona: string;
  welcome_message: string;
  supported_languages: string[];
  default_language: string;
  active_triggers: string[];
  sensitive_intent_list: string[];
  relevance_threshold: number | null;
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

export interface PendingTag {
  id: string;
  label: string;
  ticket_id?: string;
  created_at?: string;
}

export class AgentSettingsUnavailable extends Error {
  constructor(public status: number) {
    super(`agent-settings backend not available (HTTP ${status})`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const headers = new Headers(init?.headers);
  headers.set("content-type", "application/json");
  if (token) headers.set("authorization", `Bearer ${token}`);
  const resp = await fetch(path, { ...init, headers, credentials: "include" });
  // 404 (route not mounted) / 501 (stub) => the M1/M5 endpoint isn't live yet.
  if (resp.status === 404 || resp.status === 501) throw new AgentSettingsUnavailable(resp.status);
  if (!resp.ok) throw new Error(`${init?.method ?? "GET"} ${path} → ${resp.status}`);
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export function getAgentSettings(): Promise<AgentSettings> {
  return request<AgentSettings>(SETTINGS_PATH);
}

/** Bulk save. Sends the full settings object back (M1 PATCH is a merge; sending the whole object is
 * safe because we round-tripped every field, including the ones this screen doesn't render). */
export function updateAgentSettings(patch: Partial<AgentSettings>): Promise<AgentSettings> {
  return request<AgentSettings>(SETTINGS_PATH, { method: "PATCH", body: JSON.stringify(patch) });
}

export function listPendingTags(): Promise<PendingTag[]> {
  return request<PendingTag[]>(`${TAGS_PATH}?status=pending`);
}

export function approveTag(id: string): Promise<void> {
  return request<void>(`${TAGS_PATH}/${encodeURIComponent(id)}/approve`, { method: "POST" });
}

export function rejectTag(id: string): Promise<void> {
  return request<void>(`${TAGS_PATH}/${encodeURIComponent(id)}/reject`, { method: "POST" });
}
