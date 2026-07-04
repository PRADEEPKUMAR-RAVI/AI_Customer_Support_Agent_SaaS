"""M7 presence — Redis-TTL-backed liveness [IMP-ESC-1]. Needs a live Postgres + Redis."""

from __future__ import annotations

import uuid

import pytest

from app.infra.cache.redis import get_redis
from app.infra.db.engine import SessionLocal
from app.infra.db.models.tenant import Tenant
from app.infra.db.session import with_tenant
from app.services import presence_service

pytestmark = pytest.mark.rls


async def _make_tenant() -> uuid.UUID:
    async with SessionLocal() as session:
        async with session.begin():
            tenant = Tenant(name=f"T-{uuid.uuid4().hex[:8]}", industry="retail", status="active")
            session.add(tenant)
            await session.flush()
            return tenant.id


async def test_set_available_then_away_roundtrip():
    tenant_id = await _make_tenant()
    staff_id = uuid.uuid4()

    assert await presence_service.is_available(tenant_id, staff_id) is False
    await presence_service.set_available(tenant_id, staff_id)
    assert await presence_service.is_available(tenant_id, staff_id) is True
    await presence_service.set_away(tenant_id, staff_id)
    assert await presence_service.is_available(tenant_id, staff_id) is False


async def test_presence_key_has_a_short_ttl():
    tenant_id = await _make_tenant()
    staff_id = uuid.uuid4()
    await presence_service.set_available(tenant_id, staff_id)
    ttl = await get_redis().ttl(f"presence:{tenant_id}:{staff_id}")
    assert 0 < ttl <= presence_service.PRESENCE_TTL_SECONDS


async def test_is_tenant_available_reflects_any_active_staff():
    tenant_id = await _make_tenant()
    async with with_tenant(tenant_id) as session:
        from app.infra.db.models.tenant import Staff

        staff = Staff(email=f"a-{uuid.uuid4().hex}@example.com", password_hash="x", role="agent")
        session.add(staff)
        await session.flush()
        staff_id = staff.id

    async with with_tenant(tenant_id) as session:
        assert await presence_service.is_tenant_available(session, tenant_id) is False

    await presence_service.set_available(tenant_id, staff_id)
    async with with_tenant(tenant_id) as session:
        assert await presence_service.is_tenant_available(session, tenant_id) is True
