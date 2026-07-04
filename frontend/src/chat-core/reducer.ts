/**
 * Pure SSE → chat-state reduction. Each event folds into the CURRENT streaming assistant message
 * (always the last message once a turn is in flight). Kept pure + framework-free so it is unit
 * tested directly against the shared fixture (`contracts/sse_events.fixture.json`).
 *
 * Contract mirror ([IMP-FE-5]): answer text arrives ONLY on `token`; all validated control
 * metadata rides the single trailing `final`; `done` closes the turn.
 */

import type { SSEEvent } from "../types/sse";
import type { ChatMessage, ChatState } from "./types";

function patchLastAssistant(state: ChatState, patch: (m: ChatMessage) => ChatMessage): ChatState {
  const msgs = state.messages.slice();
  const i = msgs.length - 1;
  if (i < 0 || msgs[i].role !== "assistant") return state;
  msgs[i] = patch({ ...msgs[i] });
  return { ...state, messages: msgs };
}

export function applyEvent(state: ChatState, ev: SSEEvent): ChatState {
  switch (ev.type) {
    case "status":
      return { ...state, status: ev.stage, conn: "streaming", error: null };
    case "token":
      return patchLastAssistant(state, (m) => ({ ...m, content: m.content + ev.text }));
    case "citation":
      return patchLastAssistant(state, (m) => ({ ...m, citations: [...m.citations, ev.citation] }));
    case "final":
      return patchLastAssistant(
        { ...state, language: ev.detected_language },
        (m) => ({
          ...m,
          tags: ev.tags,
          escalate: ev.escalate,
          escalationReason: ev.escalation_reason,
          answerComplete: ev.answer_complete,
        }),
      );
    case "error":
      return { ...state, error: ev.message, conn: "error", status: null };
    case "done":
      return patchLastAssistant(
        { ...state, ticketState: ev.ticket_state, status: null, conn: "idle" },
        (m) => ({ ...m, id: ev.turn_id || m.id, streaming: false }),
      );
    default:
      return state;
  }
}
