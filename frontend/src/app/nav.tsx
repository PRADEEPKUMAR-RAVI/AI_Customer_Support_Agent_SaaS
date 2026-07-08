/** Console navigation model — shared by the sidebar and the ⌘K command palette. Each item is
 * gated by an optional RBAC permission (mirrors app/core/permissions.py via lib/rbac.ts). */

import {
  BarChart3,
  BookOpen,
  Database,
  Headset,
  LayoutDashboard,
  type LucideIcon,
  Rocket,
  SlidersHorizontal,
  TerminalSquare,
  Ticket,
  Users,
} from "lucide-react";

import type { Role } from "@/lib/rbac";

/** Where a staff member lands after login / when visiting the root: agents work the queue, so
 * they go to the inbox; everyone else (admin) gets the overview dashboard. */
export function homePathForRole(role: Role | null): string {
  return role === "agent" ? "/inbox" : "/overview";
}

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Permission required to see this item; undefined = any authenticated staff. */
  permission?: string;
  /** Keywords to help the command palette match. */
  keywords?: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { to: "/overview", label: "Overview", icon: LayoutDashboard, keywords: "home dashboard" },
      { to: "/tickets", label: "Tickets", icon: Ticket, permission: "tickets:read", keywords: "conversations cases" },
      { to: "/inbox", label: "Agent inbox", icon: Headset, permission: "agents:queue", keywords: "queue workspace escalations" },
    ],
  },
  {
    label: "Configure",
    items: [
      { to: "/onboarding", label: "Setup guide", icon: Rocket, permission: "settings:manage", keywords: "onboarding wizard get started" },
      { to: "/knowledge", label: "Knowledge", icon: BookOpen, permission: "kb:manage", keywords: "docs sources rag ingest" },
      { to: "/records", label: "Records", icon: Database, permission: "records:manage", keywords: "datasets connectors orders" },
      { to: "/settings", label: "Agent settings", icon: SlidersHorizontal, permission: "settings:manage", keywords: "persona language escalation tags" },
      { to: "/channels", label: "Channels", icon: TerminalSquare, permission: "settings:manage", keywords: "widget embed key domains" },
      { to: "/staff", label: "Staff", icon: Users, permission: "staff:manage", keywords: "team invite roles" },
      { to: "/analytics", label: "Analytics", icon: BarChart3, permission: "analytics:read", keywords: "metrics reports cost csat" },
    ],
  },
];
