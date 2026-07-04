"""M5 — Ticketing & Tags: list/detail/patch, reopen, tag approve/reject, and the aggregated
agent-workspace context endpoint ([IMP-FE-8]). Two path families share this router (``/tickets``
and ``/admin/tags``), so it declares no router-level prefix.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.errors import AppError
from app.core.config import TenantDefaults
from app.domain.ticketing.states import Actor, TicketState
from app.infra.db.models.conversation import Message
from app.infra.db.models.tag import TagDef, TicketTag
from app.infra.db.models.tenant import AgentSettings
from app.infra.db.models.ticket import InternalNote, ResolutionSummary, Ticket
from app.schemas.auth import StaffContext
from app.schemas.common import Page
from app.schemas.tickets import (
    LiveRecordOut,
    MessageOut,
    NoteOut,
    TagApprovalResponse,
    TagOut,
    TicketContextResponse,
    TicketPatchRequest,
    TicketReopenResponse,
    TicketResponse,
)
from app.services.tag_service import approve_tag_def, list_tag_defs, list_ticket_tags, reject_tag_def
from app.services.ticket_service import reopen_ticket, resolve_ticket

router = APIRouter(tags=["tickets"])


async def _to_ticket_response(session: AsyncSession, t: Ticket) -> TicketResponse:
    tags = await list_ticket_tags(session, ticket_id=t.id)
    return TicketResponse(
        id=str(t.id),
        conversation_id=str(t.conversation_id),
        state=t.state,
        priority=t.priority,
        language=t.language,
        linked_record_type=t.linked_record_type,
        linked_record_key=t.linked_record_key,
        contact_email=t.contact_email,
        assignee_id=str(t.assignee_id) if t.assignee_id else None,
        created_at=t.created_at,
        resolved_at=t.resolved_at,
        closed_at=t.closed_at,
        tags=[TagOut(**tag) for tag in tags],
    )


@router.get("/tickets", response_model=Page[TicketResponse])
async def list_tickets(
    status: str | None = None,
    tag: str | None = None,
    language: str | None = None,
    priority: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("tickets:read")),
) -> Page[TicketResponse]:
    stmt = select(Ticket)
    if status:
        stmt = stmt.where(Ticket.state == status)
    if language:
        stmt = stmt.where(Ticket.language == language)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if date_from:
        stmt = stmt.where(Ticket.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Ticket.created_at <= date_to)
    if tag:
        stmt = (
            stmt.join(TicketTag, TicketTag.ticket_id == Ticket.id)
            .join(TagDef, TagDef.id == TicketTag.tag_def_id)
            .where(TagDef.name == tag)
        )

    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await session.execute(stmt.order_by(Ticket.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()
    items = [await _to_ticket_response(session, t) for t in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("tickets:read")),
) -> TicketResponse:
    ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one_or_none()
    if ticket is None:
        raise AppError(status_code=404, title="Ticket not found", code="ticket_not_found")
    return await _to_ticket_response(session, ticket)


@router.patch("/tickets/{ticket_id}", response_model=TicketResponse)
async def patch_ticket(
    ticket_id: uuid.UUID,
    body: TicketPatchRequest,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("tickets:reply")),
) -> TicketResponse:
    ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one_or_none()
    if ticket is None:
        raise AppError(status_code=404, title="Ticket not found", code="ticket_not_found")

    if body.state is not None:
        if body.state != "resolved":
            raise AppError(status_code=400, title="Unsupported state transition via PATCH",
                           code="unsupported_state")
        # Agent-resolve is only legal from `with_agent` (the whitelist has no AGENT edge out of
        # `ai_handling`) — reject up front rather than let the whitelist raise.
        if ticket.state != TicketState.WITH_AGENT.value:
            raise AppError(status_code=409, title="Ticket cannot be resolved from its current state",
                           code="resolve_not_allowed")
        if str(ticket.assignee_id) != staff.staff_id:
            raise AppError(status_code=403, title="This ticket is claimed by another agent",
                           code="not_current_assignee")
        result = await resolve_ticket(
            session, ticket_id=ticket_id, actor=Actor.AGENT, expected_from=TicketState.WITH_AGENT
        )
        if not result.applied:
            raise AppError(status_code=409, title="Ticket already moved on", code="resolve_conflict")

    if body.priority is not None:
        ticket.priority = body.priority
    if body.contact_email is not None:
        ticket.contact_email = body.contact_email
    await session.flush()
    await session.refresh(ticket)
    return await _to_ticket_response(session, ticket)


@router.post("/tickets/{ticket_id}/reopen", response_model=TicketReopenResponse)
async def reopen(
    ticket_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("tickets:reply")),
) -> TicketReopenResponse:
    settings_row = (await session.execute(select(AgentSettings))).scalar_one_or_none()
    window = (
        settings_row.config.get("reopen_window_seconds") if settings_row else None
    ) or TenantDefaults.REOPEN_WINDOW_SECONDS
    # Only staff call this HTTP endpoint, so it's always the AGENT actor per the whitelist; a
    # customer message reopening a ticket is M2's job, calling this same service as CUSTOMER.
    result = await reopen_ticket(
        session, ticket_id=ticket_id, actor=Actor.AGENT, reopen_window_seconds=window
    )
    if not result.applied:
        raise AppError(
            status_code=409,
            title="Ticket cannot be reopened from its current state",
            code="reopen_not_allowed",
        )
    ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
    return TicketReopenResponse(applied=True, state=ticket.state)


@router.get("/admin/tags", response_model=list[TagApprovalResponse])
async def list_tags(
    status: str | None = Query(default=None, pattern="^(approved|pending|rejected)$"),
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("tags:approve")),
) -> list[TagApprovalResponse]:
    """Tenant's tag definitions for the admin approval tray; ``?status=pending`` backs the
    'pending tags' view (PRD §4.2.3)."""
    defs = await list_tag_defs(session, status=status)
    return [TagApprovalResponse(id=str(d.id), name=d.name, status=d.status) for d in defs]


@router.post("/admin/tags/{tag_def_id}/approve", response_model=TagApprovalResponse)
async def approve_tag(
    tag_def_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("tags:approve")),
) -> TagApprovalResponse:
    tag_def = await approve_tag_def(session, tag_def_id=tag_def_id)
    if tag_def is None:
        raise AppError(status_code=404, title="Tag not found", code="tag_not_found")
    return TagApprovalResponse(id=str(tag_def.id), name=tag_def.name, status=tag_def.status)


@router.post("/admin/tags/{tag_def_id}/reject", response_model=TagApprovalResponse)
async def reject_tag(
    tag_def_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("tags:approve")),
) -> TagApprovalResponse:
    tag_def = await reject_tag_def(session, tag_def_id=tag_def_id)
    if tag_def is None:
        raise AppError(status_code=404, title="Tag not found", code="tag_not_found")
    return TagApprovalResponse(id=str(tag_def.id), name=tag_def.name, status=tag_def.status)


@router.get("/tickets/{ticket_id}/context", response_model=TicketContextResponse)
async def get_ticket_context(
    ticket_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("tickets:read")),
) -> TicketContextResponse:
    ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one_or_none()
    if ticket is None:
        raise AppError(status_code=404, title="Ticket not found", code="ticket_not_found")

    messages = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == ticket.conversation_id)
            .order_by(Message.created_at)
        )
    ).scalars().all()

    notes = (
        await session.execute(
            select(InternalNote)
            .where(InternalNote.ticket_id == ticket_id)
            .order_by(InternalNote.created_at)
        )
    ).scalars().all()

    summary = (
        await session.execute(
            select(ResolutionSummary)
            .where(ResolutionSummary.ticket_id == ticket_id)
            .order_by(ResolutionSummary.created_at.desc())
        )
    ).scalars().first()

    linked_record_pointer = None
    if ticket.linked_record_type and ticket.linked_record_key:
        linked_record_pointer = {"type": ticket.linked_record_type, "key": ticket.linked_record_key}

    # [M7] the live-record re-fetch panel — an honest "not available yet" until person-2's M4
    # resolver exists, never a fabricated result.
    live_record = LiveRecordOut(
        status="unavailable", reason="Records lookup (M4) is not available yet"
    )

    return TicketContextResponse(
        transcript=[
            MessageOut(id=str(m.id), role=m.role, content=m.content, created_at=m.created_at)
            for m in messages
        ],
        internal_notes=[
            NoteOut(id=str(n.id), staff_id=str(n.staff_id), content=n.content, created_at=n.created_at)
            for n in notes
        ],
        ai_summary=summary.summary if summary else None,
        kb_sources=summary.kb_sources if summary else None,
        suggested_reply=summary.suggested_reply if summary else None,
        linked_record_pointer=linked_record_pointer,
        live_record=live_record,
    )
