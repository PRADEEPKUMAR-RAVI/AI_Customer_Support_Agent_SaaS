"""M6 escalation orchestration — [IMP-ESC-3] always enqueues (state=escalated IS the queue),
presence decides only the customer message + after-hours path."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.domain.escalation.reasons import EscalationReason
from app.domain.records.schemas import Industry
from app.domain.tenancy.defaults import default_agent_settings
from app.infra.db.models.conversation import Conversation
from app.infra.db.models.outbox import Outbox
from app.infra.db.models.tenant import AgentSettings, Staff, Tenant
from app.infra.db.models.ticket import ResolutionSummary, Ticket
from app.infra.db.engine import SessionLocal
from app.infra.db.session import with_tenant
from app.services import presence_service
from app.services.escalation_service import capture_contact_email, escalate
from app.services.ticket_service import get_or_create_ticket, start_ai_handling

pytestmark = pytest.mark.rls


async def _make_tenant_ticket_and_staff() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with SessionLocal() as session:
        async with session.begin():
            tenant = Tenant(name=f"T-{uuid.uuid4().hex[:8]}", industry="retail", status="active")
            session.add(tenant)
            await session.flush()
            tenant_id = tenant.id
    async with with_tenant(tenant_id) as session:
        # A real tenant always has an agent_settings row from signup — mirror that here so
        # `escalate()`'s config lookups (sla text, support-notify address) behave realistically.
        session.add(AgentSettings(config=default_agent_settings(Industry.RETAIL)))
        staff = Staff(email=f"a-{uuid.uuid4().hex}@example.com", password_hash="x", role="agent")
        session.add(staff)
        conversation = Conversation(session_id=f"sess-{uuid.uuid4().hex}")
        session.add(conversation)
        await session.flush()
        staff_id = staff.id
        ticket = await get_or_create_ticket(session, conversation_id=conversation.id)
        ticket_id = ticket.id
    async with with_tenant(tenant_id) as session:
        await start_ai_handling(session, ticket_id=ticket_id)
    return tenant_id, ticket_id, staff_id


async def test_escalate_with_an_available_agent_returns_queued():
    tenant_id, ticket_id, staff_id = await _make_tenant_ticket_and_staff()
    await presence_service.set_available(tenant_id, staff_id)

    async with with_tenant(tenant_id) as session:
        result = await escalate(
            session, ticket_id=ticket_id, tenant_id=tenant_id, reason=EscalationReason.EXPLICIT
        )
        assert result.applied is True
        assert result.mode == "queued"

    async with with_tenant(tenant_id) as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
        assert ticket.state == "escalated"
        assert ticket.priority == "normal"  # explicit is not a high-priority reason
        assert ticket.escalated_at is not None

        summaries = (
            await session.execute(
                select(ResolutionSummary).where(ResolutionSummary.ticket_id == ticket_id)
            )
        ).scalars().all()
        assert len(summaries) == 1
        assert summaries[0].type == "escalation"


async def test_escalate_with_no_agent_available_captures_after_hours_and_notifies_support():
    tenant_id, ticket_id, _staff_id = await _make_tenant_ticket_and_staff()
    async with with_tenant(tenant_id) as session:
        settings_row = (await session.execute(select(AgentSettings))).scalar_one()
        settings_row.config = {**settings_row.config, "support_notification_email": "support@acme.test"}

    async with with_tenant(tenant_id) as session:
        result = await escalate(
            session, ticket_id=ticket_id, tenant_id=tenant_id, reason=EscalationReason.DISPUTE
        )
        assert result.applied is True
        assert result.mode == "after_hours"
        assert "email" in result.customer_message.lower()

    async with with_tenant(tenant_id) as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
        assert ticket.priority == "high"  # [C4] dispute is a high-priority reason

        outbox_rows = (
            await session.execute(
                select(Outbox).where(Outbox.event_type == "email.escalation_support_notify")
            )
        ).scalars().all()
        assert len(outbox_rows) == 1
        assert outbox_rows[0].payload["to"] == "support@acme.test"


async def test_escalate_is_a_noop_when_ticket_is_not_ai_handling():
    tenant_id, ticket_id, _staff_id = await _make_tenant_ticket_and_staff()
    async with with_tenant(tenant_id) as session:
        first = await escalate(
            session, ticket_id=ticket_id, tenant_id=tenant_id, reason=EscalationReason.EXPLICIT
        )
        assert first.applied is True

    async with with_tenant(tenant_id) as session:
        second = await escalate(
            session, ticket_id=ticket_id, tenant_id=tenant_id, reason=EscalationReason.EXPLICIT
        )
        assert second.applied is False


async def test_capture_contact_email_writes_even_though_escalated():
    tenant_id, ticket_id, _staff_id = await _make_tenant_ticket_and_staff()
    async with with_tenant(tenant_id) as session:
        await escalate(
            session, ticket_id=ticket_id, tenant_id=tenant_id, reason=EscalationReason.NO_GROUNDING
        )

    async with with_tenant(tenant_id) as session:
        await capture_contact_email(session, ticket_id=ticket_id, email="waiting@customer.test")

    async with with_tenant(tenant_id) as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
        assert ticket.state == "escalated"
        assert ticket.contact_email == "waiting@customer.test"
