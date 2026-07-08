"""M7 agent presence — liveness backed by a Redis key with a short TTL [IMP-ESC-1], not a DB
row or a scheduled sweep. A crashed or closed-tab agent simply stops refreshing the key; it
expires and they read as Away for free.

The plan ties the refresh to "the agent-workspace SSE connection's heartbeat". This POC exposes
the identical liveness property via an explicit ``POST /agents/presence`` heartbeat the FE calls
on an interval instead: no SSE server-push channel exists yet for anything but the customer-chat
protocol (frozen, person-1-owned), and standing one up here would be machinery this doesn't need
— stop calling the heartbeat, the TTL expires, the agent goes Away, exactly like a dropped SSE
connection would.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.cache.redis import get_redis

PRESENCE_TTL_SECONDS = 60


def _key(tenant_id, staff_id) -> str:
    return f"presence:{tenant_id}:{staff_id}"


async def set_available(tenant_id, staff_id: uuid.UUID) -> None:
    await get_redis().set(_key(tenant_id, staff_id), "available", ex=PRESENCE_TTL_SECONDS)


async def set_away(tenant_id, staff_id: uuid.UUID) -> None:
    await get_redis().delete(_key(tenant_id, staff_id))


async def is_available(tenant_id, staff_id: uuid.UUID) -> bool:
    return bool(await get_redis().exists(_key(tenant_id, staff_id)))


async def is_tenant_available(session: AsyncSession, tenant_id) -> bool:
    """True iff ANY active staff member of this tenant currently holds a live presence key.
    Queries the tenant's (small) staff list rather than a Redis SCAN across keys — used by M6
    to decide queued-vs-after-hours."""
    return bool(await available_agents(session, tenant_id))


async def available_agents(session: AsyncSession, tenant_id) -> list[tuple[uuid.UUID, str]]:
    """``(staff_id, email)`` for every ACTIVE staff member currently holding a live presence key
    (i.e. toggled Available and heartbeating). Used by M6 to (a) decide queued-vs-after-hours and
    (b) email each available agent that a ticket was escalated and is waiting to be claimed."""
    from app.infra.db.models.tenant import Staff  # lazy: avoid a cache<->db import cycle

    rows = (
        await session.execute(select(Staff.id, Staff.email).where(Staff.is_active.is_(True)))
    ).all()
    redis = get_redis()
    out: list[tuple[uuid.UUID, str]] = []
    for staff_id, email in rows:
        if await redis.exists(_key(tenant_id, staff_id)):
            out.append((staff_id, email))
    return out
