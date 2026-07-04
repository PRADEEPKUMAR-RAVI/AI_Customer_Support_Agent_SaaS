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

// The generated OpenAPI path keys already include the `/api/v1` prefix, so the client base is
// the origin root (the Vite dev proxy forwards `/api` to the backend). Setting it to `/api/v1`
// here would double-prefix every typed call.
const API_BASE = "";

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

export const api = createClient<paths>({ baseUrl: API_BASE, credentials: "include" });
api.use(authMiddleware);
