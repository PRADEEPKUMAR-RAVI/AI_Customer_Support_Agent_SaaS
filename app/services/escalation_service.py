"""M6 — Escalation: the "no dead ends" safety net. LLM-free — M2 produces the escalation
summary text and passes it in when it calls this; M6 only decides mode (queued vs after-hours)
and orchestrates the mechanical hand-off. Trigger *evaluation* lives in
``domain.escalation.triggers`` — this module only acts on an already-decided reason.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TenantDefaults
from app.core.events import emit
from app.domain.escalation.reasons import EscalationReason
from app.domain.ticketing.states import Actor
from app.infra.db.models.tenant import AgentSettings
from app.infra.db.models.ticket import ResolutionSummary, Ticket
from app.services import presence_service
from app.services.ticket_service import escalate_ticket

# [C4] deterministic/safety-critical reasons get high priority; everything else stays normal.
_HIGH_PRIORITY_REASONS = {EscalationReason.SENSITIVE, EscalationReason.DISPUTE}


@dataclass(frozen=True)
class HandOffResult:
    applied: bool  # False = the ticket wasn't escalable from its current state (no-op, no side effects)
    mode: str = ""  # queued|after_hours
    customer_message: str = ""


async def escalate(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    tenant_id,
    reason: EscalationReason,
    summary_context: dict | None = None,
) -> HandOffResult:
    """[IMP-ESC-3] Always transitions + enqueues idempotently, regardless of presence — presence
    only decides the customer-facing message and whether the after-hours path also fires.
    ``state=escalated`` with no assignee IS the queue (``GET /agents/queue`` derives from it
    directly); there is no separate queue table to insert into.

    Only the AI actor may drive ``ai_handling -> escalated`` (enforced by the whitelist, not by
    this function) — this is the seam M2 calls once it exists.

    ``summary_context`` (produced by M2, [IMP-ESC-6]) fills the escalation-summary row the human
    agent reads — ``{summary, kb_sources, suggested_reply, linked_record_ref}``. LLM text is M2's
    job; this only persists it onto the stub ``escalate_ticket`` just wrote.
    """
    priority = "high" if reason in _HIGH_PRIORITY_REASONS else "normal"
    result = await escalate_ticket(session, ticket_id=ticket_id, actor=Actor.AI, priority=priority)
    if not result.applied:
        return HandOffResult(applied=False)

    if summary_context:
        await session.execute(
            update(ResolutionSummary)
            .where(ResolutionSummary.ticket_id == ticket_id, ResolutionSummary.type == "escalation")
            .values(
                summary=summary_context.get("summary"),
                kb_sources=summary_context.get("kb_sources"),
                suggested_reply=summary_context.get("suggested_reply"),
                linked_record_ref=summary_context.get("linked_record_ref"),
            )
        )

    agents = await presence_service.available_agents(session, tenant_id)
    settings_row = (await session.execute(select(AgentSettings))).scalar_one_or_none()
    config = settings_row.config if settings_row else {}

    if agents:
        # Email EVERY available agent that a ticket is escalated and waiting to be claimed, so any
        # of them can pick it up (the ticket is also live in the shared queue). Per-agent dedupe
        # key → exactly-once per (ticket, agent) under the at-least-once outbox.
        for staff_id, email in agents:
            await emit(
                session,
                event_type="email.escalation_agent_notify",
                payload={"to": email, "ticket_id": str(ticket_id), "reason": reason.value,
                         "priority": priority},
                dedupe_key=f"esc_agent_notify:{ticket_id}:{staff_id}",
            )
        return HandOffResult(
            applied=True,
            mode="queued",
            customer_message="You're being connected to a human agent.",
        )

    # After-hours: no agent is Available. SLA promise to the customer + a single support-notify
    # email [T6] to the tenant's support address (no recurring unclaimed-nudge scheduler for POC).
    sla_text = config.get("sla_followup_text", TenantDefaults.SLA_FOLLOWUP_TEXT)
    support_email = config.get("support_notification_email")
    if support_email:
        await emit(
            session,
            event_type="email.escalation_support_notify",
            payload={"to": support_email, "ticket_id": str(ticket_id), "reason": reason.value},
            dedupe_key=f"escalation_notify:{ticket_id}",
        )
    return HandOffResult(
        applied=True,
        mode="after_hours",
        customer_message=(
            f"No agents are available right now. Please share your email — {sla_text}"
        ),
    )


async def capture_contact_email(
    session: AsyncSession, *, ticket_id: uuid.UUID, email: str
) -> None:
    """[A15] The narrow, non-LLM after-hours email-capture path. Writes ``ticket.contact_email``
    as a plain field write, never an LLM turn — the live capture (from message text while a
    hand-off is in flight) lives in ``conversation_service``; this remains as a direct helper.
    Kept distinct from any verified ``linked_record`` identity."""
    await session.execute(update(Ticket).where(Ticket.id == ticket_id).values(contact_email=email))
