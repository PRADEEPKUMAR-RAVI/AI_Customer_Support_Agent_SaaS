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

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_settings = get_settings()

engine = create_async_engine(_settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@lru_cache
def get_bypass_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Lazily-built session factory on the dedicated RLS-bypass role/connection (M10 only)."""
    bypass_engine = create_async_engine(_settings.database_bypass_url, pool_pre_ping=True)
    return async_sessionmaker(bypass_engine, class_=AsyncSession, expire_on_commit=False)
