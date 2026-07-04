/** React binding for chat-core's ChatController (via useSyncExternalStore). Keeps the framework
 * layer thin — all turn logic lives in the framework-agnostic controller so the widget reuses it. */

import { useCallback, useSyncExternalStore } from "react";

import type { ChatController, ChatState } from "../../chat-core";

export interface UseChat {
  state: ChatState;
  send: (content: string, opts?: { escalate?: boolean; contactEmail?: string }) => void;
  retry: () => void;
  rate: (messageId: string, rating: "up" | "down") => void;
  cancel: () => void;
}

export function useChat(controller: ChatController): UseChat {
  const state = useSyncExternalStore(controller.subscribe, controller.getState, controller.getState);
  const send = useCallback(
    (content: string, opts?: { escalate?: boolean; contactEmail?: string }) => {
      void controller.send(content, opts);
    },
    [controller],
  );
  const retry = useCallback(() => void controller.retry(), [controller]);
  const rate = useCallback((id: string, r: "up" | "down") => void controller.rate(id, r), [controller]);
  const cancel = useCallback(() => controller.cancel(), [controller]);
  return { state, send, retry, rate, cancel };
}
