/**
 * chat-core — framework-agnostic chat state ([IMP-FE-2]). The logic (SSE reduction, session,
 * i18n, the controller) is authored ONCE here and rendered by the React SPA and the Preact
 * widget alike. No React/Preact imports in this directory.
 */

import type { Citation, Tag } from "../types/sse";

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string; // user: client_msg_id · assistant: turn_id (once the `done` event lands)
  role: ChatRole;
  content: string;
  streaming: boolean; // an assistant message still receiving `token` events
  citations: Citation[];
  tags: Tag[];
  escalate: boolean;
  escalationReason?: string;
  answerComplete: boolean;
  feedback?: "up" | "down"; // thumbs, once rated
}

export type ConnState = "idle" | "streaming" | "error";

export interface ChatState {
  messages: ChatMessage[];
  status: string | null; // live status stage (retrieving | looking_up | generating | waiting)
  conn: ConnState;
  ticketState: string;
  language: string; // established language (BCP-47) — drives chrome locale + dir ([C7])
  error: string | null;
}

export function emptyAssistant(): ChatMessage {
  return {
    id: "", role: "assistant", content: "", streaming: true,
    citations: [], tags: [], escalate: false, answerComplete: false,
  };
}

export function userMessage(id: string, content: string): ChatMessage {
  return {
    id, role: "user", content, streaming: false,
    citations: [], tags: [], escalate: false, answerComplete: false,
  };
}
