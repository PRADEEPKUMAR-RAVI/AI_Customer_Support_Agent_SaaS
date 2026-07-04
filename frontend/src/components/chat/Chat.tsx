/** Self-contained chat entry: bootstraps (or resumes) a widget session, builds a ChatController,
 * and renders ChatPanel. Used by the SPA hosted page and the embeddable widget alike — the only
 * inputs are the public widget_key and the API base. */

import { useEffect, useMemo, useState } from "react";

import { ChatController, resumeOrCreateSession, type WidgetSession } from "../../chat-core";
import { ChatPanel } from "./ChatPanel";

export interface ChatProps {
  widgetKey: string;
  apiBase?: string;
  requireConsent?: boolean;
}

const notice = (color: string, text: string) => (
  <div style={{ padding: 16, fontFamily: "system-ui, sans-serif", color }}>{text}</div>
);

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
          })
        : null,
    [session, apiBase],
  );

  if (error) return notice("#b91c1c", `Unable to start chat: ${error}`);
  if (!controller) return notice("#6b7280", "Connecting…");
  return <ChatPanel controller={controller} requireConsent={requireConsent} />;
}
