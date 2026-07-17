import { Check, Waypoints } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";

import { NAV_GROUPS } from "@/app/nav";
import { useAuth } from "@/app/providers";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Progress } from "@/components/ui/progress";
import { STEPS } from "@/features/onboarding/steps";
import { useOnboardingStore } from "@/features/onboarding/store";
import { useOnboardingProgress } from "@/features/onboarding/useOnboardingProgress";
import { useOnboardingStatus } from "@/features/onboarding/useOnboardingStatus";
import { hasPermission } from "@/lib/rbac";
import type { Role } from "@/lib/rbac";

/** Replaces the normal console nav while an admin's setup isn't finished — the wizard is a
 * forced flow (`RequireOnboarding` bounces every other route back to it), so a nav list full of
 * locked links added nothing; the sidebar now just IS the wizard's step list until it's done. */
function OnboardingStepList() {
  const active = useOnboardingStore((s) => s.active);
  const setActive = useOnboardingStore((s) => s.setActive);
  const { done, completed } = useOnboardingProgress();

  const firstIncomplete = STEPS.findIndex((s) => !done[s.key]);
  const frontierIndex = firstIncomplete === -1 ? STEPS.length - 1 : firstIncomplete;
  const pct = Math.round((completed / STEPS.length) * 100);

  return (
    <>
      <div className="space-y-2 px-3.5 pt-1 pb-3 group-data-[collapsible=icon]:hidden">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium">Setup progress</span>
          <span className="tabular-nums text-muted-foreground">
            {completed} / {STEPS.length}
          </span>
        </div>
        <Progress value={pct} aria-label={`Setup ${pct}% complete`} />
      </div>
      <SidebarGroup>
        <SidebarGroupContent>
          <SidebarMenu>
            {STEPS.map((s, i) => {
              const isActive = s.key === active;
              const isDone = done[s.key];
              const isLocked = i > frontierIndex;
              return (
                <SidebarMenuItem key={s.key}>
                  <SidebarMenuButton
                    size="lg"
                    className="gap-3"
                    isActive={isActive}
                    disabled={isLocked}
                    tooltip={isLocked ? "Finish the current step to unlock" : s.label}
                    onClick={() => setActive(s.key)}
                  >
                    {isDone ? (
                      <Check className="size-5! text-success" />
                    ) : (
                      <s.icon className="size-5!" />
                    )}
                    <span className="flex min-w-0 flex-col items-start leading-tight">
                      <span className="truncate text-sm font-medium">{s.label}</span>
                      <span className="truncate text-xs text-muted-foreground">{s.hint}</span>
                    </span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </>
  );
}

function ConsoleNav({ role, pathname }: { role: Role | null; pathname: string }) {
  return (
    <>
      {NAV_GROUPS.map((group) => {
        const items = group.items.filter((i) => !i.permission || hasPermission(role, i.permission));
        if (items.length === 0) return null;
        return (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {items.map((item) => {
                  const active = pathname === item.to || pathname.startsWith(item.to + "/");
                  return (
                    <SidebarMenuItem key={item.to}>
                      <SidebarMenuButton asChild isActive={active} tooltip={item.label}>
                        <NavLink to={item.to}>
                          <item.icon />
                          <span>{item.label}</span>
                        </NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        );
      })}
    </>
  );
}

export function AppSidebar() {
  const { role } = useAuth();
  const { pathname } = useLocation();

  // Mirrors the router's `RequireOnboarding` gate (admin-only, derived from server state, not a
  // stored flag) — same signal that forces every other route back to /onboarding.
  const { data: onboarding } = useOnboardingStatus();
  const showOnboardingSteps = role === "admin" && onboarding?.completed === false;

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2.5 px-1.5 py-1.5">
          <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
            <Waypoints className="size-4" />
          </div>
          <div className="grid group-data-[collapsible=icon]:hidden">
            <span className="text-sm font-semibold leading-tight tracking-tight">Relay</span>
            <span className="text-xs leading-tight text-muted-foreground">AI Support Console</span>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        {showOnboardingSteps ? <OnboardingStepList /> : <ConsoleNav role={role} pathname={pathname} />}
      </SidebarContent>
    </Sidebar>
  );
}
