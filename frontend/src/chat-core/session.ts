/**
 * Widget session bootstrap. `POST /widget/session` mints a SERVER-side session id + a signed
 * session token bound to (tenant, session, conversation) ([IMP-SEC-3]) — the client never
 * invents an id. For the embeddable widget we persist the minted token in localStorage so a
 * page reload continues the same conversation; a rejected/expired token simply mints a new one.
 */

export interface WidgetConfig {
  welcome_message: string;
  supported_languages: string[];
  default_language: string;
}

export interface WidgetSession {
  sessionId: string;
  conversationId: string;
  sessionToken: string;
  config: WidgetConfig;
}

interface RawSession {
  session_id: string;
  conversation_id: string;
  session_token: string;
  config: WidgetConfig;
}

const lsKey = (widgetKey: string) => `cs-agent:session:${widgetKey}`;

export async function createSession(apiBase: string, widgetKey: string): Promise<WidgetSession> {
  const res = await fetch(`${apiBase}/widget/session`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ widget_key: widgetKey }),
  });
  if (!res.ok) throw new Error(`widget session failed: ${res.status}`);
  const d = (await res.json()) as RawSession;
  return {
    sessionId: d.session_id,
    conversationId: d.conversation_id,
    sessionToken: d.session_token,
    config: d.config,
  };
}

/** Reuse a persisted session across reloads, else mint a fresh one and persist it. */
export async function resumeOrCreateSession(apiBase: string, widgetKey: string): Promise<WidgetSession> {
  try {
    const raw = localStorage.getItem(lsKey(widgetKey));
    if (raw) return JSON.parse(raw) as WidgetSession;
  } catch {
    /* private-mode / disabled storage — fall through to a fresh (non-persisted) session */
  }
  const session = await createSession(apiBase, widgetKey);
  try {
    localStorage.setItem(lsKey(widgetKey), JSON.stringify(session));
  } catch {
    /* ignore persistence failure */
  }
  return session;
}

export function clearSession(widgetKey: string): void {
  try {
    localStorage.removeItem(lsKey(widgetKey));
  } catch {
    /* ignore */
  }
}
