"""M7 agent workspace DTOs — presence, queue, reply, notes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tickets import TagOut


class PresenceRequest(BaseModel):
    status: str = Field(pattern="^(available|away)$")


class QueueEntry(BaseModel):
    id: str
    priority: str
    language: str | None
    escalated_at: datetime
    wait_seconds: float
    tags: list[TagOut] = []


class ReplyRequest(BaseModel):
    content: str = Field(min_length=1)


class NoteRequest(BaseModel):
    content: str = Field(min_length=1)


class ClaimResponse(BaseModel):
    id: str
    state: str
    assignee_id: str | None
