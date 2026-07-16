/**
 * Auth token lifecycle: access token in memory + single-flight refresh ([IMP-FE-4]).
 *
 * The access token never touches localStorage (XSS-safe); the refresh token is an httpOnly
 * SameSite=Strict cookie the browser sends automatically. On 401, the FIRST caller starts one
 * shared refresh promise and every concurrent 401 awaits it — no refresh stampede.
 */

const API_BASE = "/api/v1";

let accessToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

/** Single-flight refresh: concurrent callers share one in-flight request. */
export function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include", // sends the httpOnly refresh cookie
      });
      if (!res.ok) {
        accessToken = null;
        return null;
      }
      const data = (await res.json()) as TokenResponse;
      accessToken = data.access_token;
      return accessToken;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

/** Boot-time silent refresh — call once at app start; gate protected queries on the result. */
export async function bootstrapSession(): Promise<boolean> {
  const token = await refreshAccessToken();
  return token !== null;
}

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  const data = (await res.json()) as TokenResponse;
  accessToken = data.access_token;
}

export async function logout(): Promise<void> {
  accessToken = null;
  await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" });
}

/** Mirrors the backend `Industry` enum (`app/domain/records/schemas.py`) — the tenant's one
 * industry for the POC, picked at signup. */
export type Industry = "retail" | "logistics" | "telecom" | "healthcare" | "travel";

export interface SignupPayload {
  email: string;
  password: string;
  company_name: string;
  industry: Industry;
}

async function _problemDetail(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  return body?.detail ?? body?.title ?? `request failed: ${res.status}`;
}

export async function signup(payload: SignupPayload): Promise<{ tenant_id: string; message: string }> {
  const res = await fetch(`${API_BASE}/auth/signup`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await _problemDetail(res));
  return res.json();
}

export async function verifyEmail(token: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/auth/verify-email?token=${encodeURIComponent(token)}`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error(await _problemDetail(res));
}
