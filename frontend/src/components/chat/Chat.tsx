/** Self-contained chat entry: bootstraps (or resumes) a widget session, builds a ChatController,
 * and renders ChatPanel. Used by the SPA hosted page and the embeddable widget alike — the only
 * inputs are the public widget_key and the API base. */

import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ChatController, clearSession, resumeOrCreateSession, type WidgetSession } from "../../chat-core";
import { ChatPanel } from "./ChatPanel";

export interface ChatProps {
  widgetKey: string;
  apiBase?: string;
  requireConsent?: boolean;
}

const FONT = '"Geist Variable", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';

function Notice({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "danger" }) {
  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        padding: 24,
        textAlign: "center",
        fontFamily: FONT,
        fontSize: 14,
        background: "var(--background, #ffffff)",
        color: tone === "danger" ? "var(--destructive, #dc2626)" : "var(--muted-foreground, #64748b)",
      }}
    >
      {children}
    </div>
  );
}

export function Chat({ widgetKey, apiBase = "/api/v1", requireConsent = true }: ChatProps) {
  const [session, setSession] = useState<WidgetSession | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setSession(null);
    setError(null);
    resumeOrCreateSession(apiBase, widgetKey)
      .then((s) => alive && setSession(s))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [widgetKey, apiBase]);

  const controller = useMemo(
    () =>
      session
        ? new ChatController({
            apiBase,
            conversationId: session.conversationId,
            sessionToken: session.sessionToken,
            welcomeMessage: session.config.welcome_message,
            defaultLanguage: session.config.default_language,
            // Self-heal a stale/expired persisted session: drop it and mint a fresh one (which
            // re-persists for reloads). The controller retries the same message on the new session.
            onReauth: async () => {
              clearSession(widgetKey);
              const fresh = await resumeOrCreateSession(apiBase, widgetKey);
              return { conversationId: fresh.conversationId, sessionToken: fresh.sessionToken };
            },
          })
        : null,
    [session, apiBase, widgetKey],
  );

  // Live updates: while the chat is mounted, poll for human-agent replies so the customer sees a
  // human's messages appear once an agent sends their first reply (the AI goes silent then). Stops
  // on unmount.
  useEffect(() => {
    controller?.startLiveUpdates();
    return () => controller?.stopLiveUpdates();
  }, [controller]);

  if (error) return <Notice tone="danger">Unable to start chat: {error}</Notice>;
  if (!controller)
    return (
      <Notice>
        <Loader2 size={20} style={{ animation: "cswspin 0.7s linear infinite" }} />
        Connecting…
      </Notice>
    );
  return <ChatPanel controller={controller} requireConsent={requireConsent} />;
}
