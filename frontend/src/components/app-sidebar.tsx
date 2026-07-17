import type { CSSProperties } from "react";
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
  const { done } = useOnboardingProgress();

  const firstIncomplete = STEPS.findIndex((s) => !done[s.key]);
  const frontierIndex = firstIncomplete === -1 ? STEPS.length - 1 : firstIncomplete;

  return (
    <>
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
                      <s.icon className="size-5! text-sidebar-foreground" />
                    )}
                    <span className="flex min-w-0 flex-col items-start leading-tight">
                      <span className="truncate text-xs font-medium text-sidebar-foreground">{s.label}</span>
                      <span className="truncate text-[10px] text-sidebar-muted-foreground">{s.hint}</span>
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
            <SidebarGroupLabel className="text-sidebar-muted-foreground">{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {items.map((item) => {
                  const active = pathname === item.to || pathname.startsWith(item.to + "/");
                  return (
                    <SidebarMenuItem key={item.to}>
                      <SidebarMenuButton asChild isActive={active} tooltip={item.label}>
                        <NavLink to={item.to} className="text-sidebar-foreground">
                          <item.icon className="text-sidebar-foreground" />
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
    <Sidebar
      collapsible="icon"
      style={
        {
          // The same rail design used during onboarding — solid navy in light mode, neutral
          // charcoal in dark mode — now applied to the console nav too (see --onboarding-rail-*
          // in globals.css), so the sidebar doesn't change identity once setup finishes.
          "--sidebar": "var(--onboarding-rail)",
          "--sidebar-foreground": "var(--onboarding-rail-foreground)",
          "--sidebar-primary": "var(--onboarding-rail-primary)",
          "--sidebar-primary-foreground": "var(--onboarding-rail-primary-foreground)",
          "--sidebar-accent": "var(--onboarding-rail-accent)",
          "--sidebar-accent-foreground": "var(--onboarding-rail-accent-foreground)",
          "--sidebar-border": "var(--onboarding-rail-border)",
          "--sidebar-ring": "var(--onboarding-rail-ring)",
          "--sidebar-muted-foreground": "var(--onboarding-rail-muted-foreground)",
        } as CSSProperties
      }
    >
      <SidebarHeader className="border-b border-sidebar-border bg-black/5">
        <div className="flex items-center gap-2.5 px-1.5 py-3">
          <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground shadow-sm">
            <Waypoints className="size-4" />
          </div>
          <div className="grid group-data-[collapsible=icon]:hidden">
            <span className="text-sm font-semibold leading-tight tracking-tight text-sidebar-foreground">
              Relay
            </span>
            <span className="text-xs leading-tight text-sidebar-muted-foreground">AI Support Console</span>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        {showOnboardingSteps ? <OnboardingStepList /> : <ConsoleNav role={role} pathname={pathname} />}
      </SidebarContent>
    </Sidebar>
  );
}
