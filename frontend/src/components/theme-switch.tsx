import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/lib/useTheme";
import { cn } from "@/lib/utils";

/** Compact two-state track with both icons always visible (sun fixed left, moon fixed right,
 * a solid thumb slides between them) — the one theme control used everywhere: the console top
 * bar and the full-page auth surfaces (`AuthBrand.tsx`) alike. Toggles light/dark directly
 * (no "system" state — that nuance lives in the fuller `<ThemeToggle>` dropdown, used where a
 * dedicated menu already exists, e.g. the landing page and ops console). */
export function ThemeSwitch({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={() => setTheme(dark ? "light" : "dark")}
      className={cn(
        "relative inline-flex h-8 w-[3.75rem] shrink-0 items-center rounded-full border border-border bg-card shadow-md transition-colors",
        className
      )}
    >
      <Sun className="absolute left-1.5 size-4 text-muted-foreground" />
      <Moon className="absolute right-1.5 size-4 text-muted-foreground" />
      <span
        className={cn(
          "absolute left-0.5 grid size-7 place-items-center rounded-full bg-primary text-primary-foreground shadow-sm transition-transform duration-200",
          dark && "translate-x-[1.75rem]"
        )}
      >
        {dark ? <Moon className="size-3.5" /> : <Sun className="size-3.5" />}
      </span>
    </button>
  );
}
