"""M5 ticket_service — Phase-1 walking-skeleton scope: get-or-create, the guarded-CAS
``new -> ai_handling -> resolved`` path, and the resolution-summary stub ([IMP-TKT-2],
[IMP-TKT-4], [IMP-ESC-6]).

Needs a live Postgres with the migration applied (same harness as ``test_rls_isolation.py``).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.domain.ticketing.states import Actor
from app.infra.db.engine import SessionLocal
from app.infra.db.models.conversation import Conversation
from app.infra.db.models.tenant import Tenant
from app.infra.db.models.ticket import ResolutionSummary, Ticket
from app.infra.db.session import with_tenant
from app.services.ticket_service import get_or_create_ticket, resolve_ticket, start_ai_handling

pytestmark = pytest.mark.rls


async def _make_tenant_and_conversation() -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as session:
        async with session.begin():
            tenant = Tenant(name=f"T-{uuid.uuid4().hex[:8]}", industry="retail", status="active")
            session.add(tenant)
            await session.flush()
            tenant_id = tenant.id
    async with with_tenant(tenant_id) as session:
        conversation = Conversation(session_id=f"sess-{uuid.uuid4().hex}")
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id
    return tenant_id, conversation_id


async def test_get_or_create_ticket_is_idempotent():
    tenant_id, conversation_id = await _make_tenant_and_conversation()

    async with with_tenant(tenant_id) as session:
        first = await get_or_create_ticket(session, conversation_id=conversation_id)
        first_id = first.id
    async with with_tenant(tenant_id) as session:
        second = await get_or_create_ticket(session, conversation_id=conversation_id)
        assert second.id == first_id
        assert second.state == "new"

    # Exactly one row exists — a concurrent/duplicate first-message never creates two tickets.
    async with with_tenant(tenant_id) as session:
        rows = (
            await session.execute(select(Ticket).where(Ticket.conversation_id == conversation_id))
        ).scalars().all()
        assert len(rows) == 1


async def test_new_to_ai_handling_to_resolved_writes_summary_stub():
    tenant_id, conversation_id = await _make_tenant_and_conversation()

    async with with_tenant(tenant_id) as session:
        ticket = await get_or_create_ticket(session, conversation_id=conversation_id)
        ticket_id = ticket.id

    async with with_tenant(tenant_id) as session:
        result = await start_ai_handling(session, ticket_id=ticket_id)
        assert result.applied is True

    async with with_tenant(tenant_id) as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
        assert ticket.state == "ai_handling"

    async with with_tenant(tenant_id) as session:
        result = await resolve_ticket(session, ticket_id=ticket_id)
        assert result.applied is True

    async with with_tenant(tenant_id) as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
        assert ticket.state == "resolved"
        assert ticket.resolved_at is not None

        summaries = (
            await session.execute(
                select(ResolutionSummary).where(ResolutionSummary.ticket_id == ticket_id)
            )
        ).scalars().all()
        assert len(summaries) == 1
        assert summaries[0].type == "resolution"
        assert summaries[0].summary is None  # pending — M2 fills this in asynchronously


async def test_start_ai_handling_is_a_noop_once_already_handling():
    tenant_id, conversation_id = await _make_tenant_and_conversation()
    async with with_tenant(tenant_id) as session:
        ticket = await get_or_create_ticket(session, conversation_id=conversation_id)
        ticket_id = ticket.id
    async with with_tenant(tenant_id) as session:
        assert (await start_ai_handling(session, ticket_id=ticket_id)).applied is True
    async with with_tenant(tenant_id) as session:
        # A later message on the same conversation calls this again — must be a clean no-op.
        assert (await start_ai_handling(session, ticket_id=ticket_id)).applied is False


async def test_double_resolve_is_a_noop_and_never_double_writes_the_summary():
    """Simulates the sweep-vs-message race [watch-out #8]: two writers both try to resolve the
    same ticket. The second must change nothing and must NOT create a second summary row."""
    tenant_id, conversation_id = await _make_tenant_and_conversation()
    async with with_tenant(tenant_id) as session:
        ticket = await get_or_create_ticket(session, conversation_id=conversation_id)
        ticket_id = ticket.id
    async with with_tenant(tenant_id) as session:
        await start_ai_handling(session, ticket_id=ticket_id)

    async with with_tenant(tenant_id) as session:
        first = await resolve_ticket(session, ticket_id=ticket_id, actor=Actor.AI)
        assert first.applied is True
    async with with_tenant(tenant_id) as session:
        second = await resolve_ticket(session, ticket_id=ticket_id, actor=Actor.SYSTEM)
        assert second.applied is False

    async with with_tenant(tenant_id) as session:
        summaries = (
            await session.execute(
                select(ResolutionSummary).where(ResolutionSummary.ticket_id == ticket_id)
            )
        ).scalars().all()
        assert len(summaries) == 1
