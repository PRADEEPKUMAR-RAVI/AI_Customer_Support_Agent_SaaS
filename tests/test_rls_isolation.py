"""The two-tenant RLS leak test — the critical CI gate ([IMP-DEL-2]).

Proves cross-tenant isolation on a real Postgres: (a) tenant B never sees tenant A's rows,
(b) a write that mismatches the tenant context is rejected by WITH CHECK, (c) with no tenant
context the app role reads nothing. Marked ``rls`` — skipped unless RUN_RLS_TESTS=1 with a
live DB (migration applied, cs_app role). Run via ``make test-rls`` or in CI.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from app.infra.db.engine import SessionLocal
from app.infra.db.models.tenant import Staff, Tenant
from app.infra.db.session import set_tenant_guc, with_tenant

pytestmark = pytest.mark.rls


async def _make_tenant(name: str) -> uuid.UUID:
    async with SessionLocal() as session:
        async with session.begin():
            tenant = Tenant(name=name, industry="retail", status="active")
            session.add(tenant)
            await session.flush()
            return tenant.id


async def test_tenant_b_cannot_see_tenant_a_rows():
    tenant_a = await _make_tenant("Isolation-A")
    tenant_b = await _make_tenant("Isolation-B")
    a_email = f"a-{uuid.uuid4().hex}@x.test"

    async with with_tenant(tenant_a) as session:
        session.add(Staff(email=a_email, password_hash="x", role="admin"))

    # Tenant B sees only its own rows — never A's.
    async with with_tenant(tenant_b) as session:
        rows = (await session.execute(select(Staff))).scalars().all()
        assert all(r.tenant_id == tenant_b for r in rows)
        assert not any(r.email == a_email for r in rows)


async def test_write_with_mismatched_tenant_is_rejected():
    tenant_a = await _make_tenant("Isolation-C")
    tenant_b = await _make_tenant("Isolation-D")
    # Under tenant A's context, try to insert a row explicitly tagged for tenant B.
    with pytest.raises(Exception):  # WITH CHECK violation
        async with with_tenant(tenant_a) as session:
            session.add(
                Staff(
                    tenant_id=tenant_b,  # mismatched
                    email=f"c-{uuid.uuid4().hex}@x.test",
                    password_hash="x",
                    role="admin",
                )
            )


async def test_no_tenant_context_reads_nothing():
    # A session with no tenant GUC set must see zero tenant-scoped rows.
    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
            rows = (await session.execute(select(Staff))).scalars().all()
            assert rows == []
