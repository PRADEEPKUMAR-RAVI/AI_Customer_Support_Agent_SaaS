/**
 * Typed API client — `openapi-fetch` bound to the generated OpenAPI types, with a Bearer
 * interceptor and a 401 -> single-flight-refresh -> retry-once flow.
 *
 * Run `npm run gen:api` first to produce `src/api/generated/schema.ts` from
 * `../contracts/openapi.json`. Until then, TypeScript will flag the import below — expected.
 */

import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "../api/generated/schema";
import { getAccessToken, refreshAccessToken } from "./auth";

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = getAccessToken();
    if (token) request.headers.set("authorization", `Bearer ${token}`);
    return request;
  },
  async onResponse({ request, response }) {
    if (response.status !== 401) return response;
    // Single-flight refresh, then retry the original request once.
    const token = await refreshAccessToken();
    if (!token) return response;
    const retried = new Request(request, {
      headers: (() => {
        const h = new Headers(request.headers);
        h.set("authorization", `Bearer ${token}`);
        return h;
      })(),
    });
    return fetch(retried);
  },
};

// No baseUrl prefix: the generated `paths` type keys already carry the full server-relative
// path (e.g. "/api/v1/admin/staff") because the OpenAPI spec has no `servers` entry stripping
// it — FastAPI reports routes exactly as registered (`api_router` is mounted at `/api/v1`).
// Setting baseUrl to "/api/v1" here would double the prefix on every call.
export const api = createClient<paths>({ credentials: "include" });
api.use(authMiddleware);

/** Unwraps an `openapi-fetch` `{data, error}` result, throwing a plain `Error` (message pulled
 * from the RFC7807 problem body) so callers — mainly TanStack Query `mutationFn`/`queryFn` —
 * can just `return unwrap(await api.GET(...))`. */
export function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error !== undefined) {
    const problem = result.error as { detail?: string; title?: string } | undefined;
    throw new Error(problem?.detail ?? problem?.title ?? "Request failed");
  }
  return result.data as T;
}
