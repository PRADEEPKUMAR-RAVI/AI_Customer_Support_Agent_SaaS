# AI Customer Support Agent — Phase 0 (Foundation)

The shared spine of a multi-tenant AI customer-support SaaS. This is **Phase 0**: the
foundation every feature module builds on, plus the frozen contracts and the CI-gated
non-negotiables. Person-2 and Person-3 branch off `main` from here and build their verticals
in parallel. See [`../00_TEAM_TASK_SPLIT.md`](../00_TEAM_TASK_SPLIT.md) and the per-person
plans (`../PERSON_1/2/3_IMPLEMENTATION.md`).

## Architecture (one paragraph)

Python 3.12 + **FastAPI** (async, hexagonal) over **PostgreSQL 16** (relational + `pgvector` +
FTS + file bytes, isolated by **Row-Level Security**), with **Redis** (cache/idempotency/
Celery broker/pub-sub) and **Celery** workers (two queues: `interactive` + `batch`). One LLM
provider (**gpt-4o-mini**) behind a swap seam; embeddings + rerank default to **self-hosted
BGE via ONNX** (no vendor key). Email goes through a transactional **outbox → worker → SMTP**
(MailHog in dev). The whole stack runs offline on **fakes** — no cloud keys needed for dev/CI.

## Quickstart

```bash
cp .env.example .env
make up            # build + start postgres(pgvector) + redis + mailhog + api + 2 workers
                   #   (the api container runs the DB migration on boot)
make seed          # 2 tenants across 2 industries (admin logins + widget keys printed)
```

Then open:
- API docs (OpenAPI): http://localhost:8000/docs
- Captured email (MailHog): http://localhost:8025
- Frontend (FE-Shell), once running (`make fe-install && make fe-dev`): http://localhost:5173

Seeded admin logins use password `password123` (e.g. `admin@acme-retail.com`, `admin@wellness-clinic.com`).
`make seed` is idempotent — re-running it skips tenants already present. For a clean slate, `make reset`.

## Running without Docker (host / .venv)

```bash
python -m venv .venv && ./.venv/Scripts/python -m pip install -e ".[dev]"   # (Unix: .venv/bin)
make migrate       # needs a reachable Postgres with the cs_* roles + pgvector
make seed
./.venv/Scripts/python -m uvicorn app.main:app --reload
```

## Tests

```bash
make test          # pure/unit + contract gates (no services): transitions, verify,
                   #   sse-contract, ssrf, crypto  — run anywhere
make test-rls      # the two-tenant RLS leak test — needs a live Postgres (make up first)
make lint
```

CI (`.github/workflows/ci.yml`) runs three jobs: **unit** (contract gates), **rls** (the
two-tenant leak test against a real pgvector Postgres), and **frontend** (the SSE-fixture
drift gate + typed-client generation).

## The four non-negotiables (enforced in code) and where they live

| Non-negotiable | Enforcement point | Gate |
|---|---|---|
| **Tenant isolation (RLS)** | `SET LOCAL app.tenant_id` in `app/infra/db/session.py`; `FORCE RLS` + policies in `migrations/versions/0001_initial.py`; app runs as non-owner `cs_app` | `tests/test_rls_isolation.py` |
| **Ticket-transition whitelist** | `app/domain/ticketing/transitions.py` (guarded CAS + AI whitelist) | `tests/test_transitions.py` |
| **Identity verification (in code)** | `app/domain/records/schemas.py::verify_record` (§4.8.2 rules) | `tests/test_verify.py` |
| **Grounding gate** | reported by M3 retrieval, decided in M2 (Phase 1); threshold config in `TenantDefaults` | (Phase 1) |

Plus the shared security primitives: SSRF guard (`core/ssrf.py`), AES-GCM connector creds
(`core/security.py`), log redaction (`core/logging.py`), rate limiting (`core/ratelimit.py`),
and the transactional outbox (`core/events.py`).

## What Phase 0 delivers

- Config + reference defaults (`app/core/config.py`), RFC7807 errors, request-id middleware.
- **RLS harness**: async engine + `SET LOCAL` session dep + worker `with_tenant()` + audited
  `platform_bypass()`; `FORCE RLS` policies + pgvector HNSW + FTS indexes in the migration.
- **Auth**: signup/verify/login/refresh/logout; JWT access + `SameSite=Strict` refresh cookie;
  static RBAC catalog (admin/agent + platform).
- **Contracts** (frozen for the juniors): the typed **SSE event union** (`app/schemas/sse.py`
  + `contracts/sse_events.fixture.json`), the `lookup_record` resolver seam
  (`app/infra/connectors/base.py`), the **5 industry record schemas** + verify rules
  (`app/domain/records/schemas.py`), the ticket transition primitive, the outbox + turn-metric
  shapes, and the OpenAPI export (`app/cli/export_openapi.py` → `contracts/openapi.json`).
- **Ports + fakes**: `LLMPort`/`EmbeddingPort`/`StoragePort` with `FakeLLM`/`FakeEmbedder`/
  `FakeReranker` (dev/CI default) and real OpenAI + BGE-ONNX adapters behind an env flag.
- **Seed CLI**, `docker-compose` (full stack), and CI (3 jobs incl. the RLS gate).

## What comes next (Phase 1 — the walking skeleton)

One in-app-console chat turn end-to-end: M2 tool loop + M3 hybrid retrieve/RRF/rerank/gate +
SSE streaming + M1 auth + M5 ticket create/transition + one `turn_metric` — proving the
M1+M2+M3+M5+SSE+RLS seam before feature build-out. Person-2 owns M3/M4/M8; Person-3 owns
M1/M5/M6/M7/M10; Person-1 owns the engine + workers + chat surfaces.
