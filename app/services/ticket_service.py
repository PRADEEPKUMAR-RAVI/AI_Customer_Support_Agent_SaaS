"""M5 — ticketing (walking-skeleton slice).

get-or-create one ticket per conversation, and transition ONLY through the guarded CAS
primitive. person-3 owns the full M5 (tags, reopen, resolution summaries, search); the pieces
here are the minimum M2 needs to drive the lifecycle, and they use the same non-negotiable
primitive so behaviour won't change under person-3.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.domain.ticketing.states import Actor, TicketState
from app.domain.ticketing.transitions import apply_transition
from app.infra.db.models.ticket import Ticket


async def get_or_create_ticket(session, *, conversation_id, language: str | None = None) -> Ticket:
    existing = (
        await session.execute(select(Ticket).where(Ticket.conversation_id == conversation_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    # Single-active-turn lock (M2) serialises turns per conversation, so no create race here.
    ticket = Ticket(conversation_id=conversation_id, state=TicketState.NEW.value, priority="normal",
                    language=language, last_customer_msg_at=datetime.now(timezone.utc))
    session.add(ticket)
    await session.flush()
    return ticket


async def transition(session, *, ticket: Ticket, to_state: TicketState, actor: Actor) -> bool:
    """Guarded CAS transition; returns True iff it applied. On success, updates the in-memory
    object's state so callers see the new value."""
    current = TicketState(ticket.state)
    result = await apply_transition(
        session, ticket_id=ticket.id, to_state=to_state, actor=actor, expected_from=current
    )
    if result.applied:
        ticket.state = to_state.value
    return result.applied
