/**
 * ChatController — the framework-agnostic turn engine behind the SPA hook and the widget.
 *
 * Owns ChatState and drives one turn at a time: push the user message + a streaming assistant
 * placeholder, POST the turn, and fold each SSE event in via the pure reducer. Reconnects replay
 * the SAME client_msg_id (idempotent whole-turn replay). Exposes a store interface
 * (getState/subscribe) so React's useSyncExternalStore (or a Preact equivalent) can bind to it.
 */

import { newClientMsgId, streamWithRetry } from "../lib/sse";
import { applyEvent } from "./reducer";
import { emptyAssistant, userMessage, type ChatState } from "./types";

export interface ChatControllerOptions {
  apiBase: string;
  conversationId: string;
  sessionToken: string;
  welcomeMessage?: string;
  defaultLanguage?: string;
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

  constructor(private readonly opts: ChatControllerOptions) {
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
    this.setState((s) => {
      const messages = s.messages.slice();
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant") messages[messages.length - 1] = emptyAssistant();
      else messages.push(emptyAssistant());
      return { ...s, messages, error: null, conn: "streaming", status: null };
    });
    await this.stream();
  }

  async rate(messageId: string, rating: "up" | "down"): Promise<void> {
    this.setState((s) => ({
      ...s,
      messages: s.messages.map((m) => (m.id === messageId ? { ...m, feedback: rating } : m)),
    }));
    try {
      await fetch(
        `${this.opts.apiBase}/conversations/${this.opts.conversationId}/messages/${messageId}/feedback`,
        {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${this.opts.sessionToken}` },
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
    try {
      await streamWithRetry({
        url: `${this.opts.apiBase}/conversations/${this.opts.conversationId}/messages`,
        body,
        headers: { authorization: `Bearer ${this.opts.sessionToken}` },
        signal: this.abort.signal,
        onEvent: (ev) => this.setState((s) => applyEvent(s, ev)),
      });
    } catch (err) {
      this.setState((s) => ({
        ...s,
        conn: "error",
        status: null,
        error: err instanceof Error ? err.message : "stream failed",
      }));
    }
  }
}
