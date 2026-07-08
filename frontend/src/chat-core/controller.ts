/**
 * ChatController — the framework-agnostic turn engine behind the SPA hook and the widget.
 *
 * Owns ChatState and drives one turn at a time: push the user message + a streaming assistant
 * placeholder, POST the turn, and fold each SSE event in via the pure reducer. Reconnects replay
 * the SAME client_msg_id (idempotent whole-turn replay). Exposes a store interface
 * (getState/subscribe) so React's useSyncExternalStore (or a Preact equivalent) can bind to it.
 *
 * Self-healing: a persisted widget session can go stale (the conversation was pruned/expired, or
 * the DB was reseeded), which the backend reports as a `not_found` error on the turn. When that
 * happens we mint a FRESH session via `onReauth` and transparently retry the same message once —
 * so a stale localStorage session never wedges the widget (it used to fail every turn forever).
 */

import { newClientMsgId, streamWithRetry } from "../lib/sse";
import { applyEvent } from "./reducer";
import { agentMessage, emptyAssistant, userMessage, type ChatState } from "./types";

export interface ChatControllerOptions {
  apiBase: string;
  conversationId: string;
  sessionToken: string;
  welcomeMessage?: string;
  defaultLanguage?: string;
  /** Mint a fresh session when the current one is rejected as `not_found`. Returns the new
   * (conversationId, sessionToken), or null if a fresh session couldn't be obtained. */
  onReauth?: () => Promise<{ conversationId: string; sessionToken: string } | null>;
}

interface PendingTurn {
  clientMsgId: string;
  content: string;
  escalate: boolean;
  contactEmail?: string;
}

export class ChatController {
  private state: ChatState;
  private readonly listeners = new Set<() => void>();
  private abort: AbortController | null = null;
  private pending: PendingTurn | null = null;
  // Mutable so onReauth can swap in a fresh session without rebuilding the controller.
  private conversationId: string;
  private sessionToken: string;
  // At most one transparent re-auth per user-initiated turn (prevents a reauth↔not_found loop).
  private reauthedThisTurn = false;
  // Live updates: poll the transcript for HUMAN-agent replies (the AI goes silent once a ticket is
  // escalated, so the customer would otherwise never see the human's messages). We fold in agent
  // messages by server id — the one message class the widget can't produce locally — so there is
  // no risk of duplicating the customer/AI turns this controller already renders.
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private readonly seenAgentIds = new Set<string>();

  constructor(private readonly opts: ChatControllerOptions) {
    this.conversationId = opts.conversationId;
    this.sessionToken = opts.sessionToken;
    this.state = {
      messages: opts.welcomeMessage
        ? [{ ...emptyAssistant(), id: "welcome", content: opts.welcomeMessage, streaming: false, answerComplete: true }]
        : [],
      status: null,
      conn: "idle",
      ticketState: "new",
      language: opts.defaultLanguage || "en",
      error: null,
    };
  }

  // --- store interface (useSyncExternalStore) ---
  getState = (): ChatState => this.state;
  subscribe = (cb: () => void): (() => void) => {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  };

  private setState(next: (s: ChatState) => ChatState): void {
    this.state = next(this.state);
    for (const l of this.listeners) l();
  }

  // --- actions ---
  async send(content: string, opts: { escalate?: boolean; contactEmail?: string } = {}): Promise<void> {
    const text = content.trim();
    if (this.state.conn === "streaming" || (!text && !opts.escalate)) return;
    const clientMsgId = newClientMsgId();
    this.pending = { clientMsgId, content: text, escalate: opts.escalate ?? false, contactEmail: opts.contactEmail };
    this.reauthedThisTurn = false; // fresh user turn → allow one transparent re-auth
    this.setState((s) => ({
      ...s,
      error: null,
      conn: "streaming",
      status: null,
      messages: [...s.messages, userMessage(clientMsgId, text || "🗣"), emptyAssistant()],
    }));
    await this.stream();
  }

  /** Re-run the last turn with the SAME client_msg_id → backend replays instead of re-executing. */
  async retry(): Promise<void> {
    if (!this.pending || this.state.conn === "streaming") return;
    this.reauthedThisTurn = false; // a manual retry may also re-auth once
    this.resetAssistantPlaceholder();
    await this.stream();
  }

  async rate(messageId: string, rating: "up" | "down"): Promise<void> {
    this.setState((s) => ({
      ...s,
      messages: s.messages.map((m) => (m.id === messageId ? { ...m, feedback: rating } : m)),
    }));
    try {
      await fetch(
        `${this.opts.apiBase}/conversations/${this.conversationId}/messages/${messageId}/feedback`,
        {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${this.sessionToken}` },
          body: JSON.stringify({ rating }),
        },
      );
    } catch {
      /* optimistic — a failed rating is non-critical */
    }
  }

  cancel(): void {
    this.abort?.abort();
    this.setState((s) => (s.conn === "streaming" ? { ...s, conn: "idle", status: null } : s));
  }

  // --- live updates (human-agent replies) ---

  /** Start polling the transcript so a HUMAN agent's replies appear in the customer's chat. Once a
   * ticket is escalated the AI stops answering, so without this the customer never sees the human.
   * Idempotent (a second call is a no-op); pair with stopLiveUpdates() on unmount. A production
   * build could swap this for an SSE/pub-sub push, but polling needs no extra infra and is robust. */
  startLiveUpdates(intervalMs = 4000): void {
    if (this.pollTimer !== null) return;
    void this.pollForAgentReplies(); // check immediately, then on the interval
    this.pollTimer = setInterval(() => {
      // Skip while a turn is streaming (don't fetch mid-turn) and while the tab is hidden.
      if (this.state.conn === "streaming") return;
      if (typeof document !== "undefined" && document.hidden) return;
      void this.pollForAgentReplies();
    }, intervalMs);
  }

  stopLiveUpdates(): void {
    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  /** Fetch the transcript and fold in any human-agent replies not already shown. Errors are
   * swallowed (a transient/stale fetch just retries next tick) — never surfaced as a chat error. */
  private async pollForAgentReplies(): Promise<void> {
    if (this.state.conn === "streaming") return;
    let messages: Array<{ id: string; role: string; content: string }>;
    try {
      const res = await fetch(`${this.opts.apiBase}/conversations/${this.conversationId}`, {
        headers: { authorization: `Bearer ${this.sessionToken}` },
      });
      if (!res.ok) return;
      const data = (await res.json()) as { messages?: Array<{ id: string; role: string; content: string }> };
      messages = data.messages ?? [];
    } catch {
      return;
    }
    const fresh = messages.filter((m) => m.role === "agent" && m.id && !this.seenAgentIds.has(m.id));
    if (!fresh.length) return;
    for (const m of fresh) this.seenAgentIds.add(m.id);
    this.setState((s) => ({
      ...s,
      messages: [...s.messages, ...fresh.map((m) => agentMessage(m.id, m.content))],
    }));
  }

  /** Reset the trailing assistant bubble to an empty streaming placeholder (for retry/reauth). */
  private resetAssistantPlaceholder(): void {
    this.setState((s) => {
      const messages = s.messages.slice();
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant") messages[messages.length - 1] = emptyAssistant();
      else messages.push(emptyAssistant());
      return { ...s, messages, error: null, conn: "streaming", status: null };
    });
  }

  private async stream(): Promise<void> {
    const turn = this.pending;
    if (!turn) return;
    this.abort = new AbortController();
    const body: Record<string, unknown> = {
      client_msg_id: turn.clientMsgId,
      content: turn.content || " ",
      escalate_request: turn.escalate,
    };
    if (turn.contactEmail) body.contact_email = turn.contactEmail;
    let sessionInvalid = false;
    try {
      await streamWithRetry({
        url: `${this.opts.apiBase}/conversations/${this.conversationId}/messages`,
        body,
        headers: { authorization: `Bearer ${this.sessionToken}` },
        signal: this.abort.signal,
        onEvent: (ev) => {
          // A stale/expired session surfaces as a `not_found` error frame — capture it so we can
          // transparently re-mint + retry instead of folding a dead-end error into the UI.
          if (ev.type === "error" && ev.code === "not_found" && this.opts.onReauth && !this.reauthedThisTurn) {
            sessionInvalid = true;
            return;
          }
          this.setState((s) => applyEvent(s, ev));
        },
      });
    } catch (err) {
      this.setState((s) => ({
        ...s,
        conn: "error",
        status: null,
        error: err instanceof Error ? err.message : "stream failed",
      }));
      return;
    }

    if (sessionInvalid && this.opts.onReauth && !this.reauthedThisTurn) {
      this.reauthedThisTurn = true;
      const fresh = await this.opts.onReauth().catch(() => null);
      if (fresh) {
        this.conversationId = fresh.conversationId;
        this.sessionToken = fresh.sessionToken;
        this.seenAgentIds.clear(); // new conversation → old agent-message ids no longer apply
        this.resetAssistantPlaceholder();
        await this.stream(); // retry the same pending turn on the fresh session
        return;
      }
      // Re-mint failed → surface a real error rather than silently hanging.
      this.setState((s) => ({ ...s, conn: "error", status: null, error: "Session expired — please reload." }));
    }
  }
}
