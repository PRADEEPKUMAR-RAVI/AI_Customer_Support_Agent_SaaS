/**
 * Current staff identity, decoded from the in-memory access-token JWT. There is no `/me`
 * endpoint — the access token already carries `sub, tenant_id, email, role`, and the backend
 * re-validates every request, so a client-side decode is a safe convenience for UI gating.
 */

import { getAccessToken } from "./auth";
import type { Role } from "./rbac";

export interface Me {
  staffId: string;
  tenantId: string;
  email: string;
  role: Role;
}

const KNOWN_ROLES: Role[] = ["admin", "agent", "platform"];

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(b64)
        .split("")
        .map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"))
        .join("")
    );
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** Read + decode the current access token into a `Me`, or null if not authenticated. */
export function readMe(): Me | null {
  const token = getAccessToken();
  if (!token) return null;
  const claims = decodeJwtPayload(token);
  if (!claims) return null;
  const rawRole = String(claims.role ?? "");
  const role = (KNOWN_ROLES as string[]).includes(rawRole) ? (rawRole as Role) : "agent";
  return {
    staffId: String(claims.sub ?? ""),
    tenantId: String(claims.tenant_id ?? ""),
    email: String(claims.email ?? ""),
    role,
  };
}
