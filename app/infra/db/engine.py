"""Async engines + session factories.

Three roles (see .env.example), and the runtime NEVER connects as owner/superuser:
  * ``engine`` / ``SessionLocal`` — the app role (NOSUPERUSER, non-owner). RLS is enforced.
  * ``bypass_engine`` — the audited BYPASSRLS role, its OWN pool, used only by M10 ops.

We keep SQLAlchemy's default ``reset_on_return='rollback'`` so a ``SET LOCAL`` tenant GUC
can never survive a pooled-connection checkout (the #1 cross-tenant leak vector). We do NOT
add a DISCARD-ALL checkin hook (async reset can't do IO) — SET LOCAL inside a per-request
transaction is sufficient (see research / [IMP-SEC-1]).
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import NullPool, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import HNSW_EF_SEARCH, HNSW_ITERATIVE_SCAN, get_settings

_settings = get_settings()

engine = create_async_engine(_settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Worker engine — NullPool (no shared pool). Celery runs each task in a FRESH event loop
# (``asyncio.run`` in app/workers/_run.py and the scheduled tasks). A pooled asyncpg connection
# is bound to the loop that created it, so reusing one across per-task loops raises "attached to a
# different loop" (the pre-ping validation in the traceback). NullPool opens a fresh connection per
# checkout and closes it on return — no cross-loop reuse — which is the standard fix for async
# SQLAlchemy under Celery. Still RLS-safe: a brand-new connection can't carry a stale ``SET LOCAL``
# tenant GUC, and the GUC is set per-transaction inside ``with_tenant``.
worker_engine = create_async_engine(_settings.database_url, poolclass=NullPool)
WorkerSessionLocal = async_sessionmaker(worker_engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _tune_pgvector_search(dbapi_connection, _record) -> None:
    """Set pgvector HNSW scan params once per connection ([IMP-DAT-1]) so RLS-filtered ANN never
    silently returns < k neighbours. Each SET is guarded so a pre-0.8 pgvector (no iterative_scan)
    can't break connections — the index still works, just without the tuning."""
    for stmt in (
        f"SET hnsw.ef_search = {int(HNSW_EF_SEARCH)}",
        f"SET hnsw.iterative_scan = '{HNSW_ITERATIVE_SCAN}'",
    ):
        try:
            cur = dbapi_connection.cursor()
            cur.execute(stmt)
            cur.close()
        except Exception:  # noqa: BLE001 — tuning is best-effort; never fail a connection over it
            pass


# Same pgvector tuning on the worker (NullPool) engine's fresh connections.
event.listen(worker_engine.sync_engine, "connect", _tune_pgvector_search)


@lru_cache
def get_bypass_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Lazily-built session factory on the dedicated RLS-bypass role/connection (M10 only)."""
    bypass_engine = create_async_engine(_settings.database_bypass_url, pool_pre_ping=True)
    return async_sessionmaker(bypass_engine, class_=AsyncSession, expire_on_commit=False)
