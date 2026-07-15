"""Centralised configuration.

Two layers:
  * ``Settings`` — platform/env-driven config (DB, Redis, SMTP, secrets, provider flags),
    loaded from the environment / ``.env`` via pydantic-settings.
  * ``TenantDefaults`` — the reference defaults from the build sheet (§11). These are the
    seed values for a tenant's ``agent_settings`` row; a tenant may override them, but the
    platform ships these as the starting point. Kept as plain constants so every module
    reads one source of truth.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["dev", "ci", "prod"] = "dev"
    log_level: str = "INFO"

    # Postgres — three roles (see .env.example). The app NEVER connects as owner/superuser.
    database_url: str = "postgresql+asyncpg://postgres:password%401234@localhost:5432/cs_agent"
    database_owner_url: str = (
        "postgresql+asyncpg://postgres:password%401234@localhost:5432/cs_agent"
    )
    database_bypass_url: str = (
        "postgresql+asyncpg://postgres:password%401234@localhost:5432/cs_agent"
    )

    redis_url: str = "redis://localhost:6379/0"

    # Email is sent over SMTP (M9 outbox drain). Dev default = MailPit on localhost:1025 (no auth,
    # no TLS — captures mail, sends nothing externally). To relay through a real transactional
    # provider, set user/password + starttls: the SAME code path authenticates over STARTTLS on
    # port 587. Recommended = Brevo (smtp-relay.brevo.com, 300/day free, single-sender verify, no
    # domain/DNS needed); Resend (smtp.resend.com, user="resend", password=API key) is identical
    # but requires a verified sending domain. See .env.example.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "no-reply@cs-agent.local"
    smtp_user: str = ""          # empty → no SMTP AUTH (the MailPit dev path)
    smtp_password: str = ""
    smtp_starttls: bool = False  # True for a provider relay on port 587; False for dev MailPit

    jwt_secret: str = "dev-insecure-change-me-32-bytes-minimum-secret"
    jwt_algorithm: str = "HS256"
    credential_master_key_b64: str = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="  # 32 bytes (dev)

    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 1_209_600

    # Provider selection — fakes are the dev/CI default so nothing needs a vendor key.
    use_fake_llm: bool = True
    use_fake_embeddings: bool = True
    llm_provider: Literal["openai"] = "openai"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    embeddings_provider: Literal["bge_onnx", "cohere"] = "bge_onnx"
    # Self-hosted multilingual pair via fastembed/ONNX (no key). Default embedder is the LIGHT
    # multilingual model (~0.22GB, 384-dim) so it loads/runs fast on a dev CPU — the 2GB e5-large
    # took minutes to cold-load. The reranker is jina-reranker-v2-multilingual: bge-reranker-base
    # is NOT reliably multilingual (empirically it scores relevant Spanish queries ~0, failing the
    # grounding gate), whereas jina-v2 grounds consistently across EN/ES/FR/DE/HI. The grounding
    # gate depends on the reranker's scores, which BgeOnnxClient sigmoid-normalises to [0,1] so one
    # threshold works for fake + real. The reranker is warmed at API startup so its load never
    # lands on a customer turn. embed_dim MUST match the embed model's output dim — it drives the
    # kb_chunk.embedding pgvector column, so changing the model means changing dim + reseeding.
    # LICENSE NOTE: jina-reranker-v2 is CC-BY-NC (non-commercial). For a commercial launch, swap to
    # a commercial-safe multilingual reranker (e.g. BAAI/bge-reranker-v2-m3 via add_custom_model).
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    rerank_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    embed_dim: int = 384
    # Rerank toggle. The cross-encoder is the dominant retrieval cost (the ~1GB startup warmup +
    # a CPU forward pass over the fused pool every turn). When false, kb_retrieve skips it: it
    # orders by a cheap lexical-overlap fallback (same 0..1 scale as FakeReranker, so the tenant
    # relevance_threshold / grounding gate still applies) and the startup warmup skips the reranker.
    # Trade-off: the fallback is lexical, not semantic/cross-lingual — flip back to true to restore
    # multilingual grounding quality. No key/model change needed to toggle.
    rerank_enabled: bool = False
    # Where fastembed caches the ONNX weights. Pinned to a persistent path in the Docker image so
    # the model is baked into an image layer (no per-machine download). None -> fastembed default.
    embed_cache_dir: str | None = None
    cohere_api_key: str = ""

    # M3 ingestion: when true, the knowledge API runs ingest inline in the request instead of
    # enqueuing the Celery batch task — for broker-less dev/CI/tests (deterministic, no worker).
    ingest_inline: bool = False

    frontend_origin: str = "http://localhost:5173"

    # Platform operator (M10) — a SEPARATE principal from tenant staff (scope=platform), never a
    # tenant JWT. Dev defaults; set real creds in prod.
    platform_admin_email: str = "ops@platform.local"
    platform_admin_password: str = "ops-dev-password"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


# Outbox relay tuning (M9, [IMP-WRK-1]).
OUTBOX_DRAIN_BATCH = 20
OUTBOX_MAX_ATTEMPTS = 6
OUTBOX_BACKOFF_BASE_SECONDS = 30       # next_attempt_at = now + base * 2**(attempts-1)
OUTBOX_REAPER_STUCK_SECONDS = 300      # reset rows stuck in 'sending' this long


@lru_cache
def get_settings() -> Settings:
    return Settings()


# pgvector HNSW runtime tuning (audit [IMP-DAT-1]). With RLS, an ANN search followed by the
# tenant_id filter can silently return < k rows; ef_search >= the candidate pool and pgvector 0.8
# iterative scans keep fetching until k tenant rows are found. Set once per connection (engine.py).
HNSW_EF_SEARCH = 100                 # comfortably clears the hybrid candidate N (=40)
HNSW_ITERATIVE_SCAN = "relaxed_order"  # requires pgvector >= 0.8


# Centralised model pricing (USD per 1M tokens) so per-turn cost is auditable per provider
# ([IMP-DAT-5]). Approximate list prices — update as vendor pricing changes. Fakes cost nothing.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model_id: (input_per_million, output_per_million)
    "gpt-4o-mini": (0.15, 0.60),
    "fake": (0.0, 0.0),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Per-turn cost for one model call, or None if the model's price is unknown.

    OpenAI echoes a *dated snapshot* id in the response (e.g. ``gpt-4o-mini-2024-07-18``), which
    is not a literal MODEL_PRICING key. Fall back to the longest pricing key that prefixes the
    returned id, so snapshots price at the base model's rate while ``""`` (no-LLM turns) and
    genuinely unknown models still return None.
    """
    price = MODEL_PRICING.get(model)
    if price is None and model:
        match = max((k for k in MODEL_PRICING if model.startswith(k)), key=len, default=None)
        price = MODEL_PRICING[match] if match else None
    if price is None:
        return None
    inp, out = price
    return round((prompt_tokens * inp + completion_tokens * out) / 1_000_000, 8)


class TenantDefaults:
    """Reference defaults (§11). Seed values for ``agent_settings``; tenant-overridable."""

    # Session / conversation
    SESSION_ID_TTL_SECONDS: int = 30 * 24 * 3600  # 30 days (session stamped with expires_at)

    # Per-turn engine budget
    PER_TURN_TIMEOUT_SECONDS: int = 20  # time-to-first-token (NOT whole-turn wall-clock)
    PER_STEP_BUDGET_SECONDS: int = 10  # single model/tool step budget
    MAX_TOOL_CALLS_PER_TURN: int = 5  # 4–6; worst-case turn = this × per-step budget
    STALL_RETRIES: int = 1
    ESCALATE_ON_TIMEOUT: bool = True

    # Ticket lifecycle timers
    RESOLVE_AFTER_IDLE_SECONDS: int = 10 * 60
    CLOSE_AFTER_IDLE_SECONDS: int = 10 * 60
    REOPEN_WINDOW_SECONDS: int = 72 * 3600  # measured from closed_at

    # Identity verification (durable per (tenant, record_type, key), NOT per session)
    VERIFY_MAX_ATTEMPTS: int = 3
    VERIFY_MAX_ATTEMPTS_HEALTHCARE: int = 1
    VERIFY_LOCKOUT_SECONDS: int = 15 * 60

    # Connectors
    CONNECTOR_TIMEOUT_SECONDS: float = 5.0
    CONNECTOR_RETRIES: int = 1

    # Ingestion limits
    MAX_FILE_BYTES: int = 25 * 1024 * 1024  # 25 MB per file
    KB_TOTAL_BYTES_LIMIT: int = 500 * 1024 * 1024  # per-tenant total (configurable)
    MAX_ROWS_PER_RECORD_TYPE: int = 50_000

    # Chunking
    CHILD_CHUNK_MIN_TOKENS: int = 300
    CHILD_CHUNK_MAX_TOKENS: int = 500
    CHILD_CHUNK_OVERLAP_PCT: float = 0.15
    PARENT_CHUNK_TOKENS: int = 2000
    CONTEXTUAL_AUGMENTATION_ENABLED: bool = False  # [T1] OFF by default for the POC

    # Hybrid retrieval + grounding gate
    HYBRID_CANDIDATES_N: int = 40
    RRF_K: int = 60
    RERANK_TOP_K: int = 5
    # [T3] absolute gate only for the POC (top-1 rerank >= threshold); margin deferred.
    RELEVANCE_THRESHOLD: float | None = None  # eval-derived via the calibration harness

    # Autonomy
    AUTONOMY_ENABLED: bool = True

    # Crawl bounds (§4.6)
    CRAWL_MAX_DEPTH: int = 2  # page given = 0; its links = 1; theirs = 2
    CRAWL_MAX_PAGES: int = 50
    CRAWL_MAX_BYTES_PER_PAGE: int = 5 * 1024 * 1024
    CRAWL_FETCH_TIMEOUT_SECONDS: float = 10.0

    SLA_FOLLOWUP_TEXT: str = "A human will follow up by the next business day."
