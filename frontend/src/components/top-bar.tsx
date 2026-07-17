import { useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/app/providers";
import { ThemeSwitch } from "@/components/theme-switch";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { STEPS } from "@/features/onboarding/steps";
import { useOnboardingProgress } from "@/features/onboarding/useOnboardingProgress";
import { useOnboardingStatus } from "@/features/onboarding/useOnboardingStatus";
import { api, unwrap } from "@/lib/api";
import { usePageBanner } from "@/lib/pageBanner";
import { usePresenceStore } from "@/lib/presence";
import { hasPermission } from "@/lib/rbac";
import { cn } from "@/lib/utils";

const HEARTBEAT_INTERVAL_MS = 20_000;

/** Only mounted for agents (see `showPresence` below) — owns the presence mutation and its
 * heartbeat, moved here from `AgentWorkspacePage` so it keeps running (and the backend's
 * Redis-TTL presence key stays alive) no matter which console page the agent is on, not just
 * while they happen to be looking at `/inbox`. A two-sided switch, not a chip + toggle pair —
 * one control, one state. */
function PresenceToggle() {
  const available = usePresenceStore((s) => s.available);
  const setAvailable = usePresenceStore((s) => s.setAvailable);

  const presence = useMutation({
    mutationFn: async (status: "available" | "away") =>
      unwrap(await api.POST("/api/v1/agents/presence", { body: { status } })),
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't update presence"),
  });

  useEffect(() => {
    if (!available) return undefined;
    const id = setInterval(() => presence.mutate("available"), HEARTBEAT_INTERVAL_MS);
    // Backgrounded tabs throttle setInterval and can let the presence TTL lapse — send an
    // immediate heartbeat on regaining visibility rather than waiting for the next throttled tick.
    const onVisible = () => {
      if (document.visibilityState === "visible") presence.mutate("available");
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // presence is a stable useMutation object; only `available` should re-arm this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [available]);

  function set(next: boolean) {
    setAvailable(next);
    presence.mutate(next ? "available" : "away");
  }

  return (
    <div className="hidden items-center rounded-full border bg-muted p-0.5 sm:flex" role="group" aria-label="Availability">
      <button
        type="button"
        onClick={() => set(false)}
        className={cn(
          "rounded-full px-3 py-1 text-xs font-medium transition-colors",
          !available ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
        )}
        aria-pressed={!available}
      >
        Away
      </button>
      <button
        type="button"
        onClick={() => set(true)}
        className={cn(
          "rounded-full px-3 py-1 text-xs font-medium transition-colors",
          available ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
        )}
        aria-pressed={available}
      >
        Available
      </button>
    </div>
  );
}

/** Only mounted while onboarding is in progress (see `showProgress` below) — keeps the several
 * resource queries `useOnboardingProgress` fans out to (sources, datasets, domains, staff…) from
 * firing for every user on every page. Moved here from the left rail so it sits next to the
 * theme switch instead of taking up space in the step list. */
function SetupProgress() {
  const { completed } = useOnboardingProgress();
  const pct = Math.round((completed / STEPS.length) * 100);

  return (
    <div className="hidden w-32 flex-col gap-1 sm:flex">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium">Setup progress</span>
        <span className="tabular-nums text-muted-foreground">
          {completed} / {STEPS.length}
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Setup ${pct}% complete`}
      >
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function TopBar() {
  const { email, role, logout } = useAuth();
  const initials = (email || "?").slice(0, 2).toUpperCase();
  const banner = usePageBanner((s) => s.banner);

  // Mirrors `app-sidebar.tsx`'s `showOnboardingSteps` gate — same admin-only, server-derived signal.
  const { data: onboarding } = useOnboardingStatus();
  const showProgress = role === "admin" && onboarding?.completed === false;
  const showPresence = hasPermission(role, "agents:queue");

  return (
    <header className="sticky top-0 z-20 flex h-20 shrink-0 items-center gap-3 border-b bg-background/80 px-6 backdrop-blur-md">
      {/* Mobile-only: the sidebar is an off-canvas drawer there and this is its one way in.
          On desktop the sidebar always stays open — no collapse/close control. */}
      <SidebarTrigger className="-ml-1 md:hidden" />
      {banner ? (
        <div className="flex min-w-0 items-center gap-3">
          {banner.icon && (
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
              <banner.icon className="size-5" />
            </span>
          )}
          <div className="min-w-0 leading-tight">
            <p className="font-display truncate text-xl font-semibold">{banner.title}</p>
            <p className="truncate text-xs text-muted-foreground">{banner.subtitle}</p>
          </div>
        </div>
      ) : null}

      <div className="ml-auto flex items-center gap-3">
        {showProgress && <SetupProgress />}
        {showPresence && <PresenceToggle />}
        <ThemeSwitch />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-lg" className="rounded-full" aria-label="Account">
              <Avatar className="size-9">
                <AvatarFallback className="bg-primary/10 text-xs font-medium text-primary">
                  {initials}
                </AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72 overflow-hidden p-0">
            <div className="flex items-center gap-3 bg-gradient-to-br from-secondary/70 to-secondary/20 px-4 py-4">
              <Avatar className="size-11 shrink-0 shadow-sm ring-2 ring-background">
                <AvatarFallback className="bg-primary text-sm font-semibold text-primary-foreground">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-muted-foreground">{email || "Signed in"}</p>
                <span className="mt-1 inline-flex items-center rounded-full border bg-card px-2 py-0.5 text-[11px] font-medium capitalize text-muted-foreground">
                  {role ?? "—"}
                </span>
              </div>
            </div>
            <DropdownMenuSeparator className="mx-3 my-0" />
            <div className="p-1.5">
              <DropdownMenuItem
                variant="destructive"
                className="cursor-pointer justify-center"
                onClick={() => void logout()}
              >
                <LogOut className="size-3.5" />
                <span className="text-xs">Log out</span>
              </DropdownMenuItem>
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
