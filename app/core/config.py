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

from pydantic import Field
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

    redis_url: str = "redis://localhost:6379/6379"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "no-reply@cs-agent.local"

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
    embed_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    embed_dim: int = 1024
    cohere_api_key: str = ""

    frontend_origin: str = "http://localhost:5173"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


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
    """Per-turn cost for one model call, or None if the model's price is unknown."""
    price = MODEL_PRICING.get(model)
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
