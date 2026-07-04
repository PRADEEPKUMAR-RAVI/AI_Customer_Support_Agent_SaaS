/**
 * chat-core reducer test — folds the SHARED SSE fixture (the same one the backend + FE contract
 * gates use) into chat state and asserts a coherent assistant message. If the backend turn shape
 * drifts, this breaks alongside the contract gate.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { parseSSEEvent } from "../types/sse";
import { applyEvent } from "./reducer";
import { emptyAssistant, userMessage, type ChatState } from "./types";

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURE = resolve(here, "../../../contracts/sse_events.fixture.json");

function freshState(): ChatState {
  return {
    messages: [userMessage("c1", "What is your return policy?"), emptyAssistant()],
    status: null,
    conn: "idle",
    ticketState: "new",
    language: "en",
    error: null,
  };
}

describe("chat-core reducer", () => {
  const events = (JSON.parse(readFileSync(FIXTURE, "utf-8")) as unknown[]).map((e) => parseSSEEvent(e));

  it("folds a full turn into a coherent assistant message", () => {
    let state = freshState();
    for (const ev of events) state = applyEvent(state, ev);
    const assistant = state.messages[state.messages.length - 1];

    expect(assistant.role).toBe("assistant");
    expect(assistant.content).toBe("Your return policy is 30 days."); // two tokens concatenated in order
    expect(assistant.citations).toHaveLength(2);
    expect(assistant.tags).toEqual([{ name: "order_status", status: "approved" }]);
    expect(assistant.escalate).toBe(false);
    expect(assistant.answerComplete).toBe(true);
    expect(assistant.streaming).toBe(false); // `done` closed the turn
    expect(assistant.id).toBe("turn_abc123"); // `done` stamped the turn_id
    expect(state.conn).toBe("idle");
    expect(state.status).toBeNull();
    expect(state.ticketState).toBe("ai_handling");
    expect(state.language).toBe("en");
  });

  it("token events only mutate the trailing assistant message", () => {
    let state = freshState();
    state = applyEvent(state, { type: "token", text: "Hello" });
    expect(state.messages[0].content).toBe("What is your return policy?"); // user message untouched
    expect(state.messages[1].content).toBe("Hello");
    expect(state.conn).toBe("idle");
  });

  it("an error event surfaces without corrupting the transcript", () => {
    let state = freshState();
    state = applyEvent(state, { type: "error", code: "busy", message: "Another message is being processed." });
    expect(state.conn).toBe("error");
    expect(state.status).toBeNull();
    expect(state.error).toContain("processed");
    expect(state.messages).toHaveLength(2);
  });
});
