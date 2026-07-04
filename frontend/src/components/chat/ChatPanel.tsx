/**
 * ChatPanel — the one reusable chat UI ([IMP-FE-2]), rendered by the SPA route and (via
 * preact/compat) the widget. Inline styles keep it self-contained so it renders identically
 * inside a Shadow DOM without leaking or inheriting page CSS. Chrome locale + direction follow
 * the established `detected_language` ([C7]); the AI answer text itself is server-generated.
 */

import { useEffect, useRef, useState } from "react";

import { dirFor, strings, type ChatController, type ChatMessage } from "../../chat-core";
import type { Citation } from "../../types/sse";
import { useChat } from "./useChat";

const C = {
  bg: "#ffffff",
  border: "#e5e7eb",
  user: "#2563eb",
  userText: "#ffffff",
  bot: "#f3f4f6",
  botText: "#111827",
  muted: "#6b7280",
  danger: "#b91c1c",
  accent: "#2563eb",
};

const S = {
  root: { display: "flex", flexDirection: "column", height: "100%", minHeight: 0, background: C.bg,
    fontFamily: "system-ui, sans-serif", color: C.botText, fontSize: 14 } as React.CSSProperties,
  list: { flex: 1, overflowY: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 8 } as React.CSSProperties,
  row: (mine: boolean) => ({ display: "flex", justifyContent: mine ? "flex-end" : "flex-start" }) as React.CSSProperties,
  bubble: (mine: boolean) => ({
    maxWidth: "80%", padding: "8px 12px", borderRadius: 12, whiteSpace: "pre-wrap", wordBreak: "break-word",
    background: mine ? C.user : C.bot, color: mine ? C.userText : C.botText,
  }) as React.CSSProperties,
  status: { color: C.muted, fontStyle: "italic", padding: "0 12px 6px" } as React.CSSProperties,
  cites: { marginTop: 6, fontSize: 12, color: C.muted, display: "flex", flexDirection: "column", gap: 2 } as React.CSSProperties,
  thumbs: { display: "flex", gap: 6, marginTop: 6 } as React.CSSProperties,
  thumb: (on: boolean) => ({ cursor: "pointer", border: "none", background: "transparent",
    opacity: on ? 1 : 0.5, fontSize: 14 }) as React.CSSProperties,
  composer: { borderTop: `1px solid ${C.border}`, padding: 8, display: "flex", flexDirection: "column", gap: 6 } as React.CSSProperties,
  textarea: { resize: "none", border: `1px solid ${C.border}`, borderRadius: 8, padding: 8, fontFamily: "inherit",
    fontSize: 14, minHeight: 40 } as React.CSSProperties,
  actions: { display: "flex", gap: 8, alignItems: "center" } as React.CSSProperties,
  btn: (kind: "primary" | "ghost") => ({
    padding: "8px 12px", borderRadius: 8, cursor: "pointer", fontSize: 13,
    border: kind === "ghost" ? `1px solid ${C.accent}` : "1px solid transparent",
    background: kind === "primary" ? C.accent : "transparent", color: kind === "primary" ? "#fff" : C.accent,
  }) as React.CSSProperties,
  consent: { padding: 20, display: "flex", flexDirection: "column", gap: 12, height: "100%",
    justifyContent: "center" } as React.CSSProperties,
  error: { color: C.danger, padding: "0 12px 6px", display: "flex", gap: 8, alignItems: "center" } as React.CSSProperties,
};

function CitationLine({ c }: { c: Citation }) {
  if (c.source_url) {
    return (
      <a href={c.source_url} target="_blank" rel="noreferrer noopener" style={{ color: C.accent }}>
        [{c.index + 1}] {c.title}
      </a>
    );
  }
  const page = typeof c.page_number === "number" ? `, p.${c.page_number}` : "";
  return <span>[{c.index + 1}] from {c.title}{page}</span>;
}

function MessageBubble({ msg, onRate }: { msg: ChatMessage; onRate: (r: "up" | "down") => void }) {
  const mine = msg.role === "user";
  const rateable = !mine && !msg.streaming && msg.id !== "" && msg.id !== "welcome";
  return (
    <div style={S.row(mine)}>
      <div style={S.bubble(mine)}>
        <span>{msg.content}{msg.streaming && <span aria-hidden>▍</span>}</span>
        {msg.citations.length > 0 && (
          <div style={S.cites}>
            {msg.citations.map((c) => <CitationLine key={`${c.source_id}:${c.index}`} c={c} />)}
          </div>
        )}
        {rateable && (
          <div style={S.thumbs}>
            <button aria-label="helpful" style={S.thumb(msg.feedback === "up")} onClick={() => onRate("up")}>👍</button>
            <button aria-label="not helpful" style={S.thumb(msg.feedback === "down")} onClick={() => onRate("down")}>👎</button>
          </div>
        )}
      </div>
    </div>
  );
}

export function ChatPanel({ controller, requireConsent = true }: { controller: ChatController; requireConsent?: boolean }) {
  const { state, send, retry, rate } = useChat(controller);
  const [draft, setDraft] = useState("");
  const [consented, setConsented] = useState(!requireConsent);
  const endRef = useRef<HTMLDivElement>(null);
  const t = strings(state.language);
  const dir = dirFor(state.language);
  const streaming = state.conn === "streaming";

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [state.messages, state.status]);

  if (!consented) {
    return (
      <div style={{ ...S.root }} dir={dir}>
        <div style={S.consent}>
          <strong style={{ fontSize: 16 }}>{t.consentTitle}</strong>
          <p style={{ color: C.muted, margin: 0 }}>{t.consentBody}</p>
          <button style={S.btn("primary")} onClick={() => setConsented(true)}>{t.consentAccept}</button>
        </div>
      </div>
    );
  }

  const submit = () => {
    const text = draft.trim();
    if (!text || streaming) return;
    setDraft("");
    send(text);
  };

  return (
    <div style={S.root} dir={dir}>
      <div style={S.list} role="log" aria-live="polite">
        {state.messages.map((m, i) => (
          <MessageBubble key={m.id || `m${i}`} msg={m} onRate={(r) => m.id && rate(m.id, r)} />
        ))}
        <div ref={endRef} />
      </div>

      {streaming && state.status && <div style={S.status}>{t.status[state.status as keyof typeof t.status] ?? t.connecting}</div>}
      {state.conn === "error" && (
        <div style={S.error}>
          <span>{t.errorGeneric}</span>
          <button style={S.btn("ghost")} onClick={() => retry()}>{t.retry}</button>
        </div>
      )}

      <div style={S.composer}>
        <textarea
          style={S.textarea}
          value={draft}
          placeholder={t.placeholder}
          disabled={streaming}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div style={S.actions}>
          <button style={S.btn("primary")} disabled={streaming || !draft.trim()} onClick={submit}>{t.send}</button>
          <button
            style={S.btn("ghost")}
            disabled={streaming}
            onClick={() => send(t.talkToHuman, { escalate: true })}
          >
            {t.talkToHuman}
          </button>
        </div>
      </div>
    </div>
  );
}
