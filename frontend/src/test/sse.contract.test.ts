/**
 * SSE contract drift gate (frontend half) — checkpoint item #3.
 * Every event in the shared fixture must pass the FE `parseSSEEvent`, and the sequence must
 * contain the trailing `final` control envelope. The backend runs the mirror of this test.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { parseSSEEvent, type SSEEvent } from "../types/sse";

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURE = resolve(here, "../../../contracts/sse_events.fixture.json");

describe("SSE contract", () => {
  const events = JSON.parse(readFileSync(FIXTURE, "utf-8")) as unknown[];

  it("has a non-trivial fixture", () => {
    expect(events.length).toBeGreaterThanOrEqual(6);
  });

  it("every fixture event validates against the FE union", () => {
    const parsed: SSEEvent[] = events.map((e) => parseSSEEvent(e));
    expect(parsed[0].type).toBe("status");
    expect(parsed.some((e) => e.type === "final")).toBe(true);
    expect(parsed[parsed.length - 1].type).toBe("done");
  });

  it("rejects an unknown event type", () => {
    expect(() => parseSSEEvent({ type: "nope" })).toThrow();
  });

  it("rejects a malformed final event", () => {
    expect(() => parseSSEEvent({ type: "final" })).toThrow(); // missing detected_language
  });
});
