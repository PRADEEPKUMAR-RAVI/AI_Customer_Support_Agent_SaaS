# AI Customer Support Agent — Team Task Split & Build Plan

> **Read this first.** This is the master plan for the 3 of us. It summarises what we are building, splits every backend + frontend module across the three of us, fixes the gaps we found in the original design docs, and lays out a phase-by-phase build order so nobody is ever blocked.
>
> **Source of truth:** `source/END_TO_END_FLOW.pdf` + `source/IMPLEMENTATION_PLAN.pdf` (the developer-written design). This document does not replace them — it *sequences*, *splits*, and *hardens* them.
>
> **Your personal file** (do your work from this):
> - Person-1 (senior) → [`PERSON_1_IMPLEMENTATION.md`](./PERSON_1_IMPLEMENTATION.md)
> - Person-2 (junior) → [`PERSON_2_IMPLEMENTATION.md`](./PERSON_2_IMPLEMENTATION.md)
> - Person-3 (junior) → [`PERSON_3_IMPLEMENTATION.md`](./PERSON_3_IMPLEMENTATION.md)

---

## 1. What we are building (in one paragraph)

A **multi-tenant SaaS**: any business signs up, uploads its **knowledge** (docs/FAQs/URLs) and its **customer records** (orders/warranties/appointments/etc.), configures an agent, and drops a chat widget on its site. An **AI agent resolves customer questions 24×7 in the customer's own language**, grounded strictly in that tenant's data, auto-creates a support ticket per conversation, auto-tags it, and **escalates to a human when it should** — with no dead ends. One chat engine powers three surfaces: an **embeddable widget**, a **hosted page** (`/chat/{widget_key}`), and an **in-app console**.

### Locked stack (do not re-litigate)

| Layer | Choice |
|---|---|
| Backend | Python 3.12 + **FastAPI** (async, clean/hexagonal layering) |
| Frontend | **React 18 + TS** SPA (admin + agent, role-gated) · **Preact + Shadow DOM** widget bundle |
| LLM | OpenAI **gpt-4o-mini** — **single provider** for the tool loop, structured output, **and** the cheap aux tasks (query rewrite, summaries, tag classification). *Groq dropped for the POC* — one key, no cross-provider fallback; `model_router` keeps the LLM swappable for later. |
| Embeddings + rerank | **Default: self-hosted via ONNX** — **BGE-M3** (embed, 1024-dim, MIT) + **bge-reranker-v2-m3** (cross-encoder rerank, MIT). $0, no key, no cloud, multilingual, commercial-safe. **Cohere** multilingual is an optional managed swap behind the same port. |
| Datastore | **PostgreSQL 16** — relational + **pgvector** + FTS/BM25 + file bytes; **RLS** multi-tenancy |
| Search | Hybrid: pgvector (dense) + Postgres FTS/BM25 → **RRF** → **rerank** |
| Cache / queue / realtime | **Redis** (cache, idempotency, Celery broker, pub/sub) |
| Workers | **Celery** (ingestion, crawl, embeddings, scheduled jobs, email) |
| Email | **SMTP** relay (outbox → worker → send) |
| Deploy | **Docker Compose** (nginx/Traefik + API + workers + Postgres + Redis). **No cloud services.** |

### The four non-negotiables (enforced in **code**, never by the model)
1. **Identity verification** — the engine compares the verify value in code; the model never decides "verified".
2. **Grounding gate** — answer only when retrieval clears a **relevance threshold** (not model self-confidence).
3. **Ticket-transition whitelist** — the AI may only perform `new→ai_handling`, `ai_handling→resolved`, `ai_handling→escalated`.
4. **Tenant isolation (RLS)** — every row carries `tenant_id`; Row-Level Security isolates every query.

> ⚠️ **Reality check the docs gloss over:** "self-hosted, no cloud" describes the *infrastructure*. With our stack choices the **only mandatory cloud dependency is the OpenAI gpt-4o-mini LLM** — embeddings + rerank default to **self-hosted BGE via ONNX** (BGE-M3 + bge-reranker-v2-m3), so customer PII/PHI leaves the box **only** inside the LLM prompt. That's a conscious POC trade-off — see **[IMP-SEC-7]** (log redaction). A fully air-gapped tenant would additionally need a self-hosted LLM (future work).

---

## 2. The system at a glance

**Backend modules** (per the plan) + a **cross-cutting Foundation**. **Frontend modules** grouped into logical builds. Effort = rough solo person-days; skill = who can safely own it.

| Module | What it is | Cx | Skill | Days | Owner |
|---|---|:--:|---|:--:|:--:|
| **Foundation** | core/ + infra/ + api/: RLS harness, auth, ports+adapters, outbox, SSRF guard, crypto, cache/queue, DTOs/OpenAPI | 5 | senior | 20 | **P1** |
| **M1** Tenancy/IAM/Onboarding | tenants, staff, RBAC, signup/verify/login, widget-key, industry→schema+templates, agent-settings | 4 | senior* | 14 | **P3** |
| **M2** Conversation & AI Engine | session, SSE streaming, bounded tool loop, grounding gate, verify-in-code, transition whitelist, structured output | 5 | senior | 16 | **P1** |
| **M3** Knowledge / RAG | ingest FSM, chunking, embed, hybrid+RRF+rerank+threshold gate, citations, reingest | 5 | senior* | 24 | **P2** |
| **M4** Records & Connectors | `lookup_record` contract, 5 industry schemas, verify-in-code, Upload/API/DB resolvers, SSRF, AES-GCM | 4 | senior* | 16 | **P2** |
| **M5** Ticketing & Tags | one ticket/convo, lifecycle state machine + AI whitelist, tags approve/pending, reopen | 3 | mid | 11 | **P3** |
| **M6** Escalation | triggers, hand-off + summary, after-hours capture-email + SLA | 3 | mid | 5 | **P3** |
| **M7** Agent Workspace & Presence | presence, queue, claim-lock, conversation view, reply/notes/resolve, realtime pub/sub | 4 | senior* | 13 | **P3** |
| **M8** Analytics | per-turn metrics, rollups, dashboards, cost/CSAT | 3 | mid | 6 | **P2** |
| **M9** Notifications & Workers | transactional outbox → SMTP, idempotent sends, scheduled sweeps, ingest/crawl/embed pipelines | 4 | senior | 15 | **P1** |
| **M10** Platform Operator | cross-tenant list/suspend, health, usage via audited RLS-bypass | 3 | senior | 4 | **P1**(primitive) + **P3**(endpoints) |
| **FE-Shell** | SPA skeleton, typed API client, SSE hook, auth/token, RBAC, design system | 5 | senior | ↴ | **P1** |
| **FE-Chat** (chat-core) | one reusable chat UI (stream renderer, filler, citations, thumbs, i18n/RTL) | 5 | senior | 26 | **P1** |
| **FE-Widget** | Shadow-DOM `widget.js` bundle + hosted page | 5 | senior | ↴ | **P1** |
| **FE-Auth / Onboarding / Staff** | login/signup/verify · industry+templates+upload wizard · staff CRUD | 3 | mid | 13 | **P3** |
| **FE-Knowledge / Records / AgentSettings** | source list+upload · dataset+connector UI · settings + tag-approval tray | 3 | mid | 13 | **P2** |
| **FE-Tickets / AgentWorkspace / Analytics** | ticket list/detail · live agent workspace · dashboards | 4 | mixed | 16 | **P3**(Tickets+Workspace) + **P2**(Analytics) |

`Cx` = complexity 1–5. `senior*` = senior-required **module**, but we make it junior-safe by having **P1 own the dangerous primitives + the CI gate**, so the junior implements *on top of* a locked contract (see §6).

**Total ≈ 212 person-days.** Split target below.

---

## 3. Ownership map (who owns what)

We use **feature-vertical ownership**: each person owns backend module(s) **plus the matching frontend**, so every feature is demoable end-to-end by one person with minimal hand-offs. **The senior owns the spine + all the "enforced-in-code" primitives + the customer-facing chat surfaces; the two juniors each own a coherent, self-contained vertical.**

### 👤 Person-1 — Senior · *Platform Core, AI Engine & Chat Surfaces* (~77 d, front-loaded)
- **Backend:** Foundation (whole spine), **M2** (Conversation & AI Engine), **M9** (Notifications & Workers), **M10** bypass primitive.
- **Frontend:** **FE-Shell**, **FE-Chat** (chat-core), **FE-Widget**.
- **Also owns as shared primitives everyone builds on:** RLS/tenant-context harness, JWT + widget-key auth + RBAC dep, OpenAPI/DTO/RFC7807 conventions, **the typed SSE event protocol**, ports + in-memory fakes + seed CLI, transactional outbox, SSRF egress guard, AES-GCM crypto helper, rate-limit dep, log-redaction, the **grounding-gate definition + threshold calibration harness**, the **verify-in-code call site**, the **ticket-transition whitelist + guarded-CAS primitive**, and **the four non-negotiable CI-gate suites**.
- **Why:** these hold all four non-negotiables, the SSE runtime, and the FE foundation every other module mounts into. A mistake here is catastrophic (cross-tenant leak, hallucination, illegal transition), and getting the contracts stable early is what unblocks the juniors.

### 👤 Person-2 — Junior · *Knowledge, Records & Analytics* (the tenant-data vertical) (~63 d)
- **Backend:** **M3** (Knowledge/RAG), **M4** (Records & Connectors), **M8** (Analytics).
- **Frontend:** **FE-Knowledge**, **FE-Records**, **FE-AgentSettings**, **FE-Analytics**.
- **Consumes from P1:** RLS base, embedding/vector/connector **ports + fakes**, the **SSRF guard** and **AES-GCM helper** (does *not* hand-roll security), the grounding-gate definition, the `turn_metric` DTO, seed data.
- **Why:** a clean "load data → retrieve → measure" vertical. It is the *harder* junior track (two complexity-5/4 modules), so P1 pairs closely on the RAG threshold calibration and the connector security review.

### 👤 Person-3 — Junior · *Tenancy, Ticketing, Escalation & Agent Ops* (the human-operations vertical) (~71 d)
- **Backend:** **M1** (Tenancy/IAM/Onboarding), **M5** (Ticketing & Tags), **M6** (Escalation), **M7** (Agent Workspace & Presence), **M10** `/ops` endpoints.
- **Frontend:** **FE-Auth**, **FE-Onboarding**, **FE-Staff**, **FE-Tickets**, **FE-AgentWorkspace**.
- **Consumes from P1:** auth/RLS deps, the **transition-whitelist + guarded-CAS primitive**, the **outbox primitive** + worker `with_tenant()`, Redis pub/sub patterns, the SSE protocol, the M10 bypass primitive. **Consumes from P2:** the 5 industry record schemas (frozen in Phase 0, so not a code blocker).
- **Why:** the M1→M5→M6→M7 chain is a single coherent "IAM + live human hand-off" vertical whose internal dependencies are all self-owned, so P3 never waits on P2. It is broad but mostly complexity-3; the genuinely tricky bits (claim-lock races, sweeps) sit on P1's primitives with P1 review.

> **If the two juniors want to swap:** person-2's track is deeper/harder per day (RAG + connector security); person-3's is broader/shallower. Swap only as a *whole vertical*, not module-by-module — the verticals are designed to be internally coupled and mutually decoupled.

### Load & balance
| Person | Backend days | Frontend days | Total | Notes |
|---|:--:|:--:|:--:|---|
| P1 (senior) | ~51 | ~26 | **~77** | Most days **and** most risk, by design. Front-loaded in Phase 0–1, then integrator/reviewer. |
| P2 (junior) | ~46 | ~18 | **~63** | Deliberately a touch lighter — its two modules are the hardest per day. |
| P3 (junior) | ~45 | ~24 | **~71** | Broader surface, mostly complexity-3, all contract-fronted. |

---

## 4. Guiding principles of the split

1. **Contracts before code.** Phase 0 freezes the OpenAPI/DTOs, the **SSE event union**, `kb_retrieve`/`lookup_record`/transition contracts, and the **5 industry record schemas** so all three can work in parallel against stubs — not against each other's half-built code.
2. **Non-negotiables converge on the senior.** The RLS harness + worker tenant-context, the grounding gate, the verify-in-code call site, and the transition whitelist are **owned and CI-gated by P1**; juniors consume them as libraries/tables and never re-implement them.
3. **Security primitives are centralized.** One SSRF resolve-and-validate guard, one AES-GCM helper, one rate-limit dep, one log-redaction filter, one auth dep — in Foundation. **No junior ever hand-rolls a security control.**
4. **Ports + fakes = offline dev.** `FakeLLM`, `FakeEmbedder`/`FakeReranker`, and MailHog + a multi-tenant seed (with *deliberately colliding* record keys across tenants) let every vertical run and test with **no vendor keys and no cloud budget**. This is a Phase-0 deliverable, not an afterthought.
5. **Verticals are full-stack and decoupled.** Each backend module is paired with its own frontend so a feature is demoable end-to-end; intra-vertical dependency chains stay inside one owner.
6. **Walking skeleton before build-out.** We build the thinnest possible end-to-end slice (one tenant, one grounded streamed turn, one ticket lifecycle, one metric) in Phase 1 to exercise the M1+M2+M3+M5+SSE+RLS seam early — this is how we avoid the "build M1, then M2, then…" horizontal-layer trap.

---

## 5. Shared-first contracts (Phase 0 — freeze these before parallel work)

These are the artifacts everyone codes against. **If one slips, everyone downstream reworks — so Phase 0 exit criteria require them frozen and committed.**

| Contract | Owner | What it pins down |
|---|:--:|---|
| **Tenant-context + RLS harness** | P1 | One DB-session dependency issuing `SET LOCAL app.tenant_id` inside each request transaction; `FORCE ROW LEVEL SECURITY` + `WITH CHECK` on every tenant table; a `with_tenant(tid)` context manager for **workers**; a **two-tenant leak test** wired into CI. *(See [IMP-SEC-1], [IMP-DEL-2].)* |
| **Auth model** | P1 | JWT-staff → current-staff+tenant; anonymous **widget-key → tenant** + Origin/`allowed_domain` check; `require_permission()` RBAC dep; `SameSite=Strict` httpOnly refresh cookie; short access-token TTL. |
| **OpenAPI spec + Pydantic DTOs + typed FE client** | P1 | Request/response DTOs committed **first** so the OpenAPI exists before routes; FE-Shell generates the typed client both juniors import. Field/enum shapes frozen. |
| **SSE event protocol** | P1 | A discriminated union keyed on `type`: `status`/`filler`, `token`, `citation`, `final`, `error`, `done` — authored **once** as a Pydantic model **mirrored to a TS type**, with a checked-in fixture asserted by both a backend and a frontend test. *(OpenAPI codegen cannot type SSE — this is the highest-drift contract; see [IMP-FE-5], [IMP-DEL-1].)* |
| **`kb_retrieve` grounding contract** | P2 (co-authored w/ P1) | `kb_retrieve(query, tenant, N, top_k, threshold) → GroundedResult{parent-expanded chunks, citations} \| NO_GROUNDING \| KB_NOT_READY`; gate = **top-1 rerank score ≥ threshold**; M3 *reports*, M2 *decides*. *(See [IMP-RAG-1], [IMP-ENG-1].)* |
| **`lookup_record` contract + verify seam** | P2 (co-authored w/ P1) | `Resolver.fetch(tenant, record_type, key) → RawRecord \| NotFound \| ConnectorError` (**fetch only, no verdict**; `RawRecord` carries the **verify-field value + the returned fields**). **Verify + status assembly lives in M2 engine code**, returning `{ok\|not_found\|unverified\|invalid_type\|rate_limited}`; a `ConnectorError` (timeout/auth/connection) maps to the existing tool-failure fallback→escalate. *(See [IMP-DEL-3]; connector_error per PRD §4.9.)* |
| **5 industry record schemas + verify-field metadata** | P2 | retail / logistics / telecom / healthcare / travel schemas with each schema's `verify` field, **match rule (email casefold / phone digits-only / name casefold / DOB exact)**, and attempts cap (**healthcare = 1**). Retail warranty carries an `order_id` **alias key**. Frozen because M1's template downloads + M4 validation + M2 verify all depend on them. |
| **Ticket transition-whitelist + guarded-CAS helper** | P1 (impl by P3) | The AI whitelist as `(from, to, allowed_actors[])` tuples + one `apply_transition(ticket, to, actor)` that does `UPDATE … WHERE state=:expected` (compare-and-swap). *(See [IMP-TKT-1], [IMP-TKT-2].)* |
| **Outbox + `turn_metric` contracts** | P1 | `core/events.py` write-outbox-in-same-transaction primitive (at-least-once + dedupe key) and the canonical `turn_metric` DTO written by the engine. |
| **Ports + fakes + seed** | P1 | `LLMPort` (chat/tool-loop/structured-output + capability flag), `EmbeddingPort` (embed + rerank + **dimension**), `StoragePort`; `FakeLLM`/`FakeEmbedder`/`FakeReranker`; MailHog; seed CLI (≥2 tenants, ≥2 industries, colliding keys). |
| **FE-Shell foundation** | P1 | design system, typed client, auth interceptor + **single-flight refresh**, `useSSE` hook, RBAC UI gating — every feature module mounts into this. |

---

## 6. Cross-module dependency graph (so you always know what's unblocked)

```
                          ┌─────────────────────────────────────────────┐
                          │  FOUNDATION  (P1)                            │
                          │  RLS harness · auth+RBAC · ports+fakes ·     │
                          │  outbox · SSRF guard · AES-GCM · SSE proto · │
                          │  OpenAPI/DTOs · rate-limit · redaction ·     │
                          │  transition-whitelist CAS primitive · seed  │
                          └───────────────┬─────────────────────────────┘
        ┌─────────────────────┬───────────┼───────────────┬──────────────────────┐
        ▼                     ▼           ▼               ▼                      ▼
  ┌───────────┐        ┌───────────┐ ┌─────────┐   ┌───────────┐          ┌───────────┐
  │ M1 IAM    │        │ M3 RAG    │ │ M4 Recs │   │ M2 ENGINE │◄────────►│ M9 Workers│
  │  (P3)     │        │  (P2)     │ │  (P2)   │   │   (P1)    │  outbox  │   (P1)    │
  └─────┬─────┘        └────┬──────┘ └────┬────┘   └─────┬─────┘          └─────┬─────┘
        │ tenant/staff/     │ kb_retrieve │ lookup_record│ structured_out       │ sweeps
        │ agent_settings    │             │              │ + tags + escalate    │ + email
        ▼                   └─────► M2 tool loop ◄────────┘                      │
  ┌───────────┐                                    ▲                            │
  │ M5 Tickets│◄───────────────────────────────────┘ (create/transition/tag)    │
  │  (P3)     │────────► M6 Escalation (P3) ────────► M7 Agent Workspace (P3)◄───┘
  └───────────┘                                         ▲ presence/queue/claim
        │                                                │
        └──────────► M8 Analytics (P2) ◄─────────────────┘ (turn_metric, ticket_event)
                            │
                            ▼
                     M10 Ops (P1 primitive + P3 endpoints)

  FRONTEND:  FE-Shell/Chat/Widget (P1)  ──►  mounts every feature UI
             FE-Knowledge/Records/AgentSettings/Analytics (P2)
             FE-Auth/Onboarding/Staff/Tickets/AgentWorkspace (P3)
```

**Reading it:** Foundation is a prerequisite for *everything*, so P1 front-loads it. Once the Phase-0 contracts exist (even as stubs + fakes), all three verticals proceed in parallel. The only cross-junior dependency is **P2's 5 record schemas → P3's M1 template downloads**, resolved by freezing the schemas in Phase 0.

---

## 7. Phased build plan (with integration checkpoints)

> Phase lengths assume ~2 devs of junior throughput + 1 senior. Treat them as sequence, not a calendar promise.

### Phase 0 — Foundations & Contracts
Stand up the shared spine and **freeze every cross-module contract** so parallel work can't drift. Prove tenant isolation before any feature is written.
- **P1:** RLS/tenant harness (`SET LOCAL` + `FORCE RLS` + worker `with_tenant` + **two-tenant leak CI test**); JWT/widget-key auth + RBAC dep; OpenAPI+DTO+RFC7807 skeleton; **SSE event schema + fixture**; ports + `FakeLLM`/`FakeEmbedder`/`FakeReranker` + MailHog + seed CLI; SSRF guard; AES-GCM helper; outbox primitive; transition-whitelist CAS primitive; `docker-compose` + Alembic harness.
- **P2:** co-author `kb_retrieve` / `lookup_record` / **5 industry-schema** contracts with P1; scaffold M3/M4 resolvers against fakes; scaffold FE-Knowledge/FE-Records against the mock client.
- **P3:** co-author the transition-whitelist table + ticket/tag/queue DTOs + auth-UI contract; scaffold M1 tenant/staff/role/agent_settings tables + migrations on the RLS base; scaffold FE-Auth against the mock client.
- **✅ Checkpoint:** two-tenant RLS leak test **green in CI**; OpenAPI generates a working typed client; the SSE fixture parses in the FE; `docker-compose up` brings the full stack with fakes + seed data.

### Phase 1 — Walking-skeleton vertical slice
One in-app-console chat turn, end-to-end across **M1(auth) + M2 + M3 + M5 + SSE + turn_metric**, for a single seeded tenant.
- **P1:** minimal M2 tool loop (single `kb_retrieve` tool), grounding gate on a provisional threshold, SSE token+citation streaming, `structured_out` persist, verify-in-code call site (stub), transition-whitelist enforcement; FE-Shell + chat-core streaming renderer.
- **P2:** minimal M3 ingest (upload→parse→chunk→embed via `FakeEmbedder`) + hybrid retrieve→RRF→rerank→gate over ~3 seeded docs; **provisional threshold calibration** (paired with P1); FE-Knowledge source list + upload.
- **P3:** M1 signup/login + session issuance + agent_settings read; M5 create-ticket + guarded-CAS `new→ai_handling→resolved` + resolution-summary stub; FE-Auth login + FE-Onboarding industry pick.
- **✅ Checkpoint:** admin logs into the seeded tenant, asks a question in the in-app console, and receives a **grounded streamed answer with a citation** (or `NO_GROUNDING → "I don't know"`); the ticket transitions `new→ai_handling→resolved`; **exactly one** `turn_metric` row is written.

### Phase 2 — Feature build-out (parallel verticals)
- **P1:** harden M2 — tool caps + `max_tool_calls`, 20s-timeout FSM, idempotency SETNX start-lock, structured-output validate+retry→escalate fallback, single-active-turn lock, prompt-injection delimiting of tool results; ship FE-Widget (Shadow DOM + async loader).
- **P2:** M4 full (5 schemas, upload validation + 50k cap, DB & API connectors behind the SSRF guard + AES-GCM, connector test, **durable verify-attempt Redis counter**); M3 reingest/delete (**delete-last swap**), structure-aware chunking for tables/lists, contextual augment on gpt-4o-mini; FE-Records + FE-Knowledge + FE-AgentSettings.
- **P3:** M1 full (RBAC, staff invite, widget-key rotate, template downloads consuming M4 schemas, embed snippet, hot-cached agent_settings CRUD); M5 full (`tag_def`/`ticket_tag` CAS approve/reject, reopen 72h from `closed_at`, search/filter); FE-Onboarding + FE-Staff + FE-Tickets.
- **✅ Checkpoint:** end-to-end onboarding (signup→industry→template→upload KB+records→configure→embed snippet) works; a record lookup with identity verification returns `ok`/`unverified`/`not_found` **neutrally** (same message for the last two); the widget streams on an external test page.

### Phase 3 — Escalation + Agent Workspace + Realtime
"No dead ends" hand-off works live and after-hours; the AI provably steps back once a human is involved.
- **P1:** M2 **ticket-state gate** (AI answers only in `{new, ai_handling}`; canned "a human is handling this" in `escalated`/`with_agent`); escalate-tool wiring; **escalate-dominates-resolve** precedence; deterministic sensitive-intent backstop + first-class "talk to human" signal; supply the `escalation_context` DTO.
- **P2:** M4 live-record re-fetch **read path** for the workspace (with a "live data unavailable — retry" failure state, distinct from the customer verify flow); finalize the `turn_metric` write helper with P1; provide the **grounding-gated** "suggested reply" input.
- **P3:** M6 (triggers, presence check, after-hours capture-email + SLA + support notify via outbox); M7 (presence w/ **Redis TTL heartbeat**, FIFO-by-`escalated_at` queue, **claim = guarded-CAS lock** + server-side read-only for others, reply/notes/resolve, tenant-scoped pub/sub deltas, live-record panel); FE-AgentWorkspace + FE-AgentSettings escalation config.
- **✅ Checkpoint:** a no-grounding turn **and** an explicit "talk to human" both escalate; an agent sees the new escalation in the live queue in real time, **claims it (second agent goes read-only)**, replies to the customer, and resolves; after-hours captures an email and notifies support in MailHog.

### Phase 4 — Analytics, Ops, Workers & Hardening
- **P1:** M9 (notification worker + SMTP; **outbox drain with `SELECT … FOR UPDATE SKIP LOCKED`** + `email_log` dedupe; retry/dead-letter; **idempotent query-driven** CAS sweeps for idle-resolve/close/reopen/SLA; two-queue `interactive`/`batch` Celery; ingestion watchdog); the **four non-negotiable CI-gate suites**; grounding-threshold calibration on a labelled set.
- **P2:** M8 full (rollups from `turn_metric` typed columns + `ticket_tag`; `overview`/`tags`/`latency`/`cost` endpoints); FE-Analytics dashboards; retrieval eval set incl. one CJK + one RTL case.
- **P3:** M10 `/ops` endpoints (list/suspend tenants, health, usage) on P1's bypass primitive with **suspension rejected at session mint**; wire the ticketing/escalation scheduled sweeps + SLA-nudge idempotency into M9; FE-AgentWorkspace polish (queue deltas, reconnect).
- **✅ Checkpoint:** analytics dashboards render real per-turn metrics; the operator suspends a tenant and its widget/chat is **rejected**; escalation + SLA emails deliver via MailHog with dedupe; **all four non-negotiable CI suites are green**; the email outbox survives a worker crash (at-least-once).

---

## 8. Improvements over the original flow

> These are the **real gaps we found** in the design docs, each verified by an adversarial review and kept only if it matters for a POC. Each has an **ID** so your personal file can point at it. Format: *Problem → Better approach → effort → owner.* Most are **small doc/spec clarifications**, not rewrites — the original design is strong; these are the sharp edges.

### Security & multi-tenancy
- **[IMP-SEC-1] RLS on pooled async connections is the whole ballgame — pin the mechanism.** *Problem:* the docs only say "request-scoped tenant context + RLS setter". With an async pool, a session-level `SET app.tenant_id` **leaks into the next request on the same connection** = cross-tenant breach. *Fix:* one transaction per unit of work; set context with **`SET LOCAL app.tenant_id`** (or `set_config(...,true)`) inside it; app connects as a **non-owner, non-superuser** role; `ENABLE` + **`FORCE` RLS** on every table; policy `USING (tenant_id = current_setting('app.tenant_id', true)::uuid)` **with `WITH CHECK`**. *(small · P1)*
- **[IMP-SEC-2] File bytes as Postgres Large Objects break the RLS claim.** *Problem:* LOs live in `pg_largeobject` — **not** covered by table RLS; the "file bytes isolated by RLS" claim is false at the DB layer. *Fix:* store bytes in a tenant-scoped **`bytea`** column (chunked if needed) on the RLS-protected table. 25 MB is well under limits, TOAST handles it, and there's no orphaned-LO cleanup. *(small · P2 storage / P1 port)*
- **[IMP-SEC-3] `widget_key` + CORS is not an authorization boundary.** *Problem:* the widget key is *public* (pasted in a `<script>`); CORS/Origin checks only constrain real browsers — a script forges/omits Origin. *Fix:* treat `widget_key` as a public identifier; **server-mint an opaque 128-bit `session_id`** (never trust a client-supplied one), scope conversation read/write to that minted session, and make the anonymous endpoints the explicit abuse-control point via per-`(tenant, widget_key, IP)` rate limits. *(small · P1+P3)*
- **[IMP-SEC-4] "Retrieved content is data, not instructions" has no enforcing mechanism.** *Problem:* it's asserted but the engine is a tool loop; nothing structurally stops injected KB/record/crawl text from steering the model (and escalation/tagging are model-driven, so injection can suppress the safety net). *Fix:* pass KB chunks + record fields to the model **only as tool-result messages** (never concatenated into the system prompt), wrapped in explicit delimiters, with a standing instruction that everything inside is untrusted data. *(small · P1)*
- **[IMP-SEC-5] SSRF defense is a weak blocklist and the crawler has none.** *Problem:* "block internal hosts" is a blocklist (bypassable via DNS rebinding, redirects, IPv6/link-local, cloud-metadata IP); the **URL crawler** isn't covered at all though it's a textbook SSRF sink. *Fix:* **one shared resolve-and-validate guard** (used by crawler + api_resolver + db_resolver): resolve the host, reject if *any* resolved IP is loopback/private/link-local/reserved, **pin the connection to the validated IP**, disable auto-redirects (or re-validate each hop); add crawl bounds (max pages/depth/bytes, per-fetch timeout, robots). *(medium · P1 guard, P2 use)*
- **[IMP-SEC-6] Identity verify-attempt cap is session-scoped, and sessions are free.** *Problem:* the "3 attempts (healthcare 1)" cap resets by starting a new anonymous session → identity brute-force / PII enumeration. *Fix:* persist the counter in **Redis keyed on `(tenant_id, record_type, key)`** with a TTL lockout that survives new sessions — **never** scoped to `session_id`. This is what backs the `rate_limited` status. *(small · P2 in verify path, on P1 rate-limit dep)*
- **[IMP-SEC-7] PII/PHI → third-party LLM/embeddings + into logs.** *Problem:* transcripts + verified record fields (DOB/phone/email; healthcare = PHI) go to the OpenAI gpt-4o-mini LLM (the one mandatory cloud dependency, now that embeddings+rerank are self-hosted) **and** risk landing in logs/traces. *Fix:* add a non-negotiable **log-redaction** rule (never log raw message bodies, verify values, record fields, or bound DB params — only IDs + hashes); document the LLM-egress trade-off; offer BGE-M3 self-host as the regulated-tenant escape hatch. *(small · P1)*
- **[IMP-SEC-8] AES-GCM connector creds have no key-management story.** *Fix:* 4-line note in `core/security`: master key from a Docker/file secret or env (accept it co-locates with the host — no cloud KMS in a POC); use `cryptography`'s `AESGCM` (don't hand-roll); random 96-bit nonce per encryption; **bind ciphertext to `(tenant_id, connector_id)` via AAD**. *(small · P1 helper, P2 use)*
- **[IMP-SEC-9] RLS-bypass operator role needs least-privilege + tamper-evident audit.** *Fix:* bypass = a **dedicated least-privilege Postgres role on its own connection** used only by `/ops` handlers (never the shared request pool), behind a single `with platform_bypass(actor, action):` context manager that writes an append-only **non-RLS `platform_audit_log`** row in the same transaction; operator identity is a separate platform-level principal with `scope=platform` (never a tenant JWT). *(small · P1)*

### RAG correctness
- **[IMP-RAG-1] Define the grounding gate precisely.** *Problem:* "relevance threshold = eval-derived" against uncalibrated, language-dependent rerank scores, and it's ambiguous whether it's top-1/mean/count. *Fix:* pin the gate as **"top-1 rerank score ≥ threshold"** (one documented aggregation) **and** require the answer to cite ≥1 chunk; add a **relative top1-vs-top2 margin** alongside the absolute cutoff. Build a **calibration harness** (§9) rather than a magic constant; expose to tenants only a coarse *strict/balanced/lenient* dial. *(small · P1 def + P2 impl)*
- **[IMP-RAG-2] Postgres FTS breaks for CJK/RTL — "hybrid" silently collapses to dense-only.** *Fix:* add a `language` column to `kb_chunk`; build the vector with `to_tsvector(<regconfig>, text)`, defaulting to **`'simple'`** (not `'english'`) for unknown/CJK/mixed content so you never apply wrong-language stemming; consider `pg_search`/ParadeDB for real BM25. *(small · P2)*
- **[IMP-RAG-3] Fixed-token chunking shreds tables/lists.** *Fix:* give "structure-aware" chunking real teeth for the two structures that break answers: keep each **table** as an atomic chunk (repeat the header row into any split), and keep **numbered lists/procedures** intact. *(medium · P2)*
- **[IMP-RAG-4] Contextual augmentation has no budget or determinism.** *Fix:* run it on **gpt-4o-mini** (the single provider), **temperature 0 + versioned prompt** (reproducible on re-ingest), cache one context per *parent* (not per child), make it **per-tenant toggleable** (it's one LLM call per chunk at ingest), and record ingest token cost as a metric. *(small · P2)*
- **[IMP-RAG-5] Empty/ingesting/stale KB is indistinguishable from "no answer".** *Fix:* before the gate, if the tenant has **zero `ready` sources**, return a distinct **`KB_NOT_READY`** signal so the engine says "I'm still learning <tenant>'s docs" (offer human / capture email) instead of a generic "I don't know → escalate". *(small · P2+P1)*
- **[IMP-RAG-6] Retrieval-only gate never checks generated faithfulness; citation granularity undefined.** *Fix:* citations point to the **exact child span**, resolvable within the expanded 2k parent; the generation prompt attaches a citation to each factual claim; drop uncited claims. *(small · P1+P2)*
- **[IMP-RAG-7] LLM query-rewrite before the gate has no raw-query fallback.** *Fix:* run hybrid retrieval on **both** the rewritten query and the raw user message, and fuse both candidate sets through the existing RRF step before rerank — a bad rewrite can't zero out recall. *(small · P2)*
- **[IMP-RAG-8] Re-ingest can't be truly transactional across external embed calls.** *Fix:* **delete-last** — build the new version's chunks+vectors, atomically flip the serving pointer, then delete the old vectors last; a failed re-ingest leaves the prior version live (no false `NO_GROUNDING` during the embed window). *(trivial · P2)*

### AI engine, tool loop & streaming
- **[IMP-ENG-1] You cannot both validate JSON and stream it cleanly in one pass.** *Fix:* keep single-pass but **separate the channels** — stream **only the answer text** on `token` events; emit the validated control envelope (tags, escalate, retrieval_hits, detected_language, advisory_confidence) as a trailing **`final`** event that is Pydantic-validated **before** any persistence/transition/tag/escalate fires. *(small · P1)*
- **[IMP-ENG-2] Missing the one number that matters: `max_tool_calls_per_turn`.** *Problem:* gpt-4o-mini oscillates; trivial caps are pinned but the loop bound isn't. *Fix:* add `max_tool_calls_per_turn` (≈4–6) to config; on cap, force a final answer ("answer from what we have, else escalate"); `NO_GROUNDING` is a **terminal** signal for the retrieve path. *(small · P1)*
- **[IMP-ENG-3] The 20s timeout has undefined scope and its "retry" can double-fire side effects.** *Fix:* define 20s as **time-to-first-answer-token** (or per-step budget), **not** whole-turn wall-clock (a normal DB-connector lookup is 5s+1 retry ≈ 10s + model calls → trips healthy turns otherwise); `stall_retries` retries only the **stalled step**, never the whole turn; guard all side-effects with the idempotency key. *(small · P1)*
- **[IMP-ENG-4] `client_msg_id` idempotency semantics are undefined under SSE drops.** *Fix:* on POST, **`SETNX idem:{tenant}:{conversation}:{client_msg_id}`** (TTL ≈ turn cap) **before** the loop; duplicate-in-flight → attach/replay, never a second loop; duplicate-done → return cached result. This prevents duplicate escalations/tickets/emails on flaky mobile networks. *(small · P1)*
- **[IMP-ENG-5] Concurrent messages in one session are unmodeled.** *Fix:* state **single-active-turn-per-conversation**: FE disables the composer while streaming + aborts the prior stream; backend acquires a **Redis per-conversation lock**. *(small · P1 + FE)*
- **[IMP-ENG-6] Single-provider LLM routing.** *Decision:* **drop Groq for the POC** — route the tool loop, structured output, and all aux tasks (query rewrite, summaries, tag classification) to **gpt-4o-mini**: one key, one provider, no cross-provider fallback to reason about. Keep `model_router` as the seam so a cheaper aux model can be reintroduced later behind the same interface; keep summary generation off any blocking path. *(trivial · P1)*
- **[IMP-ENG-7] Localized filler is a chicken-and-egg (language is detected inside the call).** *Fix:* a typed `status` SSE event (`retrieving`/`looking_up`/`generating`) that the widget maps to **pre-translated chrome strings**, so status localizes without server-side language knowledge. *(small · P1 + FE)*

### Ticketing state machine & concurrency
- **[IMP-TKT-1] The AI answer loop is not gated by ticket state — it keeps replying during `with_agent`/`escalated`.** *(This is the "no auto-resume" guarantee, and it currently has no enforcement.)* *Fix:* add a **state gate at the top** of `POST /conversations/{id}/messages`: if `state ∈ {escalated, with_agent}` persist the message + route to the agent/queue + stream a canned "a human is handling this" turn; **do not invoke the model**. *(small · P1 + P3)*
- **[IMP-TKT-2] Transitions have no concurrency control** (the idle-resolve sweep and the message handler are two uncoordinated writers). *Fix:* every transition is an atomic **compare-and-swap**: `UPDATE ticket SET state=:new WHERE id=:id AND state=:expected`; 0 rows = "already taken" → fire no side-effects. *(small · P3 on P1 primitive)*
- **[IMP-TKT-3] Simultaneous escalate + auto-resolve has no precedence.** *Fix:* **escalate strictly dominates resolve** — if a turn sets `escalate` or any trigger fires, transition to `escalated` and never also resolve in that turn; escalate cancels the pending idle-resolve timer. *(small · P1+P3)*
- **[IMP-TKT-4] Reopen window (72h) < session (30d), and its anchor is undefined → dead end.** *Fix:* pin reopen anchor to **`closed_at`**; a message after 72h on a live session opens a **fresh ticket** (state it explicitly — "one ticket per conversation" is fine for the POC); denormalize `ticket.language` + add `UNIQUE(tenant_id, conversation_id)` (get-or-create). *(small · P3)*
- **[IMP-TKT-5] Single mutable `linked_record` pointer → wrong-record leakage across turns.** *Fix:* record the verified `{type,key}` at **per-turn grain** in `message.structured_out` (tie it to the answered record), not only the single ticket pointer. *(small · P2+P3)*
- **[IMP-TKT-6] Tag "approve-flip" grain is ambiguous (def vs instance).** *Fix:* `tag_def.status` is the single authoritative approval state; `ticket_tag` references `tag_def_id` and derives its displayed state; approving a def backfills existing pending instances in one transaction. *(small · P3)*

### Escalation & agent presence
- **[IMP-ESC-1] Presence has no liveness — a crashed "Available" agent disables the after-hours safety net.** *Fix:* back presence with a **Redis key + short TTL (~60s)** set on SSE-connect and refreshed by the agent-workspace SSE connection; missed refresh → auto-`Away`. *(small · P3)*
- **[IMP-ESC-2] Claim-lock has no atomicity or lease.** *Fix:* claim = single guarded CAS `UPDATE … WHERE id=:id AND status='escalated' AND assignee IS NULL`; loser gets **409 + current holder** and flips read-only via pub/sub; tie the lock to the presence heartbeat so a dead agent's claim auto-releases. *(small · P3)*
- **[IMP-ESC-3] Presence is a race against enqueue; the docs contradict themselves.** *Fix:* **always enqueue the escalated ticket idempotently**, regardless of presence; presence only decides the customer-facing message + whether to *also* fire the after-hours SLA path — it is never a gate on queueing. *(small · P3)*
- **[IMP-ESC-4] N-failed-attempts conflates `not_found` (benign typo) with `unverified` (identity mismatch).** *Fix:* count `unverified` against the **durable `(tenant, record_type, key)` counter** ([IMP-SEC-6]); treat `not_found` more leniently; use two counters — `verify_attempts` vs answer/`stall_retries`. *(small · P2+P3)*
- **[IMP-ESC-5] Sensitive-intent trigger is brittle across languages + ambiguously model-vs-code.** *Fix:* the **"talk to a human" button posts a first-class escalate signal** (a flag, never a prefilled text string the model re-interprets) → deterministic and cross-language for free; keep the model's sensitive-intent detection as a soft backstop only. *(small · P1+P3)*
- **[IMP-ESC-6] "Suggested reply" + escalation summary escape the grounding gate.** *Fix:* constrain the agent **suggested reply by the same grounding gate**; if there's no grounding, omit it and show a fixed label. There is also **no storage for the escalation summary** — add an escalation-summary artifact `{transcript_ref, summary, kb_sources, suggested_reply, linked_record_ref}` (reuse the summary table with a type discriminator). *(small · P1 gen + P3 store)*
- **[IMP-ESC-7] After-hours capture-email has no data field.** *Fix:* add `ticket.contact_email` (nullable, unverified, **kept distinct** from `linked_record`) + `support_notification_email` in agent_settings. *(small · P3)*
- **[IMP-ESC-8] Queue ordering + SLA-nudge cadence undefined.** *Fix:* queue = **FIFO by `escalated_at`** (agent-facing wait-time only, never a customer ETA); the unclaimed nudge re-fires on a fixed interval with an idempotency key scoped per `(ticket_id, nudge_round)` so it repeats across rounds but dedupes within one. *(small · P3)*

### Data model & scalability
- **[IMP-DAT-1] Pin the pgvector index + RLS-filtered ANN behavior.** *Fix:* **HNSW** index (`m=16, ef_construction=200`), `SET hnsw.ef_search=100` (≥ the 40 candidates), and **enable pgvector 0.8 iterative scans** (`hnsw.iterative_scan=relaxed_order`) so the RLS `tenant_id` filter doesn't silently return < k neighbors. *(small · P1/P2)*
- **[IMP-DAT-2] Name the migration tool + hand-author the risky DDL.** *Fix:* **Alembic** under `infra/db/`; the pgvector extension, HNSW opclass indexes, RLS policies, and FTS indexes are **authored by hand** in migrations, never left to autogenerate (Alembic doesn't diff policies/extensions/opclasses and would ship a table missing its RLS policy = tenant leak). *(small · P1)*
- **[IMP-DAT-3] Two Celery queues from day one.** *Fix:* `interactive` (email/notify + idle/SLA/reopen sweeps) and `batch` (ingest/crawl/embed), each with its own worker in compose, so one tenant's bulk ingest can't starve everyone's escalation emails. *(small · P1)*
- **[IMP-DAT-4] Full-replacement dataset upload needs atomic swap.** *Fix:* run the DELETE+bulk-INSERT in **one transaction** (MVCC keeps live lookups reading the old rows until commit); after swap, null any orphaned `linked_record` pointers gracefully (lookup returns `not_found`). *(small · P2)*
- **[IMP-DAT-5] Analytics dimensions duplicated in `structured_out` + `turn_metric`.** *Fix:* make **`turn_metric` the single source** for analytics (add `detected_language` as a typed column); rollups never read `structured_out`. Add a **`metric_rollup`** table (or materialized view) — the docs require rollups but define no table. Store latency as a mergeable histogram/t-digest (percentiles aren't additive across days). *(trivial–small · P2)*

### Workers, email & reliability
- **[IMP-WRK-1] "Idempotent sends" over SMTP is impossible as exactly-once — say at-least-once + dedupe.** *Fix:* reword to "at-least-once with dedupe"; give `outbox` `status/attempts/next_attempt_at/locked_at/dedupe_key`; drain via **`SELECT … WHERE status='pending' … FOR UPDATE SKIP LOCKED`**; dedupe in Postgres via `email_log UNIQUE(tenant_id, dedupe_key)` (`INSERT … ON CONFLICT DO NOTHING`, send only if inserted); add a **reaper** that resets rows stuck in `sending`. *(small · P1)*
- **[IMP-WRK-2] Redis-as-broker durability + visibility_timeout will lose/duplicate tasks.** *Fix:* `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`, AOF (`appendonly yes`); make embed tasks **idempotent** (upsert `kb_chunk` by `(source_id, content_hash)`, skip already-embedded) so a redelivery can't duplicate rows/citations/embedding compute. *(small · P1)*
- **[IMP-WRK-3] Scheduled sweeps are exposed to double-fire + post-downtime storms.** *Fix:* implement timers as **`due_at` columns + query-driven Beat sweeps** (`WHERE due_at <= now()`), not per-ticket `eta`/`countdown` broker delays; guard each transition with CAS + `FOR UPDATE SKIP LOCKED`; run exactly one Beat (or `celery-redbeat`). Missed ticks self-correct after a deploy. *(small · P1)*
- **[IMP-WRK-4] Ingestion FSM is too coarse for resume.** *Fix:* chunk ingestion into idempotent per-batch tasks with checkpointing so an embedding failure/timeout at chunk 5000 resumes from the last committed batch instead of restarting from zero; flip `source→ready` only after all batches commit; embed calls run **outside** any DB transaction. *(trivial–small · P1+P2)*
- **[IMP-WRK-5] The "no dead ends" net is single-channel email with a circular nudge.** *Fix:* expose email **DLQ depth + recent send-failure count on `GET /ops/health`** so a stalled SMTP relay is visible, not silent; treat a dead-lettered escalation notification as an ops alert. *(small · P1+P3)*

### Frontend architecture & DX
- **[IMP-FE-1] SSE over POST has no resume protocol — reconnect duplicates tokens or re-runs the billable turn.** *Fix:* standardize the transport on **`fetch()` + ReadableStream** (native `EventSource` can't POST or send a Bearer header); define reconnect against `client_msg_id` idempotency (replay the same id → returns the in-flight/finished turn, never re-enters the loop); attach a monotonic `id:` per event + buffer the last N in Redis for short-window replay. *(small · P1)*
- **[IMP-FE-2] chat-core "framework-light, mounted 3 ways" leaves the Preact↔React boundary undefined.** *Fix:* **author chat-core's view once in Preact**, reuse it verbatim in the widget, and mount it into the React SPA (console + hosted page) as a **Preact island** (small React wrapper). Keep `sse.ts`/`session.ts`/`i18n` framework-agnostic. *(small · P1)*
- **[IMP-FE-3] Shadow DOM does not exempt the widget from the host page's CSP.** *Fix:* publish the **exact CSP directives** tenants must add (`script-src <widget-origin>`, `connect-src <api-origin>`, `img-src data:`) beside the embed snippet; style the shadow tree via **`adoptedStyleSheets`** (constructable stylesheets — CSP-friendly, no inline-style); log a clear console error on CSP/CORS failure instead of dying silently. *(small · P1 + FE-Onboarding)*
- **[IMP-FE-4] Token-in-memory + refresh has no single-flight / boot-refresh → 401 storms cascade to logout.** *Fix:* **single-flight refresh** (first 401 starts one shared refresh promise; all others await it); **boot silent-refresh** on app load gating TanStack Query `enabled`; `SameSite=Strict` on the refresh cookie. *(small · P1)*
- **[IMP-FE-5] OpenAPI codegen can't type SSE or the JSONB `structured_out`.** *Fix:* the hand-authored SSE discriminated union (§5) is the single source of truth, mirrored Pydantic↔TS with a shared fixture asserted on both sides — this is the drift gate for the two juniors. *(small · P1)*
- **[IMP-FE-6] Agent live-queue realtime only pushes "new escalation".** *Fix:* extend the Redis pub/sub channel to publish **claim/release/resolve deltas**; the workspace keeps a queue store keyed by `ticket_id` and applies deltas (no ghost tickets); `GET /agents/queue` (derived from ticket state) is the source of truth on reconnect. *(small · P3)*
- **[IMP-FE-7] Widget `widget.js` has no size budget or two-stage loader.** *Fix:* the embed snippet is a **<2 KB async loader** that injects the bundle (never blocks the host page's parser); `widget.js` paints only the bubble on load, then **dynamic-imports** the chat panel on first open; CI bundle-size budget. *(small · P1)*
- **[IMP-FE-8] Missing endpoints the FE assumes:** a per-source status (`GET /knowledge/sources/{id}` or a `status`+`updated_at` field) for polling; a fetchable **resolved record schema** (`GET /records/schema`) for the connector field-map UI; an aggregated **`GET /tickets/{id}/context`** (transcript + AI summary + KB sources + suggested reply + live-record pointer) for the agent workspace; a `lock_version` on claim responses. Also: `ticket.priority` is filtered in FE-Tickets but **doesn't exist** — either add it (derived from escalation reason) or drop the filter. *(small · owners per module)*

### Delivery, testing & build-order
- **[IMP-DEL-1] The contract seam is code-first and SSE has no schema → FE is serialized behind BE.** *Fix:* Phase-0 **contract-first**: hand-author the OpenAPI + SSE union as committed artifacts and run FE against a **mock server** (MSW/Prism) so the shell/design-system/chat-core proceed before the endpoints exist. *(small · P1)*
- **[IMP-DEL-2] RLS has no isolation harness → a cross-tenant leak that passes tests.** *Fix (critical):* P1 builds the tenant/RLS harness **in Phase 0, before any repository or worker** — the `SET LOCAL` session dep, the worker `with_tenant()`, and a **two-tenant leak test wired into CI as a required gate**. *(medium · P1)*
- **[IMP-DEL-3] The `lookup_record` verify/resolver boundary is described contradictorily → the two halves get built incompatibly.** *Fix:* pin the port as `Resolver.fetch(tenant, record_type, key) → RawRecord | NotFound` (fetch only, no verdict); **verify + status assembly lives in M2's `lookup_record` tool** — resolvers never receive the verify value. *(small · P1+P2)*
- **[IMP-DEL-4] No offline dev story.** *Fix:* wire ports to **fakes by default** in dev/CI (real adapters behind an env flag): `FakeLLM` (canned structured output + scripted tool calls), `FakeEmbedder` (hash→stable vector), `FakeReranker`, MailHog, and a **multi-tenant seed with colliding keys**. No junior should need a vendor key to run the engine. *(medium · P1)*
- **[IMP-DEL-5] The grounding threshold is "eval-derived" with no harness.** *Fix:* during the Phase-1 slice, hand-label ~20–30 `(query, should_answer)` pairs per seeded tenant (incl. off-topic + one non-English), run them through the **real** hybrid+RRF+rerank path, dump scores, and pick a conservative default by eyeball. Re-calibrate whenever the reranker changes. *(small · P1+P2)*

> **Not in scope for the POC (deliberately deferred):** episode/child tickets, per-language threshold models, envelope-encryption/KMS rotation, a full SSE replay-buffer resume protocol, Postgres-native queue (pgmq) instead of Redis broker, and iframe widget fallback. We noted them so they're a conscious choice, not an accident.

---

## 9. The four non-negotiables — and their CI gates (owned by P1)

| Non-negotiable | Enforcement point | CI gate suite |
|---|---|---|
| **Identity verification** | `verify` runs in M2 engine code (`lookup_record` tool); resolvers only fetch | Verify-table test across all 5 templates **incl. healthcare N=1**; `unverified` and `not_found` return the *same* customer message |
| **Grounding gate** | M3 *reports* `grounded` vs threshold; M2 *decides* answer-vs-`NO_GROUNDING` | Off-topic query set → must refuse; on-topic → must answer with a citation |
| **Transition whitelist** | `apply_transition(ticket, to, actor)` guarded CAS in `domain/ticketing` | Allow/deny **matrix**: AI actor rejected on every edge except the 3 whitelisted |
| **Tenant isolation (RLS)** | `SET LOCAL` request dep + worker `with_tenant()` + `FORCE RLS` | Two-tenant leak test (set A, insert; set B, select → 0 rows) **incl. one worker path** |

**These four CI suites must be green before Phase 4 sign-off.** They are P1's, but they exercise everyone's code — treat a red gate as a release blocker.

---

## 10. Best-practice settings to bake in (web-verified, 2025–2026)

- **RLS:** app connects as a **non-owner** role; `SET LOCAL app.tenant_id` inside a per-request transaction; policy `USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (same)`; keep async pool default `reset_on_return='rollback'`; if PgBouncer is ever added → transaction pooling + `statement_cache_size=0`.
- **Hybrid retrieval:** RRF `k=60` (`score = Σ 1/(60+rank)`); fetch top ~30–50 from each arm, dedup by chunk id, weights 1.0/1.0; HNSW `m=16, ef_construction=200`, `ef_search=100`, **iterative scans on** (pgvector ≥ 0.8); fused `N=40 → rerank top-5`. Default embed = **BGE-M3 (ONNX, 1024-d)**, rerank = **bge-reranker-v2-m3 (ONNX)**. Re-calibrate the grounding threshold whenever you change the reranker or its quantization (BGE ↔ Cohere ↔ fp-vs-INT8) — scores aren't on a shared scale.
- **Self-hosted embeddings + rerank (ONNX):** serve **BGE-M3** (embed) + **bge-reranker-v2-m3** (rerank) from one small container (**fastembed** / HF **TEI** / **Infinity**) behind `EmbeddingPort`; ship the **INT8-quantized ONNX** build. **Latency profile:** ingest embedding is **background** (quantize hard — nobody's waiting) + one small embed per query; **rerank is the only heavy model in the query hot path** (~sub-250 ms quantized on CPU) — if it's slow, rerank fewer candidates (top-20 not 40) or add a GPU. Both models are **MIT** = commercial-safe; BGE-M3's 1024-dim matches the `vector(1024)` schema exactly.
- **Streaming:** build on the OpenAI **Responses API** deltas; answer text arrives **only** on `token` events; a trailing `final` carries validated metadata; emit a heartbeat (`: ping`) every ~15s; set `X-Accel-Buffering: no` + `proxy_buffering off` in nginx/Traefik so SSE isn't buffered. **Confirm gpt-4o-mini (or the current cheap mini tier) still supports json-schema structured output + streaming at build time.**
- **Widget:** `<script async>` <2 KB loader; `adoptedStyleSheets` for shadow styles; CORS echoes Origin only if it matches `allowed_domain` and uses `widget_key`+`session_id` in header/body (**not cookies**, to stay out of credentialed CORS); one persistent `role=log` `aria-live=polite` region; CSS logical properties for RTL.
- **Outbox/workers:** outbox row in the **same transaction** as the state change; Beat drains every ~1–5s with `FOR UPDATE SKIP LOCKED`; retry with `retry_backoff` + jitter, `max_retries≈6`, then `status='dead'` + ops alert; timers as `due_at` columns swept every ~30–60s; separate `notifications` vs `ingestion` queues.

---

## 11. Reference defaults (centralised as tenant config)

`session_id` 30d *(enforced: session stamped with `expires_at`; a new one is minted when expired)* · **per-turn timeout 20s = time-to-first-token** (`escalate_on_timeout`/`stall_retries`; worst-case turn bounded by `max_tool_calls_per_turn` × per-step budget) · **`max_tool_calls_per_turn` ≈ 4–6** · resolve/close idle 10m each · **reopen 72h from `closed_at`** · verify attempts 3 (**healthcare 1**), **durable per `(tenant, record_type, key)`** · connector 5s + 1 retry · per-file 25 MB · **per-tenant total KB bytes = configurable (`kb_total_bytes_limit`)** · 50k rows/record_type · child chunk ~300–500 tok, ~15% overlap, parent ~2k tok · hybrid **N=40, RRF k=60**, rerank top-k 5 · relevance threshold = eval-derived (**absolute top-1 rerank ≥ threshold**; top1-vs-top2 margin deferred) · **embed = BGE-M3 (ONNX, 1024-d); rerank = bge-reranker-v2-m3 (ONNX, INT8)** · **LLM = gpt-4o-mini (single provider)** · `ticket.priority ∈ {low, normal, high}` default `normal` · **escalation-reason enum = `no_grounding | explicit | sensitive | dispute | n_fails | proactive | timeout`** · autonomy default on.

### Industry record schemas (frozen by P2 in Phase 0)
| Industry | record_type(s) | key | verify | returned fields |
|---|---|---|---|---|
| Retail/E-commerce | **order, warranty** | order: `order_id` · warranty: `serial_no` **(with `order_id` as an alias key — either resolves the same warranty)** | email | order: `status`, `eta`, `tracking_ref`, *optional* `tracking_url` · warranty: `coverage`, `expiry` (claim steps from KB) |
| Logistics/Courier | shipment | tracking_no | phone or email | current_location, status, ETA |
| Telecom/ISP | subscription, billing | account_id | registered_mobile | plan, renewal_date, balance_due |
| Healthcare/Clinic | appointment | booking_ref | phone or DOB | date_time, provider, prep_instructions |
| Travel/Hospitality | booking | booking_ref | email or last_name | status, dates, itinerary |

**Pinned enums (frozen with the schemas):** order `status ∈ {placed, processing, shipped, delivered, cancelled}` · warranty `coverage ∈ {active, expired, void}` (`expiry` is a date). **Deterministic (code-driven) escalations:** `coverage=void`, and `status=delivered` + customer reports non-receipt, and a refund dispute on a `cancelled` order not covered by KB → all auto-escalate (reason `dispute`).
**Verify comparison semantics (§4.8.2, enforced in code):** email = casefold exact · phone = strip non-digits then exact · name = casefold exact · DOB = exact. Attempts: 3 / conversation / key (**healthcare = 1**) → escalate.

---

## 12. Top risks & how we're mitigating them

| Risk | Mitigation |
|---|---|
| **P1 is the serialization bottleneck** (owns spine + integrator) | Front-load Foundation + contracts + fakes in Phase 0; delegate leaf adapters (parsers, SMTP client, one vendor client) to juniors under review; keep M9 largely in Phase 4. |
| **M3/M4 are senior-required but owned by a junior (P2)** | P1 owns the dangerous primitives (grounding-gate def, SSRF guard, AES-GCM, verify call site) + the CI gates; pairs on threshold calibration in Phase 1; reviews connector security. |
| **Cross-tenant leak via RLS + pooling + workers** | `SET LOCAL` + `FORCE RLS` + worker `with_tenant()` + two-tenant CI gate ([IMP-DEL-2]) — built first, before any repo. |
| **SSE + `structured_out` can't be codegen'd → FE/BE drift** | One hand-authored Pydantic↔TS union + shared fixture asserted on both sides ([IMP-FE-5]). |
| **Contract-freeze slippage in Phase 0** cascades into M1↔M4, M2↔M4↔M5 rework | Phase-0 exit criteria explicitly require the 5 schemas, transition whitelist, and verify seam frozen. |
| **Concurrency correctness in P3's realtime work** (claim-lock, sweeps, presence) | P1 supplies the guarded-CAS + outbox primitives and reviews these specific spots. |
| **Vendor cost / false "no cloud"** | Fakes are the dev/CI default; real adapters behind an env flag. Embeddings+rerank **default to self-hosted BGE (ONNX)**, so the **only** mandatory cloud dependency is the gpt-4o-mini LLM. |

---

## 13. Definition of done (the demo we're building toward)

A single scripted end-to-end demo that proves the product:
1. **Onboard:** admin signs up → verifies email (MailHog) → picks *Retail* → downloads a CSV template → uploads 3 KB docs + a records CSV → configures persona/languages → copies the embed snippet.
2. **Go live:** the widget streams on an external test page; the hosted page works; the in-app console works.
3. **Grounded answer:** a customer asks a policy question **in another language** → gets a streamed, grounded answer **with a citation**.
4. **Record lookup:** asks "where's my order?" → engine slot-fills the key + verify value → **verifies in code** → returns status; a wrong verify value returns the neutral "couldn't match" message (same as not-found).
5. **Escalation:** clicks "talk to a human" (or hits a no-grounding/sensitive case) → ticket → `escalated`; the AI **stops answering**.
6. **Agent hand-off:** an *Available* agent sees the live queue, **claims** it (a second agent is read-only), reads the transcript + AI summary + KB sources + **grounding-gated** suggested reply + live record, replies, and resolves.
7. **After-hours:** with no agent online, the customer's email is captured, support is notified, and an SLA promise is shown.
8. **Insights:** the analytics dashboard shows volume, autonomous-resolution rate, escalation reasons, top tags, language distribution, latency p50/p95, cost/conversation, and CSAT.
9. **Ops + isolation:** the operator suspends a tenant → its chat is rejected; the **two-tenant RLS leak test** and the other three non-negotiable CI suites are green.

---

## 14. PRD coverage audit — corrections, additions & POC trims

> We audited this plan against the authoritative **`AI Customer Support Agent PRD.txt`** section by section. The plan already covered the PRD well; this section records the **deltas** — corrections to fix, small PRD-required details to add, and places we deliberately **trim back to POC scope**. **This section supersedes any earlier wording it references.** Each item is threaded into the relevant person file too.

### 14.0 LLM decision (resolves the one contradiction)
The PRD §4.1 says the server "relays **Claude's** tokens." **Decision (product owner, confirmed): the POC standardises on OpenAI `gpt-4o-mini`** as the single provider (matches the implementation plan + the existing OpenAI key). This is a **recorded, accepted deviation** from the PRD's "Claude" wording. `model_router` stays provider-agnostic and the M8 cost map is keyed by model id, so a later switch to Claude is a one-adapter change. No other doc changes needed for this.

### 14.1 Corrections (things that were wrong or would mislead a builder)
| # | Correction | Owner | File(s) |
|---|---|:--:|---|
| C1 | Retail `record_type(s)` is **`order, warranty`** (not "warranty/shipment" — `shipment` is Logistics). | P2 | §11 ✅ / P2 M4 |
| C2 | Warranty has a **primary key `serial_no` + alias key `order_id`** — either resolves the same warranty. Uniqueness on `serial_no`; build an `order_id→warranty` index; `lookup_record` tries the supplied key against both. | P2 | P2 M4 / §11 ✅ |
| C3 | `Resolver.fetch(...) → RawRecord \| NotFound \| **ConnectorError**`; `RawRecord` must carry the **verify-field value** in addition to the returned fields. `ConnectorError` (timeout/auth/connection) → existing tool-failure fallback→escalate. | P1+P2 | §5 ✅ / P1 M2 / P2 M4 |
| C4 | **`ticket.priority` is a required field** `{low, normal, high}` (default `normal`), **set on escalation per trigger** (sensitive/dispute→high). Keep the FE-Tickets priority filter — do **not** drop it. | P3 | P3 M5/M6 / IMP-FE-8 |
| C5 | **`owner` role removed** — RBAC is `admin + agent` (+ platform super-admin for M10) only, per PRD §5.1.1/§7. First signup = admin; multiple admins allowed. | P3 | P3 M1 |
| C6 | **Escalation-reason enum** is canonical: `no_grounding \| explicit \| sensitive \| dispute \| n_fails \| proactive \| timeout` (adds `dispute` for record-state escalations and `timeout` for the stall path). | P3 (owns enum) | P3 M6 / P1 M2 / P2 M8 |
| C7 | **Language stability**: FE-Chat must **not** re-switch locale/dir on every turn; only switch when `detected_language` changes to a new established value (pairs with L2 below). | P1 | P1 FE-Chat |

### 14.2 Additions (PRD requirements to make explicit — all small)
- **A1 — Deterministic (code-driven) escalations** in M2 `lookup_record` post-processing: `coverage=void`, `status=delivered` + customer reports non-receipt, and a refund dispute on a `cancelled` order not covered by KB → emit escalate (reason `dispute`). Not left to the model's soft backstop. *(P1)*
- **A2 — Proactive human offer (§4.5, "no sentiment detection"):** when verify/answer retries reach cap-1, or on `NO_GROUNDING` with no tool answer, the engine offers *"Would you like me to connect you to a human agent?"* instead of escalating immediately; a "yes" fires the first-class escalate flag (reason `explicit`), a "no" continues. *(P1 M2; the `proactive` enum value maps here)*
- **A3 — Unsupported-language rule (§4.7):** if `detected_language ∉ agent_settings.supported_languages`, generate the reply in `agent_settings.default_language`. *(P1 M2)*
- **A4 — Language stability (§4.7):** pass the conversation's established language into turn context; on short/ambiguous/low-confidence input, keep it (don't flip-flop). *(P1 M2 + C7)*
- **A5 — `answer_complete: bool` in the structured envelope (§4.2.2):** when true, emit a closing question; a thumbs-up on that message (feedback endpoint) or a detected affirmative reply fires the AI-actor `ai_handling→resolved` CAS. Idle-10m remains the fallback. *(P1 M2 + P3 M5)*
- **A6 — `welcome_message`** in `agent_settings`, rendered as the first chat-core chrome line (i18n fallback per §4.7), with a field in FE-AgentSettings. *(P3 M1 + P1 FE-Chat + P2 FE-AgentSettings)*
- **A7 — Verify comparison semantics (§4.8.2)** frozen in the schema metadata: email = casefold exact · phone = strip non-digits then exact · name = casefold exact · DOB = exact. *(P2, referenced by P1 M2 verify code)*
- **A8 — order `status` enum** `{placed, processing, shipped, delivered, cancelled}` + per-state phrasing note in the M2 order prompt; **warranty `coverage` enum** `{active, expired, void}` (`expiry` = date). *(P2 schema + P1 M2 prompt)*
- **A9 — Tracking link (§4.4):** optional per-record `tracking_url` on the order schema **and** a tenant `carrier_url_template` in `agent_settings`; M2 builds the link preferring per-record `tracking_url`, else `template.format(tracking_ref)`, else raw `tracking_ref`, else nothing. *(P2 schema + P3 M1 setting + P2 FE-AgentSettings + P1 M2)*
- **A10 — Connector must surface the verify field:** the field-map must map the verify field (not only returned fields); the connector **test fails at config time** if it can't produce it (a source that can't return the verify field can't back a verified `record_type`). *(P2 M4)*
- **A11 — Crawler controls (§4.6):** add a **same-domain** (registrable-domain) link filter (distinct from the SSRF guard) and **skip auth-gated pages** (401/403/login-redirect — don't chunk/store them). *(P2 crawler)*
- **A12 — `kb_total_bytes_limit`** per-tenant config, checked at ingest; over-quota → mark the source `failed` with an error. *(P2 M3)*
- **A13 — Citation render formats (§4.6):** add optional `page_number` (PDF parser, per chunk) and `source_url` (per crawled page) to `kb_chunk` metadata; FE renders *"from `<file>`, p.`<n>`"* for files and a clickable link for URLs, falling back to title. *(P2 M3 + P1 FE-Chat)*
- **A14 — Session lifetime enforcement:** stamp `expires_at` on the session from `session_id` lifetime; mint a fresh session when expired. *(P1 M2)*
- **A15 — After-hours email capture (§4.5.1):** in the no-agent branch, the escalation `customer_message` asks for the email, and a **narrow non-LLM capture path** writes `ticket.contact_email` even in `escalated` state (or capture just before flipping state) — reconciles with the [IMP-TKT-1] "AI stops answering" gate. Also wire the widget's optional email field. *(P3 M6 + P1 M2)*
- **A16 — Whole-turn latency backstop:** state in M2 that the worst-case turn is bounded by `max_tool_calls_per_turn` × per-step budget, and that per-step `stall_retries` also covers post-first-token stalls. *(P1 M2)*

### 14.3 POC trims (we simplify these back — the plan had over-reached for a POC)
| # | Trim | Was | POC scope | Owner |
|---|---|---|---|:--:|
| T1 | **Contextual augmentation OFF by default** (keep the toggle/seam). Base parent-child + rerank is enough to "prove the loop." | [IMP-RAG-4] on by default | default off | P2 |
| T2 | **Query rewrite + dual-fusion OFF.** Retrieve on the raw user message; keep hybrid + RRF + rerank. | [IMP-RAG-7] dual retrieval | raw-query only | P2 |
| T3 | **Grounding gate = absolute `top-1 rerank ≥ threshold` only.** Defer the top1-vs-top2 margin. | [IMP-RAG-1] +margin | absolute only | P2 |
| T4 | **Record connectors: Upload fully + at most one DB (Postgres) + one API shape.** Defer MySQL/MariaDB/SQL Server/Oracle, per-dialect statement-timeout tuning, and pub/sub engine-cache invalidation. Keep the frozen contract seam + a client-side wall-clock timeout + `(connector_id, version)` engine cache. | [P2 M4] 5-dialect matrix | Upload + Postgres + 1 API | P2 |
| T5 | **Analytics = live queries over an indexed `turn_metric`** (`percentile_cont` for p50/p95). Defer the `metric_rollup` table + Celery-beat rollups + t-digest until volume demands it. | [P2 M8] rollup machinery | live queries | P2 |
| T6 | **Support-notify = one email per escalation** (via outbox). Drop the recurring multi-round unclaimed-nudge scheduler. | [IMP-ESC-8] recurring nudge | single notify | P3 |
| T7 | **SSE reconnect = `client_msg_id` idempotent whole-turn replay.** Drop the per-event Redis replay buffer (keep the monotonic `id:` field only if trivially free). | [IMP-FE-1] event buffer | whole-turn replay | P1 |

*All four non-negotiables, the corrected contracts (C1–C7), and the additions (A1–A16) remain in scope; the trims (T1–T7) only remove machinery beyond what the POC needs to prove the end-to-end loop.*

---

*Generated from a deep multi-agent analysis of `source/END_TO_END_FLOW.pdf` + `source/IMPLEMENTATION_PLAN.pdf`, then audited against `source/AI Customer Support Agent PRD.txt`. Improvement IDs (`IMP-*`) and audit IDs (`C*`/`A*`/`T*`) are referenced from each person's implementation file.*
