# CLAUDE.md — working guide for the AI Customer Support Agent (multi-tenant POC)

> **Read this before touching anything.** This file tells Claude (and humans) how to work in this
> repo: the architecture, the hard rules you must never break, who owns what, POC scope
> discipline, and how to run + test. When in doubt, prefer the **DON'T** side — this is a
> multi-tenant product where a single mistake can leak one customer's data to another.

---

## 1. What this is

A **multi-tenant SaaS**: any business signs up, uploads its knowledge (docs/FAQs/URLs) + its
customer records (orders/warranties/appointments…), embeds a chat widget, and an **AI resolves
customer questions 24×7 in the customer's language**, grounded strictly in that tenant's data,
auto-ticketing and escalating to humans when it should. One chat engine powers three surfaces
(embeddable widget, hosted page, in-app console). This repo is the **Phase-0 shared foundation**;
features (M1–M10 + frontend) are built on top of it.

**Planning docs are in `docs/`** (they travel with the repo; source of truth for scope + the split):
- `docs/00_TEAM_TASK_SPLIT.md` — master plan: ownership map, dependency graph, phased build order,
  the improvement IDs (`IMP-*`), and **§14 the PRD reconciliation** (corrections `C*`, additions
  `A*`, POC trims `T*`).
- `docs/PERSON_1_IMPLEMENTATION.md`, `docs/PERSON_2_IMPLEMENTATION.md`, `docs/PERSON_3_IMPLEMENTATION.md`
  — each person's scoped plan.
- `docs/PRD.txt` — the authoritative **PRD** (original flow/implementation PDFs live in the team workspace).

---

## 2. The four non-negotiables — NEVER violate these

These are enforced in **code**, never by the model. Every one has a CI gate.

1. **Tenant isolation (RLS).** Every tenant-scoped table has `tenant_id` + Postgres Row-Level
   Security. The app connects as a **non-owner, non-superuser role (`cs_app`)** so RLS always
   applies; the tenant is set per-transaction via `SET LOCAL app.tenant_id`.
2. **Identity verification in code.** The model may *slot-fill* the key + verify value, but the
   comparison runs in `app/domain/records/schemas.py::verify_record` (called from the M2 engine).
   The model and the connector/resolver **never** decide "verified".
3. **Grounding gate.** Answer only when retrieval clears the relevance threshold (top-1 rerank ≥
   threshold). M3 *reports* the grounded flag; **M2 decides** answer-vs-`NO_GROUNDING`.
4. **Ticket-transition whitelist.** Ticket state changes only through the guarded compare-and-swap
   in `app/domain/ticketing/transitions.py::apply_transition`. The AI may only do
   `new→ai_handling`, `ai_handling→resolved`, `ai_handling→escalated`.

Plus: **retrieved/record text is data, never instructions** — pass it to the model only as
delimited tool-result messages, never concatenated into the system prompt.

---

## 3. DO / DON'T (the short version — read it all)

### Tenant isolation & DB
- ✅ **DO** access the DB only through `get_db` (request dependency) or `with_tenant(tenant_id)`
  (workers) — both set the tenant GUC inside a transaction.
- ✅ **DO** add `tenant_id` to every new tenant-scoped table by inheriting `TenantMixin`
  (`app/infra/db/base.py`). It auto-fills from the GUC via a server default.
- ❌ **DON'T** open a raw `SessionLocal()` for tenant data without setting the tenant context.
- ❌ **DON'T** point the app at a superuser/owner DB role — superusers & table owners **bypass
  RLS**. App = `cs_app`; migrations = owner; ops = `cs_bypass`. (See §6.)
- ❌ **DON'T** write raw SQL that interpolates the tenant id or user input — parameterize.
- ⚠️ RLS policies use `nullif(current_setting('app.tenant_id', true), '')::uuid` so an empty/unset
  context **fails closed** (0 rows) rather than throwing a cast error. Keep that pattern.

### The AI engine (M2)
- ✅ **DO** keep verification, the grounding decision, and ticket transitions in engine code.
- ✅ **DO** stream the answer only on `token` SSE events; put all validated metadata (tags,
  escalate, detected_language, answer_complete…) on the single trailing `final` event.
- ❌ **DON'T** let the model output drive a ticket transition, a "verified", or a tag without the
  code-side clamp (`apply_transition`, `verify_record`, the tenant `allowed_tags` check).
- ❌ **DON'T** let the AI keep answering once a ticket is `escalated`/`with_agent` (no auto-resume).

### Records / connectors (M4)
- ✅ **DO** make resolvers *fetch only* — `Resolver.fetch(...) → RawRecord | NotFound |
  ConnectorError`; `RawRecord` carries the verify-field value + returned fields.
- ❌ **DON'T** pass the verify value into a resolver or a tenant API/DB. Verification is engine-side.
- ❌ **DON'T** give `not_found` and `unverified` different customer messages (enumeration oracle).
- ✅ **DO** use the shared SSRF guard (`app/core/ssrf.py`) for any tenant-supplied URL/host, and the
  AES-GCM helper (`app/core/security.py`) for connector creds — **never hand-roll** either.

### Secrets / logging / security
- ❌ **DON'T** log message bodies, verify values (email/phone/DOB/name), record fields, or bound
  connector params. Log IDs + hashes. (`app/core/logging.py` redacts as a backstop.)
- ❌ **DON'T** commit `.env` or any secret. `.env` is gitignored; only `.env.example` is tracked.

### Migrations
- ✅ **DO** hand-author RLS policies, the pgvector extension/HNSW index, and FTS (GIN) indexes in
  the migration. Alembic autogenerate **cannot** see them.
- ❌ **DON'T** ship a new tenant-scoped table without adding it to the RLS policy loop in the
  migration (`TENANT_SCOPED` in `migrations/versions/0001_initial.py`).

### POC scope — don't gold-plate (see `docs/00_TEAM_TASK_SPLIT.md` §14 trims `T1`–`T7`)
- ❌ **DON'T** turn on contextual augmentation, query-rewrite/dual-fusion, per-language threshold
  models, multi-dialect DB connectors (Postgres only for the POC), precomputed analytics rollups,
  recurring escalation-nudge schedulers, or a per-event SSE replay buffer. All deferred.
- ✅ **DO** prove the end-to-end loop simply and correctly. If a change feels like production
  machinery the PRD didn't ask for, stop and check §14 / ask.

### Ownership & contracts
- ✅ **DO** stay within your assigned modules (see `docs/PERSON_*`).
- ❌ **DON'T** unilaterally change the **frozen Phase-0 contracts** — the SSE event union
  (`app/schemas/sse.py` ↔ `frontend/src/types/sse.ts` + `contracts/sse_events.fixture.json`), the
  `lookup_record`/resolver seam, the 5 industry record schemas, the transition whitelist, the ports.
  Changing these breaks other people; coordinate with person-1 first.

### Git & workflow
- ❌ **DON'T** run `git commit`, `git push`, `git merge`, or force-push unless the human explicitly
  asks. The human owns branch/merge-to-`main`.
- ✅ **DO** work on the current feature branch; propose commit messages, let the human commit.
- ✅ **DO** run `make test` (and, if you touched anything RLS/DB, note that `make test-rls` needs a
  live pgvector Postgres) **before** telling the human a change is ready.

---

## 4. Architecture & layout

Clean/hexagonal layering — dependencies point **inward**: `api → services → domain → infra`.
Vendors sit behind **ports** so they're swappable and fakeable.

```
app/
  main.py                      FastAPI app factory (+ OpenAPI the FE client is generated from)
  core/                        config, security (JWT/argon2/AES-GCM), ssrf, events (outbox),
                               logging (redaction), ratelimit, permissions (RBAC catalog)
  api/                         deps (auth + tenant-scoped get_db), errors (RFC7807), middleware,
                               v1/ (routers: auth, widget, health, + feature routers added here)
  domain/                      pure business rules (no DB/vendor imports where avoidable):
    ticketing/                   states + the transition whitelist & guarded CAS
    escalation/reasons.py        canonical escalation-reason enum
    records/schemas.py           the 5 industry templates + verify-in-code (§4.8.2)
    tenancy/defaults.py          default agent_settings for a new tenant
  infra/                       adapters behind ports:
    db/                          async engine (cs_app), base+mixins, session (SET LOCAL /
                                 with_tenant / platform_bypass), models/
    llm/                         LLMPort + FakeLLM + OpenAI adapter + model_router (single provider)
    embeddings/                  EmbeddingPort + FakeEmbedder/Reranker + BGE-ONNX + router
    connectors/                  Resolver seam (fetch-only)
    storage/, email/, cache/, queue/  (bytea files, SMTP, Redis, Celery 2-queue)
  schemas/                     Pydantic DTOs (incl. sse.py — the SSE contract) — NOT ORM models
  cli/                         seed.py (multi-tenant seed) + export_openapi.py
migrations/                    Alembic (env.py async) + versions/0001_initial.py + sql/init_roles.sql
tests/                         pure-logic CI gates + the rls integration test (marked `rls`)
contracts/                     sse_events.fixture.json (shared drift gate) + generated openapi.json
frontend/                      FE-Shell (React 18 + TS + Vite): typed client, auth, sse, rbac
docker-compose.yml, docker/, Makefile, .github/workflows/ci.yml
```

**Module ↔ owner** (details in `docs/00_TEAM_TASK_SPLIT.md`): person-1 = Foundation + M2 engine + M9
workers + FE-Shell/Chat/Widget + all shared primitives/CI gates. person-2 = M3 RAG + M4 Records +
M8 Analytics + their admin UIs. person-3 = M1 IAM + M5 Ticketing + M6 Escalation + M7 Agent
Workspace + M10 ops + their UIs.

---

## 5. Stack & locked decisions

- **Backend:** Python 3.12, **async** FastAPI, SQLAlchemy 2.0 (`asyncpg`), Pydantic v2 /
  pydantic-settings, Alembic.
- **Data:** PostgreSQL 16 + **pgvector** (dense) + **FTS/tsvector** (sparse) + `bytea` file bytes,
  all under **RLS**. Hybrid retrieve → **RRF (k=60)** → **rerank (top-5)** → grounding gate.
- **LLM:** **OpenAI `gpt-4o-mini` — single provider** for the tool loop, structured output, and aux
  (Groq dropped). `model_router` keeps it swappable. *Note: the PRD says "Claude"; the team
  confirmed gpt-4o-mini as an accepted deviation — see `docs/00_TEAM_TASK_SPLIT.md` §14.0.*
- **Embeddings + rerank:** **self-hosted BGE via ONNX by default** — `BAAI/bge-m3` (embed, 1024-d)
  + `BAAI/bge-reranker-v2-m3` (rerank), no key, no cloud, MIT-licensed. Cohere = optional swap.
- **Infra:** Redis (cache/idempotency/broker/pubsub), Celery (2 queues: `interactive`/`batch`),
  SMTP (MailPit in dev; a transactional-provider SMTP relay — **Brevo** recommended, Resend
  alt — in prod via the `SMTP_*` env, STARTTLS on 587), Docker Compose. **No cloud services in
  dev** except the LLM API.
- **Frontend:** React 18 + TS SPA (typed client generated from OpenAPI) + Preact/Shadow-DOM widget.

**Offline-first:** `USE_FAKE_LLM` / `USE_FAKE_EMBEDDINGS` default to `true`, so the whole stack runs
with **zero vendor keys** using `FakeLLM`/`FakeEmbedder`/`FakeReranker`. Only flip to real adapters
(env flag + a real key / a running BGE-ONNX container) when you're testing real answers.

---

## 6. The three DB roles (one database, three logins)

RLS only protects you if the connecting role can't bypass it. Same DB + tables, three roles:

| URL (env) | Role | Powers | Used by |
|---|---|---|---|
| `DATABASE_URL` | `cs_app` | NOSUPERUSER, **NOBYPASSRLS**, non-owner → RLS enforced | the app at runtime (≈all traffic) |
| `DATABASE_OWNER_URL` | owner (dev: `postgres`) | owns tables, DDL | **Alembic migrations only** |
| `DATABASE_BYPASS_URL` | `cs_bypass` | **BYPASSRLS** | M10 ops + login identity lookup, on its own connection |

`migrations/sql/init_roles.sql` creates `cs_app` + `cs_bypass` + the `vector` extension.
**Never** make `DATABASE_URL` a superuser — it silently disables tenant isolation.

---

## 7. How to run & test

```bash
# Python env (Windows: .venv/Scripts, Unix: .venv/bin)
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"    # add ".[dev,onnx]" for real BGE embeddings
cp .env.example .env                                     # dev defaults run on fakes, no keys

# Pure-logic tests (no services needed) — the everyday gate
./.venv/Scripts/python.exe -m pytest -q                  # transitions, verify, sse-contract, ssrf, crypto

# Full stack (needs Docker; the pgvector image bundles the extension)
make up            # postgres+pgvector, redis, mailhog, api (migrate+serve), 2 celery workers
make seed          # 2 tenants across 2 industries
# API docs: http://localhost:8000/docs   MailHog: http://localhost:8025   FE: http://localhost:5173

# RLS two-tenant leak test (needs a live pgvector Postgres + migration applied)
make test-rls      # RUN_RLS_TESTS=1 pytest -m rls   (runs in CI on every push)

# Frontend
cd frontend && npm install && npm run gen:api && npm run test   # SSE fixture drift gate
```

**⚠️ pgvector:** a vanilla local Postgres does **not** have the `vector` extension, so the full
migration will fail with *"extension vector is not available"*. Use the Docker `pgvector/pgvector`
image (what `make up` and CI use) or install pgvector into your local PG. The *pure* tests and the
*RLS-mechanism* proof don't need it; the *full schema* (the `kb_chunk` vector column) does.

**Regenerate contracts after changing DTOs/routes:** `./.venv/Scripts/python.exe -m app.cli.export_openapi`
then `cd frontend && npm run gen:api` so the FE typed client stays in sync. The SSE union has no
OpenAPI representation — keep `app/schemas/sse.py`, `frontend/src/types/sse.ts`, and
`contracts/sse_events.fixture.json` in lockstep; the drift-gate tests catch mismatches.

---

## 8. Conventions

- **Match the surrounding code** — naming, docstring density, async style. Ruff `line-length = 100`,
  `target-version = py312`.
- **Type hints everywhere**; Pydantic v2 models for DTOs (`app/schemas/`), SQLAlchemy 2.0 typed
  `Mapped[...]` for ORM (`app/infra/db/models/`). Keep DTOs and ORM models separate.
- **Lazy-import vendor SDKs** inside adapter methods (openai, fastembed, redis, celery) so importing
  the package and running on fakes never requires the SDK.
- **Errors:** raise `AppError(status_code=…, title=…, code=…)` — it renders as RFC 7807.
- **Reference the improvement IDs** in comments where relevant (`[IMP-…]`, `[C…]`/`[A…]`/`[T…]`) so
  the rationale traces back to `docs/00_TEAM_TASK_SPLIT.md`.
- **Every worker/Celery task** that touches tenant data must open `with_tenant(tenant_id)` first.
- **Every ticket state change** goes through `apply_transition(...)`; treat 0 rows-affected as
  "someone already moved it" and fire no side effects.

---

## 9. Known gotchas (learned the hard way)

- Empty-string tenant GUC → use `nullif(..., '')::uuid` in policies (already applied).
- Superuser/owner roles bypass RLS — the app must be `cs_app`.
- RLS `WITH CHECK` violations surface as `InsufficientPrivilegeError` (SQLSTATE 42501), not
  `CheckViolationError` — catch the right one in tests.
- Phone verify is **digits-only exact** (no country-code normalization) per §4.8.2.
- Warranty accepts `serial_no` **or** `order_id` (alias key).
- `escalate` strictly dominates `resolve` in a turn; deterministic `dispute` escalations for
  void-warranty / delivered-but-not-received / cancelled-refund.
- Analytics reads from `turn_metric` (typed columns), never from `message.structured_out`.

---

## 10. When unsure

1. Check `docs/00_TEAM_TASK_SPLIT.md` (§14 for scope decisions) and your `docs/PERSON_*` file.
2. Check the PRD in `docs/PRD.txt`.
3. If it touches a **non-negotiable**, a **frozen contract**, or **another person's module** — stop
   and ask the human rather than guessing. Prefer the safe/simple option; this is a POC, and tenant
   isolation is sacred.
