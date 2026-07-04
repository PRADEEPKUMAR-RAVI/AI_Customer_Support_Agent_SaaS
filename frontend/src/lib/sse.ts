/**
 * Framework-agnostic SSE streaming client.
 *
 * The chat turn is `POST /conversations/{id}/messages` with a Bearer/anon header, so we use
 * `fetch()` + `ReadableStream` (NOT native EventSource, which is GET-only and can't set
 * headers). Reconnect replays the SAME `client_msg_id` — the backend treats a duplicate
 * client_msg_id as idempotent whole-turn replay ([IMP-FE-1]/[T7]); we do NOT keep a
 * per-event replay buffer.
 */

import { parseSSEEvent, type SSEEvent } from "../types/sse";

export interface StreamOptions {
  url: string;
  body: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  onEvent: (event: SSEEvent) => void;
}

/** Parse a raw SSE frame block ("event: x\nid: n\ndata: {...}") into its data payload. */
function dataFromFrame(frame: string): string | null {
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    // `event:` and `id:` lines are transport-only; the payload carries its own `type`.
  }
  return dataLines.length ? dataLines.join("\n") : null;
}

export async function streamTurn(opts: StreamOptions): Promise<void> {
  const res = await fetch(opts.url, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream", ...opts.headers },
    body: JSON.stringify(opts.body),
    credentials: "include",
    signal: opts.signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`stream failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Frames are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const payload = dataFromFrame(frame);
      if (payload) {
        opts.onEvent(parseSSEEvent(JSON.parse(payload)));
      }
    }
  }
}

/**
 * Reconnecting wrapper: on a dropped/failed stream, re-POST the SAME body (which MUST carry a
 * stable `client_msg_id`) so the backend replays the whole turn idempotently ([IMP-FE-1]/[T7])
 * rather than re-running the loop. Aborts (user cancel) are not retried.
 */
export async function streamWithRetry(
  opts: StreamOptions,
  { retries = 2, backoffMs = 400 }: { retries?: number; backoffMs?: number } = {}
): Promise<void> {
  let attempt = 0;
  for (;;) {
    try {
      await streamTurn(opts);
      return;
    } catch (err) {
      if (opts.signal?.aborted || attempt >= retries) throw err;
      attempt += 1;
      await new Promise((r) => setTimeout(r, backoffMs * attempt));
    }
  }
}

/** A stable client_msg_id to reuse across retries of the SAME message. */
export function newClientMsgId(): string {
  return (crypto as Crypto).randomUUID();
}
