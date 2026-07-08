/**
 * Platform-operator auth — deliberately separate from the tenant staff session.
 *
 * There is no `/ops/login` endpoint: the operator pastes a platform-scoped JWT, which we hold in
 * memory and mirror to `sessionStorage` so a tab refresh survives but the token never outlives the
 * browser session (and never touches `localStorage`).
 *
 * `opsFetch` is a RAW fetch that carries this operator token. It intentionally does NOT go through
 * `@/lib/api` — that client injects the tenant *staff* access token, which must never ride on a
 * cross-tenant platform call.
 */

const STORAGE_KEY = "ops.platform_token";

function readInitial(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    // sessionStorage unavailable (private mode / non-browser) — fall back to in-memory only.
    return null;
  }
}

let token: string | null = readInitial();

export function getOpsToken(): string | null {
  return token;
}

export function setOpsToken(next: string): void {
  token = next.trim();
  try {
    sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Persisting is best-effort; the in-memory copy still works for this tab.
  }
}

export function clearOpsToken(): void {
  token = null;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

/** Pull an RFC 7807 problem message off a failed response, with a sane fallback. */
async function problemDetail(res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as
    | { detail?: string; title?: string }
    | null;
  return body?.detail ?? body?.title ?? `Request failed (${res.status} ${res.statusText})`;
}

/**
 * Raw fetch against the platform-ops API using the pasted operator token. Throws an `Error`
 * carrying the problem detail on any non-2xx response, so TanStack Query `queryFn`/`mutationFn`
 * can simply `return opsFetch(...)`. Returns the parsed JSON body (or `undefined` for 204).
 */
export async function opsFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!token) throw new Error("No operator token set. Paste a platform token to continue.");

  const headers = new Headers(init?.headers);
  headers.set("authorization", `Bearer ${token}`);
  headers.set("accept", "application/json");
  if (init?.body != null && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  const res = await fetch(path, { ...init, headers });
  if (!res.ok) throw new Error(await problemDetail(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
