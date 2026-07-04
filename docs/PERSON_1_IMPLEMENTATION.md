# Person-1 — Implementation Plan (Senior · Platform Core, AI Engine & Chat Surfaces)

> **Mission:** You own the spine everything else stands on — the RLS/tenant-isolation harness, the auth boundary, the ports+adapters, the transactional outbox, and the customer-facing AI: the bounded tool loop, the grounding gate, verify-in-code, and the SSE chat surfaces. You define the contracts the two juniors code against, and you own the four non-negotiable CI gates. Front-load Phase 0 hard — the sooner your contracts + fakes land, the sooner person-2 and person-3 are unblocked.
>
> Read [`00_TEAM_TASK_SPLIT.md`](./00_TEAM_TASK_SPLIT.md) for the shared context, the full IMP-* improvement list, the dependency graph, and the phase checkpoints. This file is your projection of it.

---

## Your scope at a glance

| # | Module | Layer | Days | Purpose |
|---|---|---|:--:|---|
| Foundation | core/ + infra/ + api/ | BE | 20 | RLS harness, auth, ports+adapters, outbox, SSRF guard, crypto, cache/queue, DTOs/OpenAPI, fakes, seed |
| **M2** | Conversation & AI Engine | BE | 16 | Session, SSE streaming, bounded tool loop, grounding gate, verify-in-code, transition whitelist, structured output |
| **M9** | Notifications & Workers | BE | 15 | Outbox→SMTP, idempotent sends, query-driven scheduled sweeps, ingest/crawl/embed task wrappers |
| **M10** | Platform Operator (primitive only) | BE | ~2 | The audited `platform_bypass` RLS-bypass primitive (P3 builds the `/ops` endpoints on top) |
| **FE-Shell** | SPA foundation | FE | ↴ | Typed API client, `useSSE` hook, auth/token, RBAC gating, router, design system |
| **FE-Chat** | chat-core | FE | 26 | One reusable chat UI (stream renderer, filler, citations, thumbs, i18n/RTL) mounted 3 ways |
| **FE-Widget** | `widget.js` bundle | FE | ↴ | Shadow-DOM standalone widget + hosted `/chat/{widget_key}` page |

**≈ 77 person-days**, deliberately the heaviest load and the highest risk. Most is front-loaded; after Phase 1 you shift toward integrator/reviewer for the juniors.

---

## What you must deliver FIRST (Phase 0 contracts everyone waits on)

These are the artifacts person-2 and person-3 cannot start real work without. **Ship them as committed artifacts + fakes, even before the real implementations behind them exist.** Each has a hard acceptance test.

- [ ] **RLS / tenant-context harness** — `SET LOCAL app.tenant_id` inside a per-request transaction; `FORCE ROW LEVEL SECURITY` + `WITH CHECK` on every tenant table; a `with_tenant(tid)` context manager for **workers**. *Accept:* the **two-tenant leak test** (set A → insert; set B → select = 0 rows; no-context → 0 rows / write rejected) is **green in CI** and required on every PR. [IMP-SEC-1, IMP-DEL-2]
- [ ] **Auth model** — JWT-staff → current-staff+tenant; anonymous **widget-key → tenant** + Origin/`allowed_domain` check; `require_permission()` RBAC dep; `SameSite=Strict` httpOnly refresh cookie; short access TTL. *Accept:* a staff token and a widget-key both resolve tenant context through the same `api/deps.py` path; RBAC dep rejects a missing permission with RFC7807 403.
- [ ] **OpenAPI + Pydantic DTOs + typed FE client** — DTOs committed *before* routes so the spec exists early; FE-Shell generates the client both juniors import. *Accept:* `openapi.json` builds; the typed client generates; a mock server (MSW/Prism) serves it. [IMP-DEL-1]
- [ ] **SSE event protocol** — discriminated union on `type`: `status`/`filler`, `token`, `citation`, `final`, `error`, `done`; **one** Pydantic model mirrored to a TS type, plus a checked-in fixture. *Accept:* the fixture parses in both a backend and a frontend test (this is the drift gate — OpenAPI can't type SSE). [IMP-FE-5]
- [ ] **Ports + in-memory fakes + seed** — `LLMPort` (chat/tool-loop/structured-output + capability flag), `EmbeddingPort` (embed + rerank + **dimension**), `StoragePort`; `FakeLLM` (canned structured output + scripted tool calls), `FakeEmbedder` (hash→stable vector), `FakeReranker`; MailHog; seed CLI (≥2 tenants, ≥2 industries, **deliberately colliding record keys**). *Accept:* `docker-compose up` brings the full stack with fakes + seed and no vendor keys. [IMP-DEL-4]
- [ ] **Transactional outbox primitive** (`core/events.py`) — write-outbox-in-same-transaction; at-least-once + dedupe-key semantics. *Accept:* an event emitted in a rolled-back transaction is not delivered.
- [ ] **Ticket transition-whitelist + guarded-CAS primitive** — `(from, to, allowed_actors[])` tuples + one `apply_transition(ticket, to, actor)` doing `UPDATE … WHERE state=:expected`. *Accept:* P3 can implement M5 purely on top of it; the allow/deny matrix test passes. [IMP-TKT-1, IMP-TKT-2]
- [ ] **Shared security utils** — SSRF resolve-and-validate guard, AES-GCM helper (AAD-bound to `(tenant_id, connector_id)`), rate-limit dep, log-redaction filter. *Accept:* the guard rejects loopback/private/link-local resolved IPs and pins the connection to the validated IP. [IMP-SEC-5, IMP-SEC-8, IMP-SEC-7]
- [ ] **`lookup_record` verify seam** (co-authored with P2) — `Resolver.fetch(...) → RawRecord | NotFound | ConnectorError` (fetch only; `RawRecord` carries the **verify-field value + returned fields**); verify + status assembly lives in **your** M2 `lookup_record` tool, which maps `ConnectorError` (timeout/auth/connection) to the tool-failure fallback→escalate. *Accept:* the port signature is frozen before P2 writes any resolver. [IMP-DEL-3, C3]

---

## Backend modules

### Foundation — `core/` + `infra/` + `api/`
**Purpose:** the technical spine every feature module (M1–M10) builds on. No business logic — this is contracts + vendor adapters behind ports + the three code-enforced security boundaries that physically live here.

**Folder/files:**
- `api/deps.py` (DI + tenant resolve), `api/middleware.py`, `api/errors.py` (RFC7807), `api/v1/router.py`
- `core/config.py` (centralized tenant-config defaults), `core/security.py` (JWT + widget-key + AES-GCM helper), `core/logging.py`, `core/telemetry.py`, `core/ratelimit.py`, `core/events.py` (outbox)
- `infra/db/` (async engine, base model with `tenant_id`, repositories, **RLS setter**), `infra/cache/` (Redis), `infra/queue/` (Celery/pub-sub)
- `infra/llm/` (`openai_client`, `model_router` — **single provider, gpt-4o-mini; Groq dropped**), `infra/embeddings/` (`bge_onnx_client` — **BGE-M3 + bge-reranker-v2-m3 via ONNX, default**; optional `cohere_client`), `infra/vector/retriever` (pgvector primitives), `infra/connectors/base` (+ SSRF guard), `infra/storage/`, `infra/crawler/`, `infra/parsers/`, `infra/email/smtp.py`
- `schemas/` (Pydantic DTOs)

**Contracts you PROVIDE (and who consumes):** RLS session dep + `with_tenant()` (ALL), auth deps (M1 issues, M2/M7/M10 consume), repository base + async engine (ALL), RFC7807 + OpenAPI (all routers; FE-Shell codegens), outbox API (M9 + every event emitter), ports + adapters (M2/M3/M4), vector retriever primitive (M3 orchestrates), SSRF guard (M4 + crawler), AES-GCM helper (M4), storage/parsers/crawler (M3), rate-limit dep (M2 public endpoints).

**Improvements to implement:** [IMP-SEC-1] `SET LOCAL` + non-owner role + `FORCE RLS` + `WITH CHECK`. [IMP-SEC-2] file bytes as tenant-scoped `bytea`, not Large Objects. [IMP-SEC-5] one shared resolve-and-validate SSRF guard used by crawler + resolvers. [IMP-SEC-7] log-redaction filter (never log message bodies, verify values, record fields, bound params). [IMP-SEC-8] AES-GCM helper (random 96-bit nonce, AAD-bound). [IMP-DAT-1] HNSW `m=16, ef_construction=200`, `ef_search=100`, iterative scans on (pgvector ≥ 0.8). [IMP-DAT-2] Alembic named; pgvector ext / HNSW opclass / RLS policies / FTS indexes hand-authored, never autogenerated. [IMP-DAT-3] two Celery queues (`interactive` / `batch`) in compose. [IMP-DEL-4] fakes wired by default; real adapters behind an env flag.

**Gotchas:**
- **Own file split explicitly** to avoid duplicate work: *you* own the port/base/thin vendor client; the feature module owns the orchestration that composes it (e.g. you own `infra/vector` pgvector primitives; P2's M3 owns hybrid+RRF+rerank+gate). Write this down.
- The RLS GUC leaking across a pooled connection is the #1 cross-tenant breach path. `SET LOCAL` only — never session-level `SET`. Keep the async pool default `reset_on_return='rollback'`.
- The POC uses a **single LLM provider (gpt-4o-mini)** for the tool loop, structured output, **and** aux — Groq is dropped, so there's no cross-provider fallback to build. Keep `model_router` + a `LLMPort` capability flag anyway so a future non-tool aux model can slot in without assuming tool/structured-output parity.
- **Embeddings + rerank default to self-hosted BGE via ONNX** (`BGE-M3` embed + `bge-reranker-v2-m3` rerank), served by one small container (fastembed / TEI / Infinity) behind `EmbeddingPort`; Cohere is an optional adapter behind the same port. Ship the **INT8-quantized** rerank build — it's the one model in the query hot path. BGE-M3 is 1024-dim (matches `vector(1024)`).
- The M10 RLS-bypass must be designed into the RLS model **up front** as an audited privileged path, not bolted on. [IMP-SEC-9]

---

### M2 — Conversation & AI Engine
**Purpose:** the end-customer chat turn — session, SSE streaming, and the grounded agentic answer. This is the crown jewel: it enforces **three of the four** non-negotiables (grounding gate, verify-in-code, transition whitelist).

**Folder/files:** `services/conversation_service.py`; `services/ai_engine/{engine.py, grounding.py, structured.py, guardrails.py}`; `services/ai_engine/tools/{kb_retrieve.py, lookup_record.py, ticket_ops.py, escalate.py}`; `services/ai_engine/prompts/` (versioned); `api/v1/{conversations.py, widget.py}`; `domain/conversation/` (Conversation, Message, Turn).

**APIs:** `POST /widget/session` · `POST /conversations/{id}/messages` (SSE) · `POST /conversations/{id}/messages/{mid}/feedback` · `GET /conversations/{id}`.

**Contracts you PROVIDE:** the SSE event protocol (FE-Chat/Widget), `message.structured_out` schema (M5 tags, M6 escalate reason, M8 metrics), the `lookup_record` verify+status assembly (M4 supplies `Resolver.fetch` only), `escalation_context` DTO (M6/M7).

**Improvements to implement:** [IMP-ENG-1] single-pass but **separate channels** — stream only answer text on `token`; validated control envelope on a trailing `final` before any side-effect fires. [IMP-ENG-2] add `max_tool_calls_per_turn` (~4–6); on cap force a final answer; `NO_GROUNDING` is terminal. [IMP-ENG-3] 20s = time-to-first-token, not whole-turn; `stall_retries` retries only the stalled step. [IMP-ENG-4] `SETNX idem:{tenant}:{conversation}:{client_msg_id}` before the loop; duplicate → attach/replay. [IMP-ENG-5] single-active-turn Redis lock per conversation. [IMP-ENG-6] single-provider LLM — tool loop + structured output + aux all on gpt-4o-mini (Groq dropped); `model_router` stays as the seam for a future aux swap. [IMP-ENG-7] typed `status` SSE event so the widget localizes filler. [IMP-SEC-4] pass KB chunks + record fields **only as delimited tool-result messages**, never in the system prompt. [IMP-TKT-1] **state gate at the top** of the message handler: `escalated`/`with_agent` → persist + route to agent, do **not** invoke the model. [IMP-TKT-3] escalate strictly dominates resolve. [IMP-ESC-5] first-class "talk to human" signal (a flag, not a text string). [IMP-ESC-6] constrain the "suggested reply" by the same grounding gate. [IMP-RAG-1] gate = top-1 rerank ≥ threshold + require ≥1 citation (you *decide*; M3 *reports*). [IMP-DEL-3] verify assembly lives here.

**PRD-audit additions (§14):** **[C3]** map a resolver `ConnectorError` → the existing tool-failure fallback→escalate. **[C6]** emit escalation reasons from the canonical enum `no_grounding | explicit | sensitive | dispute | n_fails | proactive | timeout` (P3 owns it) — `timeout` on a stall, `dispute` on deterministic record-state escalations. **[A5]** add `answer_complete: bool` to the structured envelope → when true, emit a closing question ("Did that solve your issue?"); a thumbs-up on that message (feedback endpoint) or a detected affirmative reply drives the AI-actor `ai_handling→resolved` (the CAS is P3/M5). **[A1]** deterministic escalate (reason `dispute`) in `lookup_record` post-processing when `coverage=void`, when order `status=delivered` + the customer reports non-receipt, and on a refund dispute for a `cancelled` order not covered by KB — in code, never the model's soft backstop. **[A2]** proactive human offer: at retry cap-1, or `NO_GROUNDING` with no tool answer, offer *"Would you like me to connect you to a human agent?"* instead of escalating immediately — "yes" fires the first-class escalate flag (reason `explicit`), "no" continues. **[A3]** if `detected_language ∉ agent_settings.supported_languages`, generate the reply in `agent_settings.default_language`. **[A4]** pass the conversation's established language into turn context; on short/ambiguous/low-confidence input, keep it (no flip-flop). **[A14]** `/widget/session` stamps `expires_at` from the configured session lifetime and mints a fresh session when expired. **[A16]** the worst-case turn is bounded by `max_tool_calls_per_turn × per-step budget` (the backstop for "within the latency target"); per-step `stall_retries` also covers post-first-token stalls.

**Gotchas:**
- Don't try to stream JSON and validate it in one pass — that's the [IMP-ENG-1] trap. Answer text streams; metadata validates on `final`.
- The grounding gate is a code decision, not a model self-report. M3 returns scored hits + a `grounded` boolean; **you** make the answer-vs-`NO_GROUNDING` call. Keep the two clearly separated.
- Verify-in-code: the model slot-fills the key + verify value, but the **comparison runs in `lookup_record.py`**. The model never sees "verified: true" as its own decision.
- Clamp model-proposed tags against the tenant `tag_def` allowed list — never trust raw tag strings for any control decision.
- **After-hours email capture vs the state gate [A15]:** in the no-agent branch, the escalation `customer_message` asks for the email, and a **narrow non-LLM capture path** writes `ticket.contact_email` even while the ticket is `escalated` (or capture it just before flipping state). This is the one deliberate exception to [IMP-TKT-1] "the AI stops answering once escalated" — it must not re-invoke the model. (Also accept the widget's optional email field.)

---

### M9 — Notifications & Workers
**Purpose:** reliable email + all background jobs. Correctness- and concurrency-heavy; on the critical path because every module needs the outbox to emit events.

**Folder/files:** `workers/{ingestion,crawl,embedding,scheduled,notification}_tasks.py`; `infra/email/smtp.py`; `core/events.py` (outbox — declared foundation-owned, landed week 1).

**Contracts you PROVIDE:** outbox emit API (M1/M3/M6/M7/M8), Celery enqueue contract (M3 kicks ingestion), SMTP dispatch port, the **"system" actor** for M5's time-based transitions, `email_log` audit (M8/M10), the Beat schedule.

**Ownership rule (write it down):** M9 owns the Celery app, Beat schedule, registration, and the outbox/retry/idempotency plumbing; the `*_tasks.py` wrappers only import and invoke P2's M3 domain services — **no domain logic in workers.**

**Improvements to implement:** [IMP-WRK-1] reword "idempotent sends" → at-least-once + dedupe; `outbox` gets `status/attempts/next_attempt_at/locked_at/dedupe_key`; drain via `SELECT … FOR UPDATE SKIP LOCKED`; `email_log UNIQUE(tenant_id, dedupe_key)`; add a reaper for stuck `sending` rows. [IMP-WRK-2] `task_acks_late`, `task_reject_on_worker_lost`, `prefetch=1`, Redis AOF; idempotent embed (upsert `kb_chunk` by `(source_id, content_hash)`). [IMP-WRK-3] timers as `due_at` columns + query-driven Beat sweeps (not per-ticket `eta`); CAS + `SKIP LOCKED`; single Beat / redbeat. [IMP-WRK-4] per-batch checkpointed ingestion; embed calls outside any DB transaction. [IMP-WRK-5] expose DLQ depth + send-failure count on `/ops/health`. [IMP-DAT-3] two queues. Worker-side RLS: every task carries `tenant_id` and runs `with_tenant()` before any DML.

**Gotchas:** workers have **no request scope** — the foundation's request-scoped RLS setter doesn't apply; the worker base must `SET LOCAL` from the task payload or you get a cross-tenant leak that tests miss. Idle-sweep vs incoming-message is a two-writer race — always route the sweep through the CAS transition (0 rows = no-op).

---

### M10 — Platform Operator (primitive only; P3 builds the endpoints)
**Purpose:** you own only the security-critical piece — the audited RLS-bypass.

**Improvements to implement:** [IMP-SEC-9] bypass = a **dedicated least-privilege Postgres role on its own connection**, used only by `/ops` handlers (never the shared request pool), behind a single `with platform_bypass(actor, action):` context manager that writes an append-only **non-RLS `platform_audit_log`** row in the same transaction. Operator identity = a separate platform principal with `scope=platform` (never a tenant JWT). Add `tenant.status ∈ {active, suspended}` and reject suspended tenants in the foundation tenant-resolve middleware (so P3's suspend actually bites at `/widget/session`).

**Gotcha:** a naive bypass (superuser connection / globally disabling `row_security`) is the single most dangerous line in the codebase. Make the context manager the *only* path, and make the audit write un-forgettable (inside the manager).

---

## Frontend modules

### FE-Shell — SPA foundation
**Purpose:** the skeleton admin + agent mount into. **Folder:** `frontend/src/{app/(router,providers,layout), lib/(api,sse,auth,rbac), components/(design system), hooks/, types/}`.

**Contracts you PROVIDE:** typed OpenAPI client, `useSSE` auto-reconnect hook, auth provider + in-memory token + single-flight refresh interceptor, RBAC route/UI gates, design system — consumed by every FE feature module (both juniors).

**Improvements:** [IMP-FE-1] streaming transport = `fetch()` + ReadableStream (not native `EventSource`); reconnect replays the same `client_msg_id` (idempotent **whole-turn** replay), never re-enters the loop. **[T7] POC:** drop the per-event Redis replay buffer — whole-turn replay is enough; keep the monotonic `id:` field only if trivially free. [IMP-FE-4] single-flight refresh + boot silent-refresh gating TanStack Query `enabled`; `SameSite=Strict` cookie. [IMP-FE-5] the hand-authored SSE union is the source of truth. **Gotcha:** factor one framework-agnostic transport primitive in `chat-core/sse.ts`; FE-Shell's React SSE hook is a thin wrapper over it — don't fork the reconnect logic.

### FE-Chat — chat-core
**Purpose:** one reusable chat UI (message list, composer, streaming renderer, filler/status, citations, thumbs, "talk to a human", consent, RTL/i18n) mounted 3 ways. **Folder:** `packages/chat-core/` (component + `sse.ts` + `session.ts` + `i18n/`).

**Improvements:** [IMP-FE-2] **author the view once in Preact**; reuse verbatim in the widget; mount into the React SPA as a Preact island. [IMP-ENG-7] map `status` events → pre-translated chrome strings. [IMP-ESC-5] the "talk to a human" button posts a first-class escalate flag. Own the `dir`/RTL attribute for all three surfaces; **[C7]** switch chrome locale + dir **only when `detected_language` changes to a new established value** (not every turn — pairs with M2's language-stability rule [A4]). **[A6]** render the tenant's configurable `welcome_message` as the first chrome line (i18n fallback; the setting itself lives in P3/M1). **[A13]** citations render "from `<file>`, p.`<n>`" for file sources (uses `page_number`) and a clickable link for URL sources (uses `source_url`), falling back to the title (metadata produced by P2/M3). **Gotcha:** consent / talk-to-human / thumbs / i18n / streaming belong **here once**, not duplicated in FE-Widget.

### FE-Widget — `widget.js`
**Purpose:** embeddable, style-isolated, tiny, streaming. **Folder:** `widget/src/{index.ts, Widget.tsx, styles.css}` → single `widget.js`. Wraps chat-core in a Shadow-DOM host; localStorage `session_id` continuity; retry; WCAG AA + ARIA + RTL.

**Improvements:** [IMP-FE-3] Shadow DOM ≠ CSP exemption — style via `adoptedStyleSheets`; publish the exact CSP directives tenants must add (goes in FE-Onboarding, owned by P3 — hand them the list). [IMP-FE-7] embed snippet = `<script async>` <2 KB loader; paint the bubble on load, dynamic-import the panel on first open; CI bundle-size budget. [IMP-SEC-3] the widget scopes read/write to the **server-minted** `session_id`; never trusts a client-supplied id. **Gotcha:** widget = Shadow-DOM host + bubble/panel chrome + localStorage + consent-gate wiring + retry, and nothing more; everything else is chat-core.

---

## Your phase-by-phase tasks

### Phase 0 — Foundations & Contracts *(this is your critical push — everyone waits on it)*
- RLS/tenant harness: `SET LOCAL` request dep, `FORCE RLS` policies, worker `with_tenant()`, **two-tenant leak CI test**.
- JWT + widget-key auth + `require_permission` RBAC dep; `SameSite=Strict` refresh cookie.
- OpenAPI + DTO + RFC7807 skeleton; publish a stub spec so FE-Shell codegens early.
- SSE event schema + fixture (Pydantic ↔ TS).
- Ports + `FakeLLM`/`FakeEmbedder`/`FakeReranker` + MailHog + seed CLI (colliding keys).
- SSRF guard, AES-GCM helper, rate-limit dep, log-redaction, outbox primitive, transition-whitelist CAS primitive.
- `docker-compose` (nginx/Traefik + API + workers + Postgres/pgvector/FTS + Redis + MailHog) + Alembic harness.
- **✅ Checkpoint:** two-tenant RLS leak test green in CI; typed client generates; SSE fixture parses in the FE; `docker-compose up` = full stack on fakes + seed.

### Phase 1 — Walking-skeleton vertical slice
- Minimal M2 tool loop (single `kb_retrieve` tool), grounding gate on a provisional threshold, SSE token+citation streaming, `structured_out` persist, verify-in-code call site (stub), transition-whitelist enforcement.
- FE-Shell + chat-core streaming renderer (in-app console route).
- Pair with P2 on the **provisional threshold calibration** [IMP-DEL-5].
- **✅ Checkpoint:** admin logs in on the seeded tenant, asks a question in the console, gets a grounded streamed answer + citation (or `NO_GROUNDING → "I don't know"`); ticket goes `new→ai_handling→resolved`; exactly one `turn_metric` written.

### Phase 2 — Feature build-out
- Harden M2: tool caps + `max_tool_calls` [IMP-ENG-2], 20s-timeout FSM [IMP-ENG-3], idempotency SETNX start-lock [IMP-ENG-4], structured-output validate+retry→escalate fallback [IMP-ENG-1], single-active-turn lock [IMP-ENG-5], prompt-injection delimiting [IMP-SEC-4].
- Ship **FE-Widget** (Shadow DOM + async loader + `adoptedStyleSheets`).
- **✅ Checkpoint:** the widget streams on an external test page; record lookups verify-in-code and return `ok`/`unverified`/`not_found` neutrally (last two identical).

### Phase 3 — Escalation + realtime seam
- M2 **ticket-state gate** [IMP-TKT-1] (AI answers only in `{new, ai_handling}`; canned "a human is handling this" otherwise); escalate-tool wiring; **escalate-dominates-resolve** [IMP-TKT-3]; deterministic sensitive-intent backstop + first-class "talk to human" [IMP-ESC-5]; supply the `escalation_context` DTO with a **grounding-gated** suggested reply [IMP-ESC-6].
- **✅ Checkpoint:** a no-grounding turn and an explicit "talk to human" both escalate; the AI stops answering once escalated.

### Phase 4 — Workers, ops & hardening
- M9 full: notification worker + SMTP, outbox drain `FOR UPDATE SKIP LOCKED` + `email_log` dedupe [IMP-WRK-1], retry/dead-letter, idempotent query-driven CAS sweeps [IMP-WRK-3], two-queue Celery [IMP-DAT-3], ingestion watchdog, worker-side RLS.
- Ship the **four non-negotiable CI-gate suites**; run the grounding-threshold calibration on a labelled set.
- **✅ Checkpoint:** escalation + SLA emails deliver via MailHog with dedupe; the outbox survives a worker crash (at-least-once); all four CI suites green.

---

## The four non-negotiables you own

| Non-negotiable | Enforcement point (yours) | CI gate you ship |
|---|---|---|
| **Identity verification** | verify + status assembly in M2 `lookup_record.py` (resolvers only fetch) | verify-table across 5 templates incl. healthcare N=1; `unverified` == `not_found` message |
| **Grounding gate** | M2 decides answer-vs-`NO_GROUNDING` on M3's reported score | off-topic set → refuses; on-topic → answers with a citation |
| **Transition whitelist** | `apply_transition(ticket, to, actor)` guarded CAS | allow/deny matrix: AI rejected on every edge except the 3 whitelisted |
| **Tenant isolation (RLS)** | `SET LOCAL` request dep + worker `with_tenant()` + `FORCE RLS` | two-tenant leak test incl. one worker path |

All four must be green before Phase 4 sign-off. They exercise the juniors' code too — a red gate is a release blocker for the whole team.

---

## Definition of done for your slice
- All four non-negotiable CI suites green and required on every PR.
- SSE streams cleanly (answer on `token`, validated metadata on `final`); reconnect never double-fires a turn.
- The outbox is at-least-once with dedupe and survives a worker crash; sweeps are query-driven + idempotent.
- The widget loads async, isolates under Shadow DOM + `adoptedStyleSheets`, and streams under a strict-CSP host (with the documented directives).
- Both juniors have been unblocked since end of Phase 0 (contracts + fakes + mock server live).

## Offline dev (so the juniors never need a vendor key)
- `FakeLLM` returns canned structured output + scripted tool calls; `FakeEmbedder` maps text→stable hashed vector; `FakeReranker` is deterministic. Selected by default in dev/CI; the real **OpenAI LLM** + real **BGE-ONNX embeddings/rerank** (or Cohere) sit behind an env flag.
- **MailHog** in `docker-compose`; the SMTP adapter points at it in dev so the whole outbox→email flow (verification/escalation/SLA) is testable offline.
- Seed CLI creates ≥2 tenants across ≥2 industries with **deliberately colliding record keys** so the RLS + verify paths are exercised by construction.
- Everything runs from `docker-compose up` with zero cloud dependencies — this is what makes the "no cloud" story true for dev/CI even though the real LLM path is cloud.
