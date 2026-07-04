"""M7 — Agent Workspace & Presence: presence heartbeat, the live queue, claim/release, and
reply/notes. Every write endpoint that acts on an already-claimed ticket enforces server-side
that the caller IS the current holder — read-only is an authorization check, not a UI toggle.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.errors import AppError
from app.infra.db.models.conversation import Message
from app.infra.db.models.ticket import InternalNote, Ticket
from app.schemas.agents import ClaimResponse, NoteRequest, PresenceRequest, QueueEntry, ReplyRequest
from app.schemas.auth import StaffContext
from app.services import presence_service
from app.services.tag_service import list_ticket_tags
from app.services.ticket_service import claim_ticket, release_ticket

router = APIRouter(tags=["agents"])


async def _load_ticket_or_404(session: AsyncSession, ticket_id: uuid.UUID) -> Ticket:
    ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one_or_none()
    if ticket is None:
        raise AppError(status_code=404, title="Ticket not found", code="ticket_not_found")
    return ticket


def _require_current_assignee(ticket: Ticket, staff: StaffContext) -> None:
    """[watch-out #7] Server-side read-only enforcement — every write on a claimed ticket must
    be performed by its current holder, never trusted from client-side UI state alone."""
    if str(ticket.assignee_id) != staff.staff_id:
        raise AppError(
            status_code=403,
            title="This ticket is claimed by another agent",
            code="not_current_assignee",
        )


@router.post("/agents/presence")
async def set_presence(
    body: PresenceRequest,
    staff: StaffContext = Depends(require_permission("agents:queue")),
) -> dict:
    if body.status == "available":
        await presence_service.set_available(staff.tenant_id, uuid.UUID(staff.staff_id))
    else:
        await presence_service.set_away(staff.tenant_id, uuid.UUID(staff.staff_id))
    return {"status": body.status}


@router.get("/agents/queue", response_model=list[QueueEntry])
async def get_queue(
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("agents:queue")),
) -> list[QueueEntry]:
    # Unclaimed escalations only — a claimed ticket (`with_agent`) has left the shared queue for
    # its holder's individual working view. FIFO by `escalated_at` [IMP-ESC-8].
    tickets = (
        await session.execute(
            select(Ticket)
            .where(Ticket.state == "escalated")
            .order_by(Ticket.escalated_at.asc())
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    entries = []
    for t in tickets:
        tags = await list_ticket_tags(session, ticket_id=t.id)
        wait_seconds = (now - t.escalated_at).total_seconds() if t.escalated_at else 0.0
        entries.append(
            QueueEntry(
                id=str(t.id), priority=t.priority, language=t.language,
                escalated_at=t.escalated_at, wait_seconds=wait_seconds,
                tags=[{"name": tag["name"], "status": tag["status"]} for tag in tags],
            )
        )
    return entries


@router.post("/tickets/{ticket_id}/claim", response_model=ClaimResponse)
async def claim(
    ticket_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("tickets:claim")),
) -> ClaimResponse:
    result = await claim_ticket(session, ticket_id=ticket_id, agent_staff_id=uuid.UUID(staff.staff_id))
    if not result.applied:
        # [IMP-ESC-2] the loser gets 409 + who already holds it.
        current = await _load_ticket_or_404(session, ticket_id)
        raise AppError(
            status_code=409,
            title="Already claimed",
            code="already_claimed",
            detail=f"assignee_id={current.assignee_id}",
        )
    ticket = await _load_ticket_or_404(session, ticket_id)
    return ClaimResponse(id=str(ticket.id), state=ticket.state, assignee_id=str(ticket.assignee_id))


@router.post("/tickets/{ticket_id}/release", response_model=ClaimResponse)
async def release(
    ticket_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("tickets:reply")),
) -> ClaimResponse:
    ticket = await _load_ticket_or_404(session, ticket_id)
    _require_current_assignee(ticket, staff)
    result = await release_ticket(session, ticket_id=ticket_id, agent_staff_id=uuid.UUID(staff.staff_id))
    if not result.applied:
        raise AppError(status_code=409, title="Ticket already moved on", code="release_conflict")
    ticket = await _load_ticket_or_404(session, ticket_id)
    return ClaimResponse(id=str(ticket.id), state=ticket.state, assignee_id=None)


@router.post("/tickets/{ticket_id}/reply")
async def reply(
    ticket_id: uuid.UUID,
    body: ReplyRequest,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("tickets:reply")),
) -> dict:
    ticket = await _load_ticket_or_404(session, ticket_id)
    _require_current_assignee(ticket, staff)
    message = Message(conversation_id=ticket.conversation_id, role="agent", content=body.content)
    session.add(message)
    await session.flush()
    return {"id": str(message.id)}


@router.post("/tickets/{ticket_id}/notes")
async def add_note(
    ticket_id: uuid.UUID,
    body: NoteRequest,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("tickets:reply")),
) -> dict:
    ticket = await _load_ticket_or_404(session, ticket_id)
    _require_current_assignee(ticket, staff)
    note = InternalNote(ticket_id=ticket_id, staff_id=uuid.UUID(staff.staff_id), content=body.content)
    session.add(note)
    await session.flush()
    return {"id": str(note.id)}
