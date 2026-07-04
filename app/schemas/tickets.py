"""M5 ticketing DTOs — list/detail/reopen/tag-approve/context."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TagOut(BaseModel):
    name: str
    status: str  # approved|pending|rejected


class TicketResponse(BaseModel):
    id: str
    conversation_id: str
    state: str
    priority: str
    language: str | None
    linked_record_type: str | None
    linked_record_key: str | None
    contact_email: str | None
    assignee_id: str | None
    created_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None
    tags: list[TagOut] = []


class TicketPatchRequest(BaseModel):
    priority: str | None = None  # low|normal|high
    contact_email: str | None = None
    # The only legal value is "resolved" — routes through the guarded CAS (with_agent/
    # ai_handling -> resolved), never a direct state write. Anything else is rejected.
    state: str | None = None


class TicketReopenResponse(BaseModel):
    applied: bool
    state: str | None = None


class TagApprovalResponse(BaseModel):
    id: str
    name: str
    status: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime


class NoteOut(BaseModel):
    id: str
    staff_id: str
    content: str
    created_at: datetime


class LiveRecordOut(BaseModel):
    """M7's live re-fetched record panel. ``status="unavailable"`` until Person-2's M4 resolver
    exists — an honest "not ready yet" state, never a fabricated result."""

    status: str  # ok|unavailable
    record: dict | None = None
    reason: str | None = None


class TicketContextResponse(BaseModel):
    """The aggregated payload the agent workspace needs — [IMP-FE-8]. ``ai_summary``,
    ``kb_sources``, and ``suggested_reply`` stay null/empty until M2's engine populates the
    resolution/escalation-summary artifact; that's an accurate "not ready yet" state, not a bug."""

    transcript: list[MessageOut]
    internal_notes: list[NoteOut]
    ai_summary: str | None
    kb_sources: list | None
    suggested_reply: str | None
    linked_record_pointer: dict | None
    live_record: LiveRecordOut
