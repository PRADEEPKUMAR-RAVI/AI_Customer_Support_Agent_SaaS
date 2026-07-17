import { create } from "zustand";

interface PresenceState {
  available: boolean;
  setAvailable: (available: boolean) => void;
}

/** Holds the agent's own available/away toggle state, shared between the app-bar control that
 * renders it (`top-bar.tsx`'s `PresenceToggle`) and anything else that might care. Split out of
 * `AgentWorkspacePage.tsx` so the toggle — and its heartbeat, which keeps the backend's Redis-TTL
 * presence key alive — lives in the top bar (rendered on every console page) instead of only
 * while the agent happens to be on `/inbox`; otherwise navigating to Tickets/Overview would let
 * the TTL lapse and silently flip them to "away". */
export const usePresenceStore = create<PresenceState>((set) => ({
  available: false,
  setAvailable: (available) => set({ available }),
}));
