/**
 * TS mirror of the backend SSE union (`app/schemas/sse.py`) — the frontend half of the
 * drift gate. Keep field-for-field in sync; the shared fixture
 * (`contracts/sse_events.fixture.json`) is asserted against BOTH sides.
 *
 * Design: the answer streams ONLY on `token` events; all validated control metadata rides
 * the single trailing `final` event.
 */

export type StatusStage = "retrieving" | "looking_up" | "generating" | "waiting";

export interface StatusEvent {
  type: "status";
  stage: StatusStage;
}

export interface TokenEvent {
  type: "token";
  text: string;
}

export interface Citation {
  index: number;
  source_id: string;
  title: string;
  page_number?: number; // file sources -> "from <file>, p.<n>"
  source_url?: string; // crawled pages -> clickable link
}

export interface CitationEvent {
  type: "citation";
  citation: Citation;
}

export interface Tag {
  name: string;
  status: "approved" | "pending";
}

export interface FinalEvent {
  type: "final";
  answer_complete: boolean;
  detected_language: string; // BCP-47
  tags: Tag[];
  retrieval_hits: number;
  escalate: boolean;
  escalation_reason?: string; // canonical enum value
  advisory_confidence?: number; // observability only, NOT the escalation trigger
}

export interface ErrorEvent {
  type: "error";
  code: string;
  message: string;
}

export interface DoneEvent {
  type: "done";
  turn_id: string;
  ticket_state: string;
}

export type SSEEvent =
  | StatusEvent
  | TokenEvent
  | CitationEvent
  | FinalEvent
  | ErrorEvent
  | DoneEvent;

const STAGES: readonly StatusStage[] = ["retrieving", "looking_up", "generating", "waiting"];

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

/**
 * Runtime validator + type-narrower. Throws on an unknown `type` or a malformed payload —
 * this is what fails CI if the backend union drifts from this mirror.
 */
export function parseSSEEvent(data: unknown): SSEEvent {
  if (!isObject(data) || typeof data.type !== "string") {
    throw new Error(`SSE event is not an object with a string 'type': ${JSON.stringify(data)}`);
  }
  switch (data.type) {
    case "status":
      if (!STAGES.includes(data.stage as StatusStage)) {
        throw new Error(`invalid status stage: ${String(data.stage)}`);
      }
      return { type: "status", stage: data.stage as StatusStage };
    case "token":
      if (typeof data.text !== "string") throw new Error("token.text must be a string");
      return { type: "token", text: data.text };
    case "citation": {
      const c = data.citation;
      if (!isObject(c) || typeof c.index !== "number" || typeof c.source_id !== "string" || typeof c.title !== "string") {
        throw new Error("malformed citation event");
      }
      return {
        type: "citation",
        citation: {
          index: c.index,
          source_id: c.source_id,
          title: c.title,
          page_number: typeof c.page_number === "number" ? c.page_number : undefined,
          source_url: typeof c.source_url === "string" ? c.source_url : undefined,
        },
      };
    }
    case "final":
      if (typeof data.detected_language !== "string") {
        throw new Error("final.detected_language must be a string");
      }
      return {
        type: "final",
        answer_complete: Boolean(data.answer_complete),
        detected_language: data.detected_language,
        tags: Array.isArray(data.tags) ? (data.tags as Tag[]) : [],
        retrieval_hits: typeof data.retrieval_hits === "number" ? data.retrieval_hits : 0,
        escalate: Boolean(data.escalate),
        escalation_reason:
          typeof data.escalation_reason === "string" ? data.escalation_reason : undefined,
        advisory_confidence:
          typeof data.advisory_confidence === "number" ? data.advisory_confidence : undefined,
      };
    case "error":
      if (typeof data.code !== "string" || typeof data.message !== "string") {
        throw new Error("malformed error event");
      }
      return { type: "error", code: data.code, message: data.message };
    case "done":
      if (typeof data.turn_id !== "string" || typeof data.ticket_state !== "string") {
        throw new Error("malformed done event");
      }
      return { type: "done", turn_id: data.turn_id, ticket_state: data.ticket_state };
    default:
      throw new Error(`unknown SSE event type: ${data.type}`);
  }
}
