import { Waypoints } from "lucide-react";
import { Outlet } from "react-router-dom";

/** Centered, single-column shell for the unauthenticated auth flows (login/verify/forgot/reset).
 * Signup gets its own full-bleed split layout (`SignupPage.tsx`) since it's the one page carrying
 * a pitch; these are quick, transactional tasks for a returning user, so they stay a simple
 * centered card — just dressed in the same soft brand glow as the rest of the auth experience. */
export function AuthLayout() {
  return (
    <div className="relative grid min-h-svh place-items-center overflow-hidden bg-background px-4 py-10">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 size-[32rem] -translate-x-1/2 rounded-full bg-brand-500/10 blur-3xl"
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
            <Waypoints className="size-5" />
          </div>
          <span className="text-lg font-semibold tracking-tight">Relay</span>
        </div>
        <Outlet />
      </div>
    </div>
  );
}
