"""M5 tag classification — [IMP-TKT-6]: ``tag_def`` is the single authoritative approval
state; ``ticket_tag`` denormalizes it and is backfilled when the def's status changes."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.infra.db.engine import SessionLocal
from app.infra.db.models.conversation import Conversation
from app.infra.db.models.tag import TicketTag
from app.infra.db.models.tenant import Tenant
from app.infra.db.session import with_tenant
from app.services.tag_service import approve_tag_def, propose_tag, reject_tag_def
from app.services.ticket_service import get_or_create_ticket

pytestmark = pytest.mark.rls


async def _make_tenant() -> uuid.UUID:
    async with SessionLocal() as session:
        async with session.begin():
            tenant = Tenant(name=f"T-{uuid.uuid4().hex[:8]}", industry="retail", status="active")
            session.add(tenant)
            await session.flush()
            return tenant.id


async def _make_ticket(tenant_id: uuid.UUID) -> uuid.UUID:
    async with with_tenant(tenant_id) as session:
        conversation = Conversation(session_id=f"sess-{uuid.uuid4().hex}")
        session.add(conversation)
        await session.flush()
        ticket = await get_or_create_ticket(session, conversation_id=conversation.id)
        return ticket.id


async def test_curated_tag_is_auto_approved():
    tenant_id = await _make_tenant()
    ticket_id = await _make_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        tag = await propose_tag(
            session, ticket_id=ticket_id, name="billing", allowed_tags=["billing", "refund"]
        )
        assert tag.status == "approved"


async def test_novel_tag_starts_pending():
    tenant_id = await _make_tenant()
    ticket_id = await _make_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        tag = await propose_tag(
            session, ticket_id=ticket_id, name="weird_new_tag", allowed_tags=["billing"]
        )
        assert tag.status == "pending"


async def test_proposing_the_same_tag_twice_is_idempotent():
    tenant_id = await _make_tenant()
    ticket_id = await _make_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        first = await propose_tag(session, ticket_id=ticket_id, name="billing", allowed_tags=["billing"])
    async with with_tenant(tenant_id) as session:
        second = await propose_tag(session, ticket_id=ticket_id, name="billing", allowed_tags=["billing"])
        assert second.id == first.id
        rows = (
            await session.execute(select(TicketTag).where(TicketTag.ticket_id == ticket_id))
        ).scalars().all()
        assert len(rows) == 1


async def test_approving_a_def_backfills_pending_instances():
    tenant_id = await _make_tenant()
    ticket_id = await _make_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        tag = await propose_tag(session, ticket_id=ticket_id, name="new_topic", allowed_tags=[])
        tag_def_id = tag.tag_def_id
        assert tag.status == "pending"

    async with with_tenant(tenant_id) as session:
        approved = await approve_tag_def(session, tag_def_id=tag_def_id)
        assert approved.status == "approved"

    async with with_tenant(tenant_id) as session:
        row = (
            await session.execute(select(TicketTag).where(TicketTag.tag_def_id == tag_def_id))
        ).scalar_one()
        assert row.status == "approved"  # backfilled, not left stale pending


async def test_rejecting_a_def_suppresses_future_proposals_of_the_same_name():
    tenant_id = await _make_tenant()
    ticket_id_1 = await _make_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        tag = await propose_tag(session, ticket_id=ticket_id_1, name="junk", allowed_tags=[])
        tag_def_id = tag.tag_def_id

    async with with_tenant(tenant_id) as session:
        rejected = await reject_tag_def(session, tag_def_id=tag_def_id)
        assert rejected.status == "rejected"

    ticket_id_2 = await _make_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        tag2 = await propose_tag(session, ticket_id=ticket_id_2, name="junk", allowed_tags=[])
        assert tag2.status == "rejected"


async def test_rejecting_a_def_removes_it_from_tickets():
    # PRD §4.2.3: reject REMOVES the tag from the ticket(s) (not just a status flip).
    tenant_id = await _make_tenant()
    ticket_id = await _make_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        tag = await propose_tag(session, ticket_id=ticket_id, name="spam", allowed_tags=[])
        tag_def_id = tag.tag_def_id

    async with with_tenant(tenant_id) as session:
        await reject_tag_def(session, tag_def_id=tag_def_id)

    async with with_tenant(tenant_id) as session:
        rows = (
            await session.execute(select(TicketTag).where(TicketTag.ticket_id == ticket_id))
        ).scalars().all()
        assert rows == []


async def test_approve_unknown_tag_def_returns_none():
    tenant_id = await _make_tenant()
    async with with_tenant(tenant_id) as session:
        result = await approve_tag_def(session, tag_def_id=uuid.uuid4())
        assert result is None
