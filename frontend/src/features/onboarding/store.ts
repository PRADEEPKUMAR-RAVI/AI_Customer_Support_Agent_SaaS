import { create } from "zustand";

import type { StepKey } from "./steps";

interface OnboardingStore {
  active: StepKey;
  setActive: (key: StepKey) => void;
  /** "Agent configuration" and "Embed the widget" can't be derived from server data the way
   * every other step is: signup seeds a default persona/welcome_message, and a widget key is
   * minted automatically — so "does data exist" is true for both from the moment the account
   * is created. Tracked here instead, confirmed only by an explicit action (saving the config
   * form / copying the embed snippet). */
  confirmedSteps: Set<StepKey>;
  confirmStep: (key: StepKey) => void;
}

/** The onboarding wizard's navigation state, shared between `OnboardingPage.tsx` (the content)
 * and `app-sidebar.tsx` (the step list, which replaces the normal console nav while setup is
 * incomplete) — they're siblings under `ConsoleLayout`, not parent/child, so this is how a click
 * in the sidebar reaches the page. */
export const useOnboardingStore = create<OnboardingStore>((set) => ({
  active: "industry",
  setActive: (key) => set({ active: key }),
  confirmedSteps: new Set(),
  confirmStep: (key) => set((s) => ({ confirmedSteps: new Set(s.confirmedSteps).add(key) })),
}));
