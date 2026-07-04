/**
 * RBAC gating helpers — mirror the backend catalog (`app/core/permissions.py`, audit [C5]).
 * admin + agent staff roles, plus the platform operator. No `owner` tier.
 */

export type Role = "admin" | "agent" | "platform";

export const ROLE_PERMISSIONS: Record<Role, ReadonlySet<string>> = {
  admin: new Set([
    "kb:manage",
    "records:manage",
    "settings:manage",
    "staff:manage",
    "tags:approve",
    "tickets:read",
    "analytics:read",
    "embed:read",
    "agents:queue",
    "tickets:claim",
    "tickets:reply",
  ]),
  agent: new Set(["agents:queue", "tickets:read", "tickets:claim", "tickets:reply"]),
  platform: new Set(["ops:read", "ops:manage"]),
};

export function hasPermission(role: Role | null | undefined, permission: string): boolean {
  if (!role) return false;
  return ROLE_PERMISSIONS[role]?.has(permission) ?? false;
}
