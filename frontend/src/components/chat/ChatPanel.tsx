/**
 * ChatPanel — the one reusable chat UI ([IMP-FE-2]), rendered by the SPA hosted page/console and
 * (verbatim) inside the widget's Shadow DOM. Layout/colour use React inline styles that READ the
 * design-system CSS variables (with hex fallbacks): inline styles apply via the CSSOM so they are
 * CSP-safe and unaffected by Shadow-DOM encapsulation, while `var(--token)` reads pick up the
 * console tokens (globals.css :root) or the widget tokens (:host). The AI answer is rendered as
 * Markdown, styled by the `.chat-md` rules that live in BOTH globals.css and the widget stylesheet.
 * Chrome locale + direction follow the established `detected_language` ([C7]).
 */

import { Bot, ExternalLink, Headset, RotateCw, Send, ThumbsDown, ThumbsUp, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { dirFor, strings, type ChatController, type ChatMessage } from "../../chat-core";
import type { Citation } from "../../types/sse";
import { useChat } from "./useChat";

// Design tokens (resolve against console :root or widget :host; hex fallbacks for safety).
const c = {
  bg: "var(--background, #ffffff)",
  fg: "var(--foreground, #0f172a)",
  card: "var(--card, #ffffff)",
  border: "var(--border, #e2e8f0)",
  muted: "var(--muted-foreground, #64748b)",
  secondary: "var(--secondary, #f1f5f9)",
  primary: "var(--primary, #4f46e5)",
  primaryFg: "var(--primary-foreground, #ffffff)",
  accent: "var(--accent, #eef2ff)",
  accentFg: "var(--accent-foreground, #3730a3)",
  danger: "var(--destructive, #dc2626)",
  font: '"Geist Variable", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
};

const GRADIENT =
  "linear-gradient(150deg, var(--primary, #6366f1), color-mix(in oklab, var(--primary, #4f46e5) 68%, #000))";

const S = {
  root: {
    display: "flex", flexDirection: "column", height: "100%", minHeight: 0,
    background: c.bg, color: c.fg, fontFamily: c.font, fontSize: 14, lineHeight: 1.5,
  } as React.CSSProperties,
  header: {
    display: "flex", alignItems: "center", gap: 10, padding: "12px 14px",
    borderBottom: `1px solid ${c.border}`, flexShrink: 0,
  } as React.CSSProperties,
  avatar: {
    width: 30, height: 30, borderRadius: 9, display: "grid", placeItems: "center", flexShrink: 0,
    background: GRADIENT, color: c.primaryFg,
  } as React.CSSProperties,
  onlineDot: {
    width: 7, height: 7, borderRadius: 999, background: "var(--success, #16a34a)",
    boxShadow: "0 0 0 2px var(--card, #fff)", marginInlineStart: -8, marginTop: 14, alignSelf: "flex-start",
  } as React.CSSProperties,
  list: { flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 18 } as React.CSSProperties,
  userRow: { display: "flex", justifyContent: "flex-end", animation: "cswfadein 0.25s ease-out" } as React.CSSProperties,
  userBubble: {
    maxWidth: "82%", padding: "9px 13px", borderRadius: "14px 14px 4px 14px",
    background: c.primary, color: c.primaryFg, whiteSpace: "pre-wrap", wordBreak: "break-word",
  } as React.CSSProperties,
  botRow: { display: "flex", gap: 10, alignItems: "flex-start", animation: "cswfadein 0.25s ease-out" } as React.CSSProperties,
  botAvatar: {
    width: 26, height: 26, borderRadius: 8, display: "grid", placeItems: "center", flexShrink: 0, marginTop: 1,
    background: GRADIENT, color: c.primaryFg,
  } as React.CSSProperties,
  botBody: { flex: 1, minWidth: 0, paddingTop: 2 } as React.CSSProperties,
  thinking: { display: "flex", alignItems: "center", gap: 10, minHeight: 22 } as React.CSSProperties,
  thinkingText: { color: c.muted, fontSize: 13 } as React.CSSProperties,
  cites: { marginTop: 10, display: "flex", flexWrap: "wrap", gap: 6 } as React.CSSProperties,
  cite: {
    display: "inline-flex", alignItems: "center", gap: 7, maxWidth: 240, padding: "6px 9px",
    border: `1px solid ${c.border}`, borderRadius: 9, background: c.card, color: c.fg,
    fontSize: 12, textDecoration: "none",
  } as React.CSSProperties,
  citeN: {
    width: 16, height: 16, borderRadius: 5, background: c.accent, color: c.accentFg,
    fontSize: 10, fontWeight: 600, display: "grid", placeItems: "center", flexShrink: 0,
  } as React.CSSProperties,
  actions: { display: "flex", gap: 2, marginTop: 8 } as React.CSSProperties,
  iconBtn: (on: boolean) => ({
    width: 28, height: 28, display: "grid", placeItems: "center", cursor: "pointer",
    border: "none", borderRadius: 7, background: on ? c.accent : "transparent",
    color: on ? c.accentFg : c.muted,
  }) as React.CSSProperties,
  suggests: { display: "flex", flexWrap: "wrap", gap: 8, marginInlineStart: 36, animation: "cswfadein 0.3s ease-out" } as React.CSSProperties,
  chip: {
    padding: "7px 12px", borderRadius: 999, cursor: "pointer", fontSize: 13, fontFamily: "inherit",
    border: `1px solid ${c.border}`, background: c.card, color: c.fg, textAlign: "start",
  } as React.CSSProperties,
  errorRow: { display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", color: c.danger, fontSize: 13 } as React.CSSProperties,
  composer: { borderTop: `1px solid ${c.border}`, padding: 12, flexShrink: 0 } as React.CSSProperties,
  inputWrap: {
    display: "flex", alignItems: "flex-end", gap: 8, border: `1px solid ${c.border}`,
    borderRadius: 12, background: c.card, padding: 6, paddingInlineStart: 12,
  } as React.CSSProperties,
  textarea: {
    flex: 1, resize: "none", border: "none", outline: "none", background: "transparent",
    color: c.fg, fontFamily: "inherit", fontSize: 14, lineHeight: 1.5, maxHeight: 120, padding: "6px 0",
  } as React.CSSProperties,
  sendBtn: (enabled: boolean) => ({
    width: 34, height: 34, display: "grid", placeItems: "center", flexShrink: 0, cursor: enabled ? "pointer" : "not-allowed",
    border: "none", borderRadius: 9, background: c.primary, color: c.primaryFg, opacity: enabled ? 1 : 0.5,
    transition: "opacity .15s ease",
  }) as React.CSSProperties,
  humanBtn: {
    display: "inline-flex", alignItems: "center", gap: 6, marginTop: 8, padding: "5px 10px", cursor: "pointer",
    border: "none", borderRadius: 8, background: "transparent", color: c.muted, fontSize: 12.5, fontFamily: "inherit",
  } as React.CSSProperties,
  consent: { flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: 12, padding: 24, textAlign: "center" } as React.CSSProperties,
  consentBtn: {
    padding: "10px 16px", borderRadius: 10, cursor: "pointer", border: "none",
    background: c.primary, color: c.primaryFg, fontSize: 14, fontFamily: "inherit", fontWeight: 500,
  } as React.CSSProperties,
  ghostBtn: {
    padding: "8px 14px", borderRadius: 9, cursor: "pointer", fontSize: 13, fontFamily: "inherit",
    border: `1px solid ${c.border}`, background: "transparent", color: c.fg,
  } as React.CSSProperties,
};

// react-markdown: open links in a new tab (critical inside the embedded widget so a link never
// navigates the host page away).
const MD: Components = {
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  ),
};

function ThinkingDots() {
  const dot = (delay: number): React.CSSProperties => ({
    width: 6, height: 6, borderRadius: 999, background: c.muted, display: "inline-block",
    animation: "cswbounce 1.2s infinite", animationDelay: `${delay}s`,
  });
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }} aria-hidden>
      <span style={dot(0)} />
      <span style={dot(0.15)} />
      <span style={dot(0.3)} />
    </span>
  );
}

function CitationCard({ ct }: { ct: Citation }) {
  const inner = (
    <>
      <span style={S.citeN}>{ct.index + 1}</span>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        <span style={{ fontWeight: 500 }}>{ct.title}</span>
        {typeof ct.page_number === "number" ? <span style={{ color: c.muted }}> · p.{ct.page_number}</span> : null}
      </span>
    </>
  );
  if (ct.source_url) {
    return (
      <a style={S.cite} href={ct.source_url} target="_blank" rel="noreferrer noopener">
        {inner}
        <ExternalLink size={12} style={{ color: c.muted, flexShrink: 0 }} />
      </a>
    );
  }
  return <span style={S.cite}>{inner}</span>;
}

function Assistant({ msg, status, onRate }: { msg: ChatMessage; status: string; onRate: (r: "up" | "down") => void }) {
  // Human-agent replies aren't rateable (the feedback endpoint only accepts AI messages) and get
  // a distinct avatar + label so the customer can see a person has taken over.
  const rateable = !msg.streaming && msg.id !== "" && msg.id !== "welcome" && !msg.agent;
  const thinking = msg.streaming && !msg.content;
  return (
    <div style={S.botRow}>
      <div style={S.botAvatar}>
        {msg.agent ? <Headset size={15} /> : <Bot size={15} />}
      </div>
      <div style={S.botBody}>
        {msg.agent ? (
          <div style={{ fontSize: 11, fontWeight: 600, color: c.muted, marginBottom: 3 }}>
            Support agent
          </div>
        ) : null}
        {thinking ? (
          <div style={S.thinking}>
            <ThinkingDots />
            <span style={S.thinkingText}>{status}</span>
          </div>
        ) : (
          <div className="chat-md">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD}>
              {msg.content}
            </ReactMarkdown>
          </div>
        )}
        {msg.citations.length > 0 ? (
          <div style={S.cites}>
            {msg.citations.map((ct) => (
              <CitationCard key={`${ct.source_id}:${ct.index}`} ct={ct} />
            ))}
          </div>
        ) : null}
        {rateable ? (
          <div style={S.actions}>
            <button aria-label="Helpful" style={S.iconBtn(msg.feedback === "up")} onClick={() => onRate("up")}>
              <ThumbsUp size={14} />
            </button>
            <button aria-label="Not helpful" style={S.iconBtn(msg.feedback === "down")} onClick={() => onRate("down")}>
              <ThumbsDown size={14} />
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ChatPanel({ controller, requireConsent = true }: { controller: ChatController; requireConsent?: boolean }) {
  const { state, send, retry, rate } = useChat(controller);
  const [draft, setDraft] = useState("");
  const [consented, setConsented] = useState(!requireConsent);
  const endRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const t = strings(state.language);
  const dir = dirFor(state.language);
  const streaming = state.conn === "streaming";
  const statusText = t.status[state.status as keyof typeof t.status] ?? t.connecting;
  const hasUserMessage = state.messages.some((m) => m.role === "user");
  const showSuggestions = !hasUserMessage && !streaming && state.conn !== "error";

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [state.messages, state.status]);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
  }, [draft]);

  if (!consented) {
    return (
      <div style={S.root} dir={dir}>
        <div style={S.consent}>
          <div style={{ ...S.avatar, width: 44, height: 44, margin: "0 auto" }}>
            <Bot size={22} />
          </div>
          <strong style={{ fontSize: 17 }}>{t.consentTitle}</strong>
          <p style={{ color: c.muted, margin: 0, fontSize: 13.5, lineHeight: 1.55 }}>{t.consentBody}</p>
          <button style={S.consentBtn} onClick={() => setConsented(true)}>
            {t.consentAccept}
          </button>
        </div>
      </div>
    );
  }

  const submit = (text?: string) => {
    const value = (text ?? draft).trim();
    if (!value || streaming) return;
    if (!text) setDraft("");
    send(value);
  };

  return (
    <div style={S.root} dir={dir}>
      <div style={S.header}>
        <div style={S.avatar}>
          <Bot size={16} />
        </div>
        <div style={S.onlineDot} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{t.assistantName}</div>
          <div style={{ fontSize: 12, color: c.muted }}>{t.assistantSubtitle}</div>
        </div>
      </div>

      <div style={S.list} role="log" aria-live="polite">
        {state.messages.map((m, i) =>
          m.role === "user" ? (
            <div key={m.id || `m${i}`} style={S.userRow}>
              <div style={S.userBubble}>{m.content}</div>
            </div>
          ) : (
            <Assistant key={m.id || `m${i}`} msg={m} status={statusText} onRate={(r) => m.id && rate(m.id, r)} />
          )
        )}

        {showSuggestions ? (
          <div style={S.suggests}>
            {t.suggestions.map((s) => (
              <button key={s} style={S.chip} onClick={() => submit(s)}>
                {s}
              </button>
            ))}
          </div>
        ) : null}
        <div ref={endRef} />
      </div>

      {state.conn === "error" ? (
        <div style={S.errorRow}>
          <span style={{ flex: 1 }}>{t.errorGeneric}</span>
          <button style={S.ghostBtn} onClick={() => retry()}>
            <RotateCw size={13} style={{ verticalAlign: "-2px", marginInlineEnd: 5 }} />
            {t.retry}
          </button>
        </div>
      ) : null}

      <div style={S.composer}>
        <div style={S.inputWrap}>
          <textarea
            ref={taRef}
            rows={1}
            style={S.textarea}
            value={draft}
            placeholder={t.placeholder}
            disabled={streaming}
            aria-label={t.placeholder}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <button
            style={S.sendBtn(!streaming && !!draft.trim())}
            disabled={streaming || !draft.trim()}
            aria-label={t.send}
            onClick={() => submit()}
          >
            <Send size={16} />
          </button>
        </div>
        <button style={S.humanBtn} disabled={streaming} onClick={() => send(t.talkToHuman, { escalate: true })}>
          <UserRound size={14} />
          {t.talkToHuman}
        </button>
      </div>
    </div>
  );
}
