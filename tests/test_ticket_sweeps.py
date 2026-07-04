"""M9 wiring — [IMP-WRK-3] query-driven, idempotent ticket idle-resolve/idle-close sweeps.
Pure service-level (no Celery needed to test the logic); needs a live Postgres."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

import pytest

from app.infra.db.engine import SessionLocal
from app.infra.db.models.conversation import Conversation
from app.infra.db.models.tenant import Tenant
from app.infra.db.models.ticket import Ticket
from app.infra.db.session import with_tenant
from app.services.ticket_service import (
    get_or_create_ticket,
    resolve_ticket,
    start_ai_handling,
    sweep_idle_ai_handling_to_resolved,
    sweep_idle_resolved_to_closed,
)

pytestmark = pytest.mark.rls


async def _make_tenant() -> uuid.UUID:
    async with SessionLocal() as session:
        async with session.begin():
            tenant = Tenant(name=f"T-{uuid.uuid4().hex[:8]}", industry="retail", status="active")
            session.add(tenant)
            await session.flush()
            return tenant.id


async def _make_ai_handling_ticket(tenant_id: uuid.UUID) -> uuid.UUID:
    async with with_tenant(tenant_id) as session:
        conversation = Conversation(session_id=f"sess-{uuid.uuid4().hex}")
        session.add(conversation)
        await session.flush()
        ticket = await get_or_create_ticket(session, conversation_id=conversation.id)
        ticket_id = ticket.id
    async with with_tenant(tenant_id) as session:
        await start_ai_handling(session, ticket_id=ticket_id)
    return ticket_id


async def test_sweep_resolves_an_idle_ai_handling_ticket():
    tenant_id = await _make_tenant()
    ticket_id = await _make_ai_handling_ticket(tenant_id)
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    async with with_tenant(tenant_id) as session:
        await session.execute(update(Ticket).where(Ticket.id == ticket_id).values(updated_at=stale))

    async with with_tenant(tenant_id) as session:
        count = await sweep_idle_ai_handling_to_resolved(session, idle_seconds=600)
        assert count == 1

    async with with_tenant(tenant_id) as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
        assert ticket.state == "resolved"


async def test_sweep_does_not_touch_a_recently_active_ticket():
    tenant_id = await _make_tenant()
    ticket_id = await _make_ai_handling_ticket(tenant_id)  # updated_at is "now"

    async with with_tenant(tenant_id) as session:
        count = await sweep_idle_ai_handling_to_resolved(session, idle_seconds=600)
        assert count == 0

    async with with_tenant(tenant_id) as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
        assert ticket.state == "ai_handling"


async def test_sweep_respects_last_customer_msg_at_over_updated_at():
    tenant_id = await _make_tenant()
    ticket_id = await _make_ai_handling_ticket(tenant_id)
    # updated_at is fresh (just transitioned), but a customer messaged long before that and
    # nothing since — the sweep must anchor on last_customer_msg_at, not updated_at.
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    async with with_tenant(tenant_id) as session:
        await session.execute(
            update(Ticket).where(Ticket.id == ticket_id).values(last_customer_msg_at=stale)
        )

    async with with_tenant(tenant_id) as session:
        count = await sweep_idle_ai_handling_to_resolved(session, idle_seconds=600)
        assert count == 1


async def test_sweep_closes_an_idle_resolved_ticket():
    tenant_id = await _make_tenant()
    ticket_id = await _make_ai_handling_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        await resolve_ticket(session, ticket_id=ticket_id)
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    async with with_tenant(tenant_id) as session:
        await session.execute(update(Ticket).where(Ticket.id == ticket_id).values(resolved_at=stale))

    async with with_tenant(tenant_id) as session:
        count = await sweep_idle_resolved_to_closed(session, idle_seconds=600)
        assert count == 1

    async with with_tenant(tenant_id) as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
        assert ticket.state == "closed"


async def test_sweep_is_idempotent_on_a_second_run():
    tenant_id = await _make_tenant()
    ticket_id = await _make_ai_handling_ticket(tenant_id)
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    async with with_tenant(tenant_id) as session:
        await session.execute(update(Ticket).where(Ticket.id == ticket_id).values(updated_at=stale))

    async with with_tenant(tenant_id) as session:
        first = await sweep_idle_ai_handling_to_resolved(session, idle_seconds=600)
        assert first == 1
    async with with_tenant(tenant_id) as session:
        second = await sweep_idle_ai_handling_to_resolved(session, idle_seconds=600)
        assert second == 0  # already resolved — not a candidate anymore, not double-fired
