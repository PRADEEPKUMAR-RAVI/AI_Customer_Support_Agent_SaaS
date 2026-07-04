"""Tenant-context / RLS session helpers — the isolation harness (non-negotiable #4).

Every DB access runs inside a transaction that first sets the tenant GUC with
``set_config('app.tenant_id', :tid, true)`` (transaction-local, i.e. ``SET LOCAL``). The RLS
policy compares ``tenant_id`` against ``current_setting('app.tenant_id', true)``.

  * ``with_tenant(tenant_id)`` — for **workers** (Celery has no request scope). Every task
    that touches tenant data MUST open this or RLS will see no tenant and return nothing.
  * ``platform_bypass(...)`` — the ONLY audited RLS-bypass path (M10), on its own connection,
    writing a non-RLS audit row in the same transaction.

The FastAPI request dependency lives in ``app.api.deps.get_db`` (it resolves the tenant from
JWT/widget-key first, then uses the same GUC-setting logic).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.engine import SessionLocal, get_bypass_sessionmaker

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tid, true)")


async def set_tenant_guc(session: AsyncSession, tenant_id) -> None:
    await session.execute(_SET_TENANT, {"tid": str(tenant_id)})


@asynccontextmanager
async def with_tenant(tenant_id) -> AsyncIterator[AsyncSession]:
    """Worker-side tenant context. Opens a transaction, sets the GUC, commits on success."""
    async with SessionLocal() as session:
        async with session.begin():
            await set_tenant_guc(session, tenant_id)
            yield session


@asynccontextmanager
async def auth_bootstrap_session() -> AsyncIterator[AsyncSession]:
    """Pre-tenant identity resolution for LOGIN ONLY (email -> tenant + credentials).

    Login can't know the tenant before it authenticates, so this narrow read uses the
    BYPASSRLS role (no audit row — it's authentication, not an ops action). It must be used
    ONLY to look up a staff row by (globally-unique) email during login. Everything after
    authentication uses tenant-scoped sessions. Documented POC bootstrap ([C5]-adjacent)."""
    sm = get_bypass_sessionmaker()
    async with sm() as session:
        yield session


@asynccontextmanager
async def platform_bypass(
    *, actor_admin_id, action: str, target_tenant_id=None
) -> AsyncIterator[AsyncSession]:
    """Audited cross-tenant read/write for M10 ops. Uses the dedicated BYPASSRLS role on its
    own pool (never the request pool) and writes an append-only audit row in the SAME
    transaction so the bypass can't be used without a trace ([IMP-SEC-9])."""
    from app.infra.db.models.outbox import PlatformAuditLog  # lazy

    sm = get_bypass_sessionmaker()
    async with sm() as session:
        async with session.begin():
            session.add(
                PlatformAuditLog(
                    actor_admin_id=actor_admin_id,
                    action=action,
                    target_tenant_id=target_tenant_id,
                )
            )
            yield session
