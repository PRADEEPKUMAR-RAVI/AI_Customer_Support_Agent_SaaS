/**
 * ChatPanel — the one reusable chat UI ([IMP-FE-2]), rendered by the SPA hosted page/console and
 * (verbatim) inside the widget's Shadow DOM. Layout/colour use React inline styles that READ the
 * design-system CSS variables (with hex fallbacks): inline styles apply via the CSSOM so they are
 * CSP-safe and unaffected by Shadow-DOM encapsulation, while `var(--token)` reads pick up the
 * console tokens (globals.css :root) or the widget tokens (:host). The AI answer is rendered as
 * Markdown, styled by the `.chat-md` rules that live in BOTH globals.css and the widget stylesheet.
 * Chrome locale + direction follow the established `detected_language` ([C7]).
 *
 * Pseudo-class polish (hover/active/focus rings) can't be expressed inline, so a small set of
 * `.csw-*` classes (scoped under `.csw-root`) lives in BOTH globals.css AND the widget's WIDGET_CSS
 * — keep those two blocks in sync. No new @keyframes: the streaming caret reuses `cswblink`,
 * entrances reuse `cswfadein`, the thinking dots reuse `cswbounce`.
 */

import {
  AlertCircle, Bot, Check, ChevronDown, Copy, ExternalLink, Headset, RotateCw,
  Send, Sparkles, ThumbsDown, ThumbsUp, UserRound,
} from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { dirFor, strings, type ChatController, type ChatMessage, type ChromeStrings } from "../../chat-core";
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
  primary: "var(--primary, #1B3C53)",
  primaryFg: "var(--primary-foreground, #ffffff)",
  accent: "var(--accent, #eef2ff)",
  accentFg: "var(--accent-foreground, #3730a3)",
  success: "var(--success, #16a34a)",
  danger: "var(--destructive, #dc2626)",
  font: '"Geist Variable", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
};

const GRADIENT =
  "linear-gradient(150deg, var(--primary, #1B3C53), color-mix(in oklab, var(--primary, #1B3C53) 68%, #000))";
// Reusable layered, single-light-direction depth (composed from the foreground token so it works
// in both themes). Kept out of interactive elements — those get their shadow via .csw-* classes.
const SOFT_SHADOW =
  "0 1px 2px color-mix(in oklab, var(--foreground, #0f172a) 7%, transparent), " +
  "0 6px 16px color-mix(in oklab, var(--foreground, #0f172a) 6%, transparent)";
const tint = (token: string, pct: number, over = "var(--card, #ffffff)") =>
  `color-mix(in oklab, ${token} ${pct}%, ${over})`;

const S = {
  root: {
    display: "flex", flexDirection: "column", height: "100%", minHeight: 0,
    background: c.bg, color: c.fg, fontFamily: c.font, fontSize: 14, lineHeight: 1.5,
  } as React.CSSProperties,
  header: {
    display: "flex", alignItems: "center", gap: 11, padding: "12px 14px",
    borderBottom: `1px solid ${c.border}`, flexShrink: 0,
    boxShadow: `0 1px 0 ${tint("var(--foreground, #0f172a)", 4, "transparent")}`,
    background: c.card,
  } as React.CSSProperties,
  avatarWrap: { position: "relative", flexShrink: 0, lineHeight: 0 } as React.CSSProperties,
  avatar: {
    width: 34, height: 34, borderRadius: 11, display: "grid", placeItems: "center",
    background: GRADIENT, color: c.primaryFg,
    boxShadow: `0 0 0 1px ${tint("var(--foreground, #0f172a)", 8, "transparent")}, 0 2px 6px ${tint("var(--primary, #1B3C53)", 30, "transparent")}`,
  } as React.CSSProperties,
  presenceDot: {
    position: "absolute", insetInlineEnd: -2, bottom: -2, width: 10, height: 10, borderRadius: 999,
    background: c.success, boxShadow: `0 0 0 2px ${c.card}`,
  } as React.CSSProperties,
  list: {
    flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column",
    position: "relative", scrollBehavior: "smooth",
  } as React.CSSProperties,
  userRow: { display: "flex", justifyContent: "flex-end", animation: "cswfadein 0.25s ease-out" } as React.CSSProperties,
  userBubble: (last: boolean): React.CSSProperties => ({
    maxWidth: "82%", padding: "9px 13px",
    borderRadius: last ? "16px 16px 4px 16px" : "16px 16px 14px 16px",
    background: GRADIENT, color: c.primaryFg, whiteSpace: "pre-wrap", wordBreak: "break-word",
    boxShadow: `${SOFT_SHADOW}, inset 0 1px 0 rgba(255,255,255,0.14)`,
  }),
  botRow: { display: "flex", gap: 10, alignItems: "flex-start", animation: "cswfadein 0.25s ease-out" } as React.CSSProperties,
  botAvatar: {
    width: 26, height: 26, borderRadius: 8, display: "grid", placeItems: "center", flexShrink: 0, marginTop: 1,
    background: GRADIENT, color: c.primaryFg,
    boxShadow: `0 1px 4px ${tint("var(--primary, #1B3C53)", 26, "transparent")}`,
  } as React.CSSProperties,
  botSpacer: { width: 26, flexShrink: 0 } as React.CSSProperties,
  botBody: { flex: 1, minWidth: 0, paddingTop: 1 } as React.CSSProperties,
  aiCaption: {
    display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 500,
    color: c.muted, marginBottom: 4,
  } as React.CSSProperties,
  agentCaption: {
    display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 600,
    color: c.accentFg, marginBottom: 4,
  } as React.CSSProperties,
  thinking: { display: "flex", alignItems: "center", gap: 10, minHeight: 22 } as React.CSSProperties,
  thinkingText: { color: c.muted, fontSize: 13 } as React.CSSProperties,
  caret: {
    display: "inline-block", width: 2, height: "1.05em", verticalAlign: "-2px", marginInlineStart: 2,
    borderRadius: 1, background: c.muted, animation: "cswblink 1s step-end infinite",
  } as React.CSSProperties,
  citesLabel: { fontSize: 11, fontWeight: 500, color: c.muted, marginTop: 12, marginBottom: 6 } as React.CSSProperties,
  cites: { display: "flex", flexWrap: "wrap", gap: 6 } as React.CSSProperties,
  cite: {
    display: "inline-flex", alignItems: "center", gap: 7, maxWidth: 240, padding: "6px 9px",
    border: `1px solid ${c.border}`, borderRadius: 10, background: c.card, color: c.fg,
    fontSize: 12, textDecoration: "none",
  } as React.CSSProperties,
  citeN: {
    width: 16, height: 16, borderRadius: 5, background: c.accent, color: c.accentFg,
    fontSize: 10, fontWeight: 600, display: "grid", placeItems: "center", flexShrink: 0,
  } as React.CSSProperties,
  actions: { display: "flex", gap: 2, marginTop: 8 } as React.CSSProperties,
  iconBtn: (on: boolean): React.CSSProperties => ({
    width: 28, height: 28, display: "grid", placeItems: "center", cursor: "pointer",
    border: "none", borderRadius: 7, background: on ? c.accent : "transparent",
    color: on ? c.accentFg : c.muted,
  }),
  systemNote: {
    display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
    margin: "6px 8px", color: c.muted, fontSize: 12,
  } as React.CSSProperties,
  systemRule: { height: 1, flex: 1, maxWidth: 48, background: c.border } as React.CSSProperties,
  suggests: {
    display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12, marginInlineStart: 36,
  } as React.CSSProperties,
  chip: {
    padding: "7px 12px", borderRadius: 999, cursor: "pointer", fontSize: 13, fontFamily: "inherit",
    border: `1px solid ${c.border}`, background: c.card, color: c.fg, textAlign: "start",
    animation: "cswfadein 0.3s ease-out both",
  } as React.CSSProperties,
  jumpWrap: {
    position: "absolute", insetInlineStart: "50%", transform: "translateX(-50%)", bottom: 10, zIndex: 2,
  } as React.CSSProperties,
  jumpBtn: {
    display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 12px", cursor: "pointer",
    border: `1px solid ${c.border}`, borderRadius: 999, background: c.card, color: c.fg,
    fontSize: 12.5, fontFamily: "inherit", fontWeight: 500, boxShadow: SOFT_SHADOW,
  } as React.CSSProperties,
  errorBanner: {
    display: "flex", alignItems: "center", gap: 10, margin: "0 12px 10px", padding: "9px 12px",
    color: c.danger, fontSize: 13, borderRadius: 10,
    background: tint("var(--destructive, #dc2626)", 9),
    border: `1px solid ${tint("var(--destructive, #dc2626)", 28)}`,
  } as React.CSSProperties,
  composer: { borderTop: `1px solid ${c.border}`, padding: 12, flexShrink: 0, background: c.card } as React.CSSProperties,
  inputWrap: {
    display: "flex", alignItems: "flex-end", gap: 8, border: `1px solid ${c.border}`,
    borderRadius: 14, background: c.bg, padding: 6, paddingInlineStart: 12,
  } as React.CSSProperties,
  textarea: {
    flex: 1, resize: "none", border: "none", outline: "none", background: "transparent",
    color: c.fg, fontFamily: "inherit", fontSize: 14, lineHeight: 1.5, maxHeight: 120, padding: "6px 0",
  } as React.CSSProperties,
  sendBtn: (enabled: boolean): React.CSSProperties => ({
    width: 34, height: 34, display: "grid", placeItems: "center", flexShrink: 0,
    cursor: enabled ? "pointer" : "not-allowed",
    border: "none", borderRadius: 10, background: GRADIENT, color: c.primaryFg, opacity: enabled ? 1 : 0.45,
  }),
  humanBtn: {
    display: "inline-flex", alignItems: "center", gap: 6, marginTop: 8, padding: "5px 11px", cursor: "pointer",
    border: `1px solid ${c.border}`, borderRadius: 999, background: "transparent", color: c.muted,
    fontSize: 12.5, fontFamily: "inherit",
  } as React.CSSProperties,
  consent: { flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", padding: 24 } as React.CSSProperties,
  consentCard: {
    display: "flex", flexDirection: "column", alignItems: "center", gap: 12, maxWidth: 340,
    padding: "28px 24px", textAlign: "center", borderRadius: 18,
    border: `1px solid ${c.border}`, background: c.card, boxShadow: SOFT_SHADOW,
  } as React.CSSProperties,
  consentBtn: {
    marginTop: 4, padding: "10px 18px", borderRadius: 11, cursor: "pointer", border: "none",
    background: GRADIENT, color: c.primaryFg, fontSize: 14, fontFamily: "inherit", fontWeight: 500,
    boxShadow: `0 2px 8px ${tint("var(--primary, #1B3C53)", 34, "transparent")}`,
  } as React.CSSProperties,
  ghostBtn: {
    display: "inline-flex", alignItems: "center", gap: 5, padding: "7px 13px", borderRadius: 9,
    cursor: "pointer", fontSize: 13, fontFamily: "inherit",
    border: `1px solid ${c.border}`, background: c.card, color: c.fg,
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
      <a className="csw-cite" style={S.cite} href={ct.source_url} target="_blank" rel="noreferrer noopener">
        {inner}
        <ExternalLink size={12} style={{ color: c.muted, flexShrink: 0 }} />
      </a>
    );
  }
  return <span className="csw-cite" style={S.cite}>{inner}</span>;
}

function Assistant({
  msg, status, firstOfGroup, showAiCaption, t, onRate,
}: {
  msg: ChatMessage;
  status: string;
  firstOfGroup: boolean;
  showAiCaption: boolean;
  t: ChromeStrings;
  onRate: (r: "up" | "down") => void;
}) {
  // Human-agent replies aren't rateable (the feedback endpoint only accepts AI messages) and get
  // a distinct avatar + label so the customer can see a person has taken over.
  const rateable = !msg.streaming && msg.id !== "" && msg.id !== "welcome" && !msg.agent;
  const copyable = !msg.streaming && !msg.agent && !!msg.content;
  const thinking = msg.streaming && !msg.content;
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(msg.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard may be blocked in some embedded contexts — never throw into the host page */
    }
  };

  return (
    <div style={S.botRow}>
      {firstOfGroup ? (
        <div style={S.botAvatar}>{msg.agent ? <Headset size={15} /> : <Bot size={15} />}</div>
      ) : (
        <div style={S.botSpacer} aria-hidden />
      )}
      <div style={S.botBody}>
        {msg.agent && firstOfGroup ? (
          <div style={S.agentCaption}>
            <Headset size={12} />
            {t.agentLabel}
          </div>
        ) : showAiCaption ? (
          <div style={S.aiCaption}>
            <Sparkles size={11} />
            {t.aiAgent}
          </div>
        ) : null}

        {thinking ? (
          <div style={S.thinking} role="status">
            <ThinkingDots />
            <span style={S.thinkingText}>{status}</span>
          </div>
        ) : (
          <div className="chat-md">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD}>
              {msg.content}
            </ReactMarkdown>
            {msg.streaming && msg.content ? <span style={S.caret} aria-hidden /> : null}
          </div>
        )}

        {msg.citations.length > 0 ? (
          <>
            <div style={S.citesLabel}>{t.sources}</div>
            <div style={S.cites}>
              {msg.citations.map((ct) => (
                <CitationCard key={`${ct.source_id}:${ct.index}`} ct={ct} />
              ))}
            </div>
          </>
        ) : null}

        {copyable || rateable ? (
          <div style={S.actions}>
            {copyable ? (
              <button
                className="csw-iconbtn"
                aria-label={copied ? t.copied : t.copy}
                style={S.iconBtn(false)}
                onClick={copy}
              >
                {copied ? <Check size={14} style={{ color: c.success }} /> : <Copy size={14} />}
              </button>
            ) : null}
            {rateable ? (
              <>
                <button className="csw-iconbtn" aria-label={t.thumbUp} style={S.iconBtn(msg.feedback === "up")} onClick={() => onRate("up")}>
                  <ThumbsUp size={14} />
                </button>
                <button className="csw-iconbtn" aria-label={t.thumbDown} style={S.iconBtn(msg.feedback === "down")} onClick={() => onRate("down")}>
                  <ThumbsDown size={14} />
                </button>
              </>
            ) : null}
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
  const [atBottom, setAtBottom] = useState(true);
  const listRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const t = strings(state.language);
  const dir = dirFor(state.language);
  const streaming = state.conn === "streaming";
  const statusText = t.status[state.status as keyof typeof t.status] ?? t.connecting;
  const hasUserMessage = state.messages.some((m) => m.role === "user");
  const showSuggestions = !hasUserMessage && !streaming && state.conn !== "error";
  // Honest handoff: a human has ACTUALLY taken over only once one of their replies is in the
  // transcript. Being merely escalated (queued) or claimed no longer flips the chrome — the AI
  // keeps helping until the agent's first message arrives, mirroring the backend state gate
  // (conversation_service._agent_has_replied). The inline "connecting you with a human" note still
  // signals the pending hand-off in the meantime.
  const conversationHasHuman = state.messages.some((m) => m.agent);
  const handedOff = conversationHasHuman;

  // Non-intrusive auto-scroll: only follow the stream while the reader is already near the bottom,
  // so scrolling up to re-read a long answer isn't yanked back down. Otherwise the "jump to latest"
  // pill lets them return on demand. Purely local scroll state — no backend data.
  const onListScroll = () => {
    const el = listRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 120);
  };
  useEffect(() => {
    if (atBottom) endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [state.messages, state.status, atBottom]);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
  }, [draft]);

  if (!consented) {
    return (
      <div className="csw-root" style={S.root} dir={dir}>
        <div style={S.consent}>
          <div style={S.consentCard}>
            <div style={{ ...S.avatar, width: 48, height: 48, borderRadius: 15 }}>
              <Bot size={24} />
            </div>
            <strong style={{ fontSize: 17 }}>{t.consentTitle}</strong>
            <p style={{ color: c.muted, margin: 0, fontSize: 13.5, lineHeight: 1.55 }}>{t.consentBody}</p>
            <button className="csw-send" style={S.consentBtn} onClick={() => setConsented(true)}>
              {t.consentAccept}
            </button>
          </div>
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
    <div className="csw-root" style={S.root} dir={dir}>
      <div style={S.header}>
        <div style={S.avatarWrap}>
          <div style={S.avatar}>{handedOff ? <Headset size={17} /> : <Bot size={17} />}</div>
          <span style={S.presenceDot} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{handedOff ? t.agentLabel : t.assistantName}</div>
          <div style={{ fontSize: 12, color: c.muted }}>{handedOff ? t.handoffSubtitle : t.assistantSubtitle}</div>
        </div>
      </div>

      <div ref={listRef} style={S.list} role="log" aria-live="polite" onScroll={onListScroll}>
        {state.messages.map((m, i) => {
          const prev = state.messages[i - 1];
          const firstOfGroup =
            !prev || prev.role !== m.role || Boolean(prev.agent) !== Boolean(m.agent);
          const next = state.messages[i + 1];
          const lastOfGroup =
            !next || next.role !== m.role || Boolean(next.agent) !== Boolean(m.agent);
          const mt = i === 0 ? 0 : firstOfGroup ? 18 : 4;
          const key = m.id || `m${i}`;

          const row =
            m.role === "user" ? (
              <div style={{ ...S.userRow, marginTop: mt }}>
                <div style={S.userBubble(lastOfGroup)}>{m.content}</div>
              </div>
            ) : (
              <div style={{ marginTop: mt }}>
                <Assistant
                  msg={m}
                  status={statusText}
                  firstOfGroup={firstOfGroup}
                  // Only label AI turns when a human is ALSO in the transcript — otherwise the header
                  // already says it's the assistant and per-message captions would be noise.
                  showAiCaption={firstOfGroup && !m.agent && conversationHasHuman}
                  t={t}
                  onRate={(r) => m.id && rate(m.id, r)}
                />
              </div>
            );

          return (
            <Fragment key={key}>
              {row}
              {m.escalate ? (
                <div style={S.systemNote}>
                  <span style={S.systemRule} />
                  {t.connectingHuman}
                  <span style={S.systemRule} />
                </div>
              ) : null}
            </Fragment>
          );
        })}

        {showSuggestions ? (
          <div style={S.suggests}>
            {t.suggestions.map((s, i) => (
              <button
                key={s}
                className="csw-chip"
                style={{ ...S.chip, animationDelay: `${Math.min(i * 60, 240)}ms` }}
                onClick={() => submit(s)}
              >
                {s}
              </button>
            ))}
          </div>
        ) : null}
        <div ref={endRef} />

        {!atBottom ? (
          <div style={S.jumpWrap}>
            <button
              className="csw-jump"
              style={S.jumpBtn}
              aria-label={t.jumpToLatest}
              onClick={() => {
                setAtBottom(true);
                endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
              }}
            >
              <ChevronDown size={14} />
              {t.jumpToLatest}
            </button>
          </div>
        ) : null}
      </div>

      {state.conn === "error" ? (
        <div style={S.errorBanner}>
          <AlertCircle size={15} style={{ flexShrink: 0 }} />
          <span style={{ flex: 1 }}>{t.errorGeneric}</span>
          <button className="csw-ghost" style={S.ghostBtn} onClick={() => retry()}>
            <RotateCw size={13} />
            {t.retry}
          </button>
        </div>
      ) : null}

      <div style={S.composer}>
        <div className="csw-composer" style={S.inputWrap}>
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
            className="csw-send"
            style={S.sendBtn(!streaming && !!draft.trim())}
            disabled={streaming || !draft.trim()}
            aria-label={t.send}
            onClick={() => submit()}
          >
            <Send size={16} />
          </button>
        </div>
        <button className="csw-ghost" style={S.humanBtn} disabled={streaming} onClick={() => send(t.talkToHuman, { escalate: true })}>
          <UserRound size={14} />
          {t.talkToHuman}
        </button>
      </div>
    </div>
  );
}
