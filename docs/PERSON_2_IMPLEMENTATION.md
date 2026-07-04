# Person-2 — Implementation Plan (Knowledge, Records & Analytics)

> **Your mission:** own the **tenant-data vertical** — everything about *loading a tenant's data, retrieving from it, and measuring the bot*. You build the RAG pipeline (M3), the record-lookup system (M4), and the analytics (M8), plus the four admin screens that drive them. This is the *deepest* junior track: two of your three backend modules are the hardest in the app, so you'll pair closely with Person-1 on the tricky bits (RAG threshold, connector security).
>
> **Read [`00_TEAM_TASK_SPLIT.md`](./00_TEAM_TASK_SPLIT.md) first** — it has the full split, the phase plan, and the `IMP-*` improvement IDs this file points at. Ground everything in `source/END_TO_END_FLOW.pdf` + `source/IMPLEMENTATION_PLAN.pdf`.

---

## Your scope at a glance

| Layer | Module | Days | One-line purpose |
|---|---|:--:|---|
| Backend | **M3 — Knowledge / RAG** | 24 | Ingest docs/URLs → chunk → embed → hybrid retrieve → RRF → rerank → grounding gate → citations |
| Backend | **M4 — Records & Connectors** | 16 | Generic `lookup_record` over Upload/DB/API sources; 5 industry schemas; feeds the verify-in-code path |
| Backend | **M8 — Analytics** | 6 | Per-turn metrics → rollups → tenant dashboards (volume, resolution rate, cost, CSAT…) |
| Frontend | **FE-Knowledge** | ~4 | Source list + upload/URL/paste + ingestion-status polling + reingest/delete |
| Frontend | **FE-Records** | ~4 | Dataset upload + validation report + connector create/test/field-map |
| Frontend | **FE-AgentSettings** | ~4 | Persona/languages/threshold/triggers form + the pending-tag approval tray |
| Frontend | **FE-Analytics** | ~5 | Overview cards + charts + date-range filter |

**≈ 63 person-days.** Fewer days than Person-3 *on purpose* — your modules are harder per day.

---

## What Person-1 gives you (build ON these, don't rebuild)

You never hand-roll infrastructure or a security control. These arrive frozen in **Phase 0**; until they land, code against the fakes/stubs.

- **RLS base + tenant context** — a DB-session dependency that has already `SET LOCAL app.tenant_id`. Your repositories just query; the tenant filter is automatic. For **workers** you get a `with_tenant(tenant_id)` context manager — *you must use it in every Celery task* or RLS won't be set (see Watch-outs).
- **Ports + in-memory fakes** — `EmbeddingPort` (embed + rerank + `dimension`), a `vector` retriever primitive over pgvector, `StoragePort`, `ConnectorResolver` base, and the `LLMPort` (contextual augmentation runs on **gpt-4o-mini** — single provider; Groq is dropped). The real embed/rerank is **self-hosted BGE via ONNX** (see the M3 gotcha below). Dev/CI default to `FakeEmbedder` (hash→stable vector) + `FakeReranker` so you run with **no vendor keys**.
- **SSRF resolve-and-validate guard** (`infra/connectors/base` / a shared util) — call it from your api/db resolvers and the crawler. **Do not write your own** (`IMP-SEC-5`).
- **AES-GCM crypto helper** (`core/security`) — call it to encrypt connector creds. **Do not touch `cryptography` directly** (`IMP-SEC-8`).
- **Rate-limit dependency** (Redis-backed) — you use it for the durable verify-attempt counter (`IMP-SEC-6`).
- **Grounding-gate definition** — Person-1 owns *what the gate means* (top-1 rerank ≥ threshold); you implement the retrieval that feeds it and *report* the grounded flag. M3 reports, M2 decides.
- **`turn_metric` DTO + outbox primitive** — the canonical per-turn metric shape (written by the M2 engine) and the write-outbox-in-a-transaction helper. Your M8 reads `turn_metric`; you don't invent the metric shape.
- **OpenAPI/DTO conventions + FE-Shell** — your four screens mount into Person-1's SPA shell and call the generated typed client.
- **Multi-tenant seed** — ≥2 tenants across ≥2 industries with *deliberately colliding record keys* (e.g. both tenants have `order_id=1001`) so you can prove RLS + verify isolation.

### What you give others (freeze in Phase 0)
- **`kb_retrieve` contract** (co-authored w/ P1): `kb_retrieve(query, tenant, N, top_k, threshold) → GroundedResult{parent-expanded chunks, citations} | NO_GROUNDING | KB_NOT_READY`. Consumed by M2's tool loop. `IMP-RAG-1`, `IMP-RAG-5`.
- **`lookup_record` verify seam** (co-authored w/ P1): `Resolver.fetch(tenant, record_type, key) → RawRecord | NotFound | ConnectorError` — **fetch only, no verdict**; `RawRecord` carries the **verify-field value + the returned fields**. Verify + status assembly lives in the M2 engine; a `ConnectorError` (timeout/auth/connection) maps to the tool-failure fallback→escalate. `IMP-DEL-3`, `C3`.
- **5 industry record schemas + verify metadata** — the single registry (`domain/records/`); M1's template downloads and M2's verify both import from it. Freeze early (M1/Person-3 is blocked until then): field names, key, verify field, and **the verify match rule per §4.8.2 — email = casefold exact, phone = strip-non-digits then exact, name = casefold exact, DOB = exact `[A7]`**, attempts cap (**healthcare = 1**). **Retail `[C1]`: record_types = `order, warranty`; warranty key = `serial_no` with `order_id` as an alias key `[C2]`; order `status ∈ {placed,processing,shipped,delivered,cancelled}`, warranty `coverage ∈ {active,expired,void}`, `expiry` = date `[A8]`; order carries an optional `tracking_url` `[A9]`.**
- **`turn_metric` consumer + analytics query surface** — you own the analytics queries. **[T5] POC:** serve dashboards with **live queries over an indexed `turn_metric`** (`percentile_cont` for p50/p95); the `metric_rollup` table + scheduled rollups are **deferred** until volume demands them.

---

## Backend modules

### M3 — Knowledge / RAG  *(complexity 5, ~24 d — your biggest module)*

**Purpose:** ingest a tenant's knowledge (files/paste/URL), and answer the engine's `kb_retrieve` calls with grounded chunks + citations — or a clean "no grounding" signal. You own the *retrieval half* of the grounding-gate non-negotiable.

**Folder / files** (from the plan):
```
services/knowledge_service.py          # orchestration
infra/parsers/                         # PDF/DOCX/TXT/MD  (leaf — P1 may seed)
infra/crawler/                         # URL crawl  (uses P1's SSRF guard)
infra/embeddings/                      # BGE-M3 + bge-reranker-v2-m3 via ONNX (default); Cohere optional — all behind EmbeddingPort (P1 owns the port)
infra/vector/retriever.py              # pgvector query primitive  (P1 owns primitive, you compose)
workers/{ingestion,crawl,embedding}_tasks.py   # thin wrappers → your service (M9/P1 owns Celery app)
domain/knowledge/                      # Kb parent/child, source FSM
api/v1/knowledge.py
```

**Responsibilities:** file/paste/URL ingestion (async, status FSM `queued→ingesting→ready|failed`); structure-aware parent-child chunking (~300–500-tok children, ~15% overlap, ~2k-tok parents) + contextual augmentation *(optional, **off by default** for the POC — `[T1]`)*; multilingual embedding; store dense (pgvector) + sparse (tsvector); **hybrid retrieve → RRF → rerank top-k → threshold gate → parent expansion + citations**; re-ingest/delete.

**APIs:** `POST/GET /knowledge/sources`, `POST /knowledge/sources/{id}/reingest`, `DELETE /knowledge/sources/{id}`. **Add `GET /knowledge/sources/{id}`** (or a `status`+`updated_at` field on the list) for FE polling — `IMP-FE-8`.

**Contracts you provide:** `kb_retrieve(...)` (above) + the citation schema (source id/title + **exact child span** locator). **You consume:** `EmbeddingPort`, the `vector` primitive, `StoragePort`, the crawler + SSRF guard, and the Celery queue wiring.

**Improvements to implement (do these):**
- `IMP-RAG-1` **[T3]** — the gate is the **absolute `top-1 rerank score ≥ threshold`** *and* the answer must cite ≥1 chunk. The top1-vs-top2 margin is **deferred post-POC** (one thing to calibrate, not two). You *report* `grounded`; M2 decides.
- `IMP-RAG-2` — add a `language` column to `kb_chunk`; build the tsvector with `to_tsvector(<regconfig>, text)` defaulting to **`'simple'`** (never `'english'`) for unknown/CJK/mixed text.
- `IMP-RAG-3` — keep **tables** as atomic chunks (repeat the header row into any split); keep numbered lists/procedures intact.
- `IMP-RAG-4` **[T1 — POC: OFF by default]** — base parent-child + rerank is enough to prove the loop, so keep contextual augmentation **off** (but keep the toggle/seam). When a tenant enables it: runs on **gpt-4o-mini**, **temperature 0 + versioned prompt**, cached once **per parent** (not per child); record ingest token cost.
- `IMP-RAG-5` — if the tenant has **zero `ready` sources**, return `KB_NOT_READY` (not `NO_GROUNDING`) so the engine says "still learning your docs" instead of "I don't know → escalate".
- `IMP-RAG-6` / `[A13]` — citations resolve to the exact child span within the 2k parent; store optional `page_number` (set by the PDF parser, per chunk) + `source_url` (the specific crawled page) on `kb_chunk` so FE renders "from `<file>`, p.`<n>`" for files and a clickable link for URL sources (fallback to title).
- `IMP-RAG-7` **[T2 — POC: OFF]** — for the POC retrieve on the **raw user message only** (keep hybrid + RRF + rerank). The dual-query rewrite+fusion (retrieve on both the rewritten *and* raw query, fuse via RRF before rerank) is **deferred post-POC**.
- `[A12]` — enforce a per-tenant **`kb_total_bytes_limit`** (config, default in `core/config`) at ingest; over-quota → mark the source `failed` with an error (never a half-ready silent state).
- `IMP-RAG-8` — **delete-last** reingest: build the new version's chunks+vectors, atomically flip a serving pointer, delete old vectors last. A failed reingest leaves the old version live.
- `IMP-DAT-1` — use the **HNSW** index Person-1 defines (`m=16, ef_construction=200`), set `hnsw.ef_search=100`, and rely on **pgvector 0.8 iterative scans** so the RLS filter doesn't return < k neighbours.
- `IMP-SEC-2` — store file bytes in a tenant-scoped **`bytea`** column, not a Large Object (Large Objects aren't covered by RLS).
- `IMP-SEC-5` / `[A11]` — the crawler calls Person-1's **SSRF guard** before every fetch, disables auto-redirects (or re-validates each hop), and enforces max pages/depth/bytes + per-fetch timeout + robots; **plus a same-domain (registrable-domain) link filter** (distinct from SSRF — never follow off-site links) and **skip auth-gated pages** (401/403/login-redirect — don't chunk/store them).
- `IMP-WRK-2`/`IMP-WRK-4` — embedding tasks are **idempotent** (upsert `kb_chunk` by `(source_id, content_hash)`, skip already-embedded) and **resumable per batch** with checkpointing; embed calls run **outside** any DB transaction; flip `source→ready` only after all batches commit.

**Gotchas & where you'll get stuck (read this — it's the heart of your work):**
- **RRF is simpler than it sounds.** You run two searches — dense (pgvector cosine) and sparse (Postgres full-text/BM25). Each returns a *ranked list*. Reciprocal Rank Fusion just adds `1/(k + rank)` for each doc across both lists (**`k=60`**), then sorts by that sum. You fuse on *rank order*, not raw scores — that's the whole point (dense distances and BM25 scores aren't comparable, but ranks are). Fetch ~30–50 from each arm, dedup by chunk id, then rerank the fused top-`N=40` down to **top-5**.
- **The grounding threshold is not a magic number — you *calibrate* it** (`IMP-DEL-5`, with Person-1). The reranker gives a relevance score per (query, chunk). You can't guess a cutoff. Instead: hand-label ~20–30 `(query, should_answer?)` pairs per seeded tenant (include off-topic questions and one non-English), run them through the **real** hybrid+RRF+rerank path, dump the top-1 rerank scores, and eyeball a cutoff that answers the good ones and refuses the off-topic ones. Store it as the tenant default. **Re-calibrate whenever the reranker changes** — BGE, Cohere, and even a quantized-vs-fp ONNX build output scores on different scales.
- **RLS + ANN interact in a nasty way.** pgvector's HNSW index finds nearest neighbours *first*, then the RLS `tenant_id` filter drops the ones from other tenants — so you can silently get **fewer than `k`** results for a tenant. The fix is pgvector 0.8's *iterative scans* (Person-1 enables this) which keep scanning until enough tenant rows are found. If retrieval feels "empty" for a tenant with data, this is the first thing to check.
- **"Transactional reingest" is a trap.** Embedding calls the embedding service (self-hosted BGE via ONNX, or Cohere) and takes real time across many chunks — you **cannot** hold a DB transaction open across it. That's why it's *delete-last* (`IMP-RAG-8`): only the final pointer-swap is transactional.
- **Contextual augmentation can blow your token budget — so it's OFF by default for the POC (`[T1]`).** When enabled it's a gpt-4o-mini call per chunk at ingest time; cache per parent, temp 0, per-tenant toggle — or a big upload silently costs a fortune and isn't reproducible on reingest.
- **Self-hosted embeddings + rerank (your default — $0 / no-cloud / commercial-safe).** Embed with **BGE-M3** (1024-dim — matches the `vector(1024)` schema exactly) and rerank with **bge-reranker-v2-m3**, both run via **ONNX Runtime** (INT8-quantized) and served from one small container (**fastembed** / HF **TEI** / **Infinity**) behind Person-1's `EmbeddingPort`. Both are **MIT-licensed**. **Latency (your instinct was right):** the two run at different stages — ingest embedding is **background** (nobody's waiting, so quantize hard), while **rerank is the only heavy model in the query hot path** (~sub-250 ms quantized on CPU). If rerank is slow, rerank **top-20 instead of 40** or add a GPU. Cohere stays an optional managed swap behind the same port — if you switch, **re-calibrate the threshold** (different score scale).

---

### M4 — Records & Connectors  *(complexity 4, ~16 d)*

**Purpose:** one generic `lookup_record` that works across Upload (CSV/JSON), DB, and API sources, all behind the same contract, feeding the identity-verify-in-code path. **Build order: Upload first** (no network surface), then DB, then API — each drops in with no redesign.

**Folder / files:**
```
services/record_service.py
infra/connectors/{base,upload_resolver,api_resolver,db_resolver}.py   # base = P1's; you build the three resolvers
domain/records/                       # THE 5 industry schemas + verify rules (your registry — others import it)
api/v1/records.py
```

**Responsibilities:** the 5 industry schemas; the `lookup_record` result set (`ok|not_found|unverified|invalid_type|rate_limited`); resolver dispatch + field mapping to schema; upload rules (CSV/JSON, exact headers, unique key, **full replacement**, 50k cap); connector security (encrypted creds, SSRF guard, **read-only + parameterized** DB queries); connector test; 5s timeout + 1 retry.

**APIs:** `POST/GET/DELETE /records/datasets`, `POST /records/connectors`, `POST /records/connectors/{id}/test`. **Add `GET /records/schema`** (resolved `record_type → {fields, key, verify}`) so the FE field-map/validation UI can render — `IMP-FE-8`.

**Contracts you provide/consume:** you provide the 5 schemas + `Resolver.fetch(tenant, record_type, key) → RawRecord | NotFound | ConnectorError` where `RawRecord` = **verify-field value + returned fields** (`C3`). **The verify comparison itself lives in the M2 engine, not here** (`IMP-DEL-3`). You consume Person-1's resolver base, SSRF guard, AES-GCM helper, and rate-limit dep.

**Improvements to implement:**
- `IMP-DEL-3` / `C3` — **fetch only, no verdict.** `Resolver.fetch` returns the raw row (**the verify-field value + the returned fields**), `NotFound`, or `ConnectorError` (timeout/auth/connection). It never receives the verify value from the customer and never decides "verified". The M2 `lookup_record` tool does: fetch → compare verify field in code → assemble `{status, record}`; a `ConnectorError` maps to the tool-failure fallback→escalate. (The original doc ordered "verify before dispatch" — impossible; you can't compare a field before fetching the row.)
- `[A10]` — **the connector field-map must map the verify field** (not only the returned fields), and the connector **test fails at config time** if it can't produce it — a source that can't surface the verify field cannot back a verified `record_type` (all five POC templates are verified). `GET /records/schema` already exposes the verify field for the field-map UI.
- `IMP-SEC-5` — api/db resolvers call Person-1's **SSRF guard**; DB connections are **read-only creds + parameterized query template** (`... WHERE order_id = :key`), never string-built SQL.
- `IMP-SEC-6` — the verify-attempt counter is **durable in Redis keyed on `(tenant_id, record_type, key)`** with a TTL lockout — **never** on `session_id`. This backs `rate_limited`. (You provide the counter increment on failed verify; the engine calls it.)
- `IMP-SEC-8` — encrypt connector creds with Person-1's **`AESGCM` helper**, binding ciphertext to `(tenant_id, connector_id)` via AAD. Don't touch crypto primitives yourself.
- `IMP-DAT-4` — full-replacement dataset upload = **DELETE + bulk-INSERT in one transaction** (MVCC keeps live lookups reading old rows until commit). After swap, an orphaned `linked_record` pointer just returns `not_found` gracefully.
- `IMP-TKT-5` — when a verified lookup *grounds an answer*, write its `{type, key}` into `message.structured_out` (per-turn), so the agent workspace shows the right record even across multiple lookups. (You provide it in the result; M2 persists it.)
- **[T4 — POC scope]** Ship **Upload fully + one DB (Postgres) + one API shape**. **Defer** MySQL/MariaDB/SQL Server/Oracle, per-dialect statement-timeout tuning, and the Redis pub/sub engine-cache invalidation — the SQLAlchemy abstraction keeps them a post-POC drop-in. Keep the frozen contract seam + a **hard client-side wall-clock timeout** (5s + 1 retry) + a `(connector_id, version)`-keyed SQLAlchemy Engine cache disposed on update/delete.

**Gotchas & where you'll get stuck:**
- **The verify boundary is the #1 thing to get right.** Say it out loud: *resolvers fetch, the engine verifies.* If a resolver ever sees the customer's email/DOB, the design is wrong. This keeps the identity-verification non-negotiable in exactly one place (`IMP-DEL-3`).
- **`not_found` and `unverified` return the *same* customer message.** This is deliberate — if "wrong order id" and "right order id, wrong email" gave different messages, an attacker could enumerate which order ids exist. The *status* differs internally (for the attempt counter), but the customer text is identical.
- **SSRF is subtle** — a tenant's "API connector URL" could point at `http://169.254.169.254` (cloud metadata) or `http://localhost:5432` (your own Postgres). That's why you *must* use Person-1's resolve-and-validate guard, which checks the *resolved IP*, not the hostname string, and blocks redirects. Don't write your own check.
- **Multi-worker Engine cache.** You run several FastAPI worker processes; a per-process Engine cache means a connector edit in one process won't invalidate another's. Key the cache on `(connector_id, version)` and **bump `version` on edit** (the Redis pub/sub "connector-invalidated" broadcast is **deferred post-POC** per `[T4]`).

---

### M8 — Analytics  *(complexity 3, ~6 d)*

**Purpose:** per-turn metrics → scheduled rollups → tenant-scoped, date-filterable dashboards.

**Folder / files:** `services/analytics_service.py`, `domain/` metrics, the rollup task function (registered by Person-1's M9 Celery beat), `api/v1/analytics.py`.

**Responsibilities:** provide the `record_turn_metric(dto)` write helper (called by the M2 engine); scheduled rollups; dashboards — volume, autonomous-resolution rate, escalation-reason breakdown, top tags/intents, language distribution, latency p50/p95, token cost/conversation, thumbs CSAT.

**APIs:** `GET /analytics/{overview,tags,latency,cost}` (tenant-scoped, date-filterable).

**Improvements to implement:**
- `IMP-DAT-5` **[T5 — POC: live queries]** — **`turn_metric` is the single source of truth**; add `detected_language` as a typed column and never read `message.structured_out` in a query. **Serve dashboards with live queries over an indexed `turn_metric`** (`percentile_cont` for p50/p95). **Defer** the `metric_rollup` table + scheduled Celery-beat rollups + t-digest until data volume actually demands them.
- `[C6]` — group the escalation-reason breakdown by the **canonical enum** `no_grounding | explicit | sensitive | dispute | n_fails | proactive | timeout` (single source, owned in P3 `domain/escalation`; M2 records it, you group by it).
- **Percentiles are NOT additive** across days — with the live-query approach you compute them directly with `percentile_cont` over the filtered window (this is exactly why the POC skips daily rollups).
- `turn_metric` carries a **per-model** token+cost breakdown (gpt-4o-mini today; keep it a list so an aux model can be added later); centralize a pricing map in `core/config`.
- Define "autonomous-resolution rate" explicitly: resolved tickets that never entered `escalated`/`with_agent` ÷ total resolved, over the window.
- Your rollup runs in a **Celery worker** (no HTTP request) → it must loop over tenant_ids and apply Person-1's **`with_tenant()`** per tenant. Never a single cross-tenant scan.

**Gotchas:** the biggest one is the percentile trap above. The second: don't let `/ops/usage` (Person-3's M10) re-implement your cost math — it should call *your* analytics query surface, not its own aggregation.

---

## Frontend modules

All four mount into Person-1's **FE-Shell** (router, providers, design system, typed API client, RBAC gating). You call the generated typed client — no hand-written types.

### FE-Knowledge (`features/knowledge/`)
- Source list + **ingestion-status polling** + upload (PDF/DOCX/TXT/MD, URL crawl, pasted text) + reingest/delete.
- **Polling contract (`IMP-FE-8`):** poll `GET /knowledge/sources/{id}` (or the list with a `status` field) every ~2–3s **only while any source is `queued|ingesting`**; stop when all are `ready|failed`. Don't poll forever.

### FE-Records (`features/records/`)
- Dataset upload + validation report + connector create/test/field-map.
- **Backend is the single source of validation truth** — the FE does only cheap pre-checks (extension, size ≤25MB, headers present) then renders M4's structured `{row errors, missing headers, duplicate keys}` report verbatim.
- The field-map UI drives off `GET /records/schema` (`IMP-FE-8`), not the CSV-download endpoint.
- **Dataset validation is synchronous** (structural check on upload), unlike KB ingestion which is a long async FSM — don't conflate the two feedback models.

### FE-AgentSettings (`features/agent-settings/`)
- Persona/tone, **welcome message `[A6]`**, languages + default, active triggers, **relevance threshold**, sensitive-intent list, N, SLA text, idle timers, allowed tag list, **optional carrier tracking-URL template `[A9]`** (`https://carrier/track/{tracking_ref}`), autonomy on/off — **plus the pending-tag approval tray**. (Fields stored in `agent_settings` by P3/M1; this screen just edits them.)
- **Guard the relevance threshold control** (`IMP-RAG-1`): it's a code-enforced non-negotiable input, not a free number field. Show the eval-derived default with a recommended band; warn on deviation; or offer a coarse *strict/balanced/lenient* dial.
- The screen talks to **two backends with different write semantics**: bulk `GET/PATCH /admin/settings` (M1) for the config form vs per-item `POST /admin/tags/{id}/approve|reject` (M5) for the tray. Keep the **tag tray separate** with its own optimistic per-row actions — it must never ride on the settings-form save.
- **Extract a shared `<UploadDropzone>` + `<ValidationReport>` component** into the design system — FE-Onboarding (Person-3), FE-Knowledge, and FE-Records all reuse it. Agree with Person-3 who houses it (design system) so it's built once.

### FE-Analytics (`features/analytics/`)
- Overview cards + charts (volume, resolution rate, escalation reasons, top tags, language distribution, latency p50/p95, cost/conversation, CSAT) + date-range filter.
- **8 charts vs 4 endpoints:** build an endpoint→chart matrix first (confirm `overview` returns the composite volume/resolution/language/CSAT series; `tags`/`latency`/`cost` are drill-downs). **Pin a locally-bundled chart lib (Recharts or visx)** — no CDN (`no-cloud` constraint).

---

## Your phase-by-phase tasks

**Phase 0 — Foundations & Contracts**
- Co-author with Person-1: the `kb_retrieve` contract, the `lookup_record`/verify seam, and **freeze the 5 industry record schemas** (Person-3's M1 template downloads are blocked until these are frozen).
- Scaffold M3/M4 resolvers against the fakes; scaffold FE-Knowledge/FE-Records against the mock client.
- *Checkpoint:* the schemas are committed; the fakes let your scaffolds run.

**Phase 1 — Walking skeleton**
- Minimal M3 ingest: upload → parse → chunk → embed via **`FakeEmbedder`** over ~3 seeded docs; hybrid retrieve → RRF → rerank → gate returning `GroundedResult | NO_GROUNDING`.
- **Provisional threshold calibration** paired with Person-1.
- FE-Knowledge: source list + upload.
- *Checkpoint (team):* an admin asks a question in the console and gets a grounded, cited, streamed answer (or a clean "I don't know").

**Phase 2 — Feature build-out**
- **M4 full:** 5 schemas (incl. warranty `serial_no`+`order_id` alias key), upload validation + 50k cap, **Upload fully + one DB (Postgres) + one API** connector behind the SSRF guard + AES-GCM (other dialects post-POC, `[T4]`), connector test (incl. verify-field check `[A10]`), **durable verify-attempt Redis counter**.
- **M3 depth:** reingest/delete (delete-last), structure-aware chunking for tables/lists, `kb_total_bytes_limit` + crawler same-domain/auth-skip; stand up the self-hosted **BGE-M3 + bge-reranker-v2-m3 (ONNX)** serving container and wire the real `EmbeddingPort` adapter. (Contextual augmentation stays **off** for the POC, `[T1]`.)
- FE-Records + FE-Knowledge + FE-AgentSettings.
- *Checkpoint (team):* onboarding works end-to-end; a record lookup with identity verification returns `ok`/`unverified`/`not_found` **neutrally**.

**Phase 3 — Escalation support**
- M4 **live-record re-fetch read path** for the agent workspace — an *internal, already-verified staff read* keyed by `ticket.linked_record_{type,key}`, distinct from the customer verify flow, with a "live data unavailable — retry" failure state.
- Finalize the `turn_metric` write helper with Person-1.
- Provide the **grounding-gated** "suggested reply" input for the escalation summary (`IMP-ESC-6`).

**Phase 4 — Analytics & hardening**
- **M8 full:** **live queries** over `turn_metric` typed columns + `ticket_tag` (`percentile_cont` for p50/p95); `overview`/`tags`/`latency`/`cost` endpoints. (`metric_rollup` + scheduled rollups deferred, `[T5]`.)
- FE-Analytics dashboards.
- Build the **retrieval eval set** incl. one CJK + one RTL case; write the **embedding-model pin note** — record `embedder_id` + `dimension` on each source (default **BGE-M3 / 1024-d**); a model/dim change is a **full re-ingest**, never an in-place swap.
- *Checkpoint (team):* dashboards render real per-turn metrics; all four non-negotiable CI suites green.

---

## Definition of done for your slice
- A tenant can upload docs + a records CSV, and the bot answers **grounded** questions with clickable citations and looks up records with **in-code identity verification**.
- `kb_retrieve` returns `GroundedResult | NO_GROUNDING | KB_NOT_READY` correctly; the threshold is calibrated, not guessed.
- DB + API connectors work through the SSRF guard with encrypted creds; the connector test surfaces auth/mapping errors at config time.
- Analytics dashboards show real metrics from `turn_metric`; the rollup runs per-tenant in a worker.
- Your part of the **grounding-gate** and **identity-verify** CI suites is green.

## How to test offline
- **No vendor keys needed.** `FakeEmbedder` maps text → a stable hash-derived vector (so the same text always embeds the same); `FakeReranker` gives deterministic scores. Wire them via the env flag Person-1 provides.
- **Prove verify isolation with the colliding-key seed:** tenant A and tenant B both have `order_id=1001` with *different* verify emails. Look up `1001` as tenant A with tenant B's email → must return `unverified` (and the *same* message as `not_found`). Look up as the wrong tenant → RLS returns nothing.
- **Prove the attempt counter is durable:** fail verify 3× in one session, start a *new* session, fail again → still locked out (counter is keyed on `(tenant, record_type, key)`, not session).
- Use MailHog + seed data brought up by `docker-compose up`.

---

## Watch-outs (read before you start)
1. **Verify runs in the ENGINE (M2), not your resolver.** Resolvers `fetch` and return raw rows or `NotFound`. Never pass the verify value into a resolver. (`IMP-DEL-3`)
2. **`not_found` and `unverified` show the customer the *same* message.** Different messages = an enumeration oracle.
3. **Never scope the verify-attempt counter to `session_id`.** Sessions are free and anonymous; scope it to `(tenant, record_type, key)` in Redis. (`IMP-SEC-6`)
4. **Reingest is delete-*last*, never delete-first.** Deleting first creates a window where live retrieval falsely returns `NO_GROUNDING`. (`IMP-RAG-8`)
5. **Use `'simple'`, not `'english'`, for the tsvector** on unknown/CJK/mixed text — wrong-language stemming quietly wrecks the sparse arm. (`IMP-RAG-2`)
6. **Don't hand-roll SSRF checks or crypto.** Call Person-1's guard and `AESGCM` helper. (`IMP-SEC-5`, `IMP-SEC-8`)
7. **Percentiles aren't additive** — for the POC compute p50/p95 **live** with `percentile_cont` over the filtered window; the `metric_rollup` table is deferred. (`IMP-DAT-5`, `[T5]`)
8. **File bytes go in a `bytea` column**, not a Postgres Large Object (LOs escape RLS). (`IMP-SEC-2`)
9. **Calibrate the threshold, don't guess it** — and re-calibrate when the reranker changes. (`IMP-DEL-5`)
10. **Every Celery task must open `with_tenant()`** or RLS isn't set and your query either sees nothing or (worse) leaks. Workers have no request scope.
