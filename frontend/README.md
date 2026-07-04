# FE-Shell (Person-1)

The SPA foundation the admin + agent feature modules mount into: typed API client, SSE
streaming client, auth (in-memory access token + single-flight refresh), RBAC gating, router,
providers, and a design-system stub.

## Setup

```bash
npm install
npm run gen:api      # generate src/api/generated/schema.ts from ../contracts/openapi.json
npm run dev          # http://localhost:5173 (proxies /api -> http://localhost:8000)
```

Run `npm run gen:api` before `dev`/`build`/`typecheck` — `src/lib/api.ts` imports the
generated OpenAPI types. The backend produces the spec with `python -m app.cli.export_openapi`.

## Test

```bash
npm run test         # vitest — includes the SSE contract drift gate
```

`src/test/sse.contract.test.ts` asserts the shared `contracts/sse_events.fixture.json` parses
against the FE SSE union (`src/types/sse.ts`), which mirrors the backend `app/schemas/sse.py`.
The backend runs the mirror of this test — together they are the drift gate for the one
contract OpenAPI can't type.

## Key files

| Path | Purpose |
|---|---|
| `src/types/sse.ts` | SSE discriminated union + `parseSSEEvent` runtime validator |
| `src/lib/sse.ts` | fetch()+ReadableStream streaming client; reconnect replays `client_msg_id` |
| `src/lib/auth.ts` | in-memory access token + single-flight refresh + boot silent-refresh |
| `src/lib/api.ts` | typed `openapi-fetch` client + Bearer/401-retry middleware |
| `src/lib/rbac.ts` | permission catalog mirroring the backend |
| `src/app/*` | providers, router (role-gated), layout |
