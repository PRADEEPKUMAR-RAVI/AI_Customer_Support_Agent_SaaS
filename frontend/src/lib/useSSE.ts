/**
 * useSSE — React binding over the reconnecting SSE transport ([IMP-FE-1]). A thin wrapper: it
 * owns an AbortController tied to the component lifecycle (auto-cancel on unmount) and delegates
 * reconnect/replay to `streamWithRetry`. chat-core's ChatController is the primary consumer; this
 * hook is here so other FE features can stream one-off turns without re-implementing the plumbing.
 */

import { useCallback, useEffect, useRef } from "react";

import { streamWithRetry, type StreamOptions } from "./sse";

export interface UseSSE {
  start: (
    opts: Omit<StreamOptions, "signal">,
    retry?: { retries?: number; backoffMs?: number },
  ) => Promise<void>;
  stop: () => void;
}

export function useSSE(): UseSSE {
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const start = useCallback(
    (opts: Omit<StreamOptions, "signal">, retry?: { retries?: number; backoffMs?: number }) => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      return streamWithRetry({ ...opts, signal: ac.signal }, retry);
    },
    [],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  return { start, stop };
}
