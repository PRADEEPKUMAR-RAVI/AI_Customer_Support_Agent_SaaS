import type { LucideIcon } from "lucide-react";
import { create } from "zustand";

interface Banner {
  icon?: LucideIcon;
  title: string;
  subtitle: string;
}

interface PageBannerState {
  banner: Banner | null;
  set: (banner: Banner) => void;
  clear: () => void;
}

/** Lets a page hand the top bar a contextual icon/title/subtitle to show in place of the plain
 * breadcrumb — used by the onboarding wizard so the app bar reflects whichever step is active,
 * without threading step state through `ConsoleLayout`/`TopBar` (siblings of the routed page,
 * not ancestors of it). Cleared on unmount so leaving the page restores the normal breadcrumb. */
export const usePageBanner = create<PageBannerState>((set) => ({
  banner: null,
  set: (banner) => set({ banner }),
  clear: () => set({ banner: null }),
}));
