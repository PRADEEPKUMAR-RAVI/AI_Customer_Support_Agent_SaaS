"""Conversation + Message (M2 domain — minimal Phase-0 shape; FK target for tickets)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, TenantMixin, TimestampMixin, uuid_pk


class Conversation(Base, TenantMixin, TimestampMixin):
    __tablename__ = "conversation"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Server-minted opaque anonymous session id ([IMP-SEC-3]); indexed for continuity lookups.
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    language: Mapped[str | None] = mapped_column(String(16))  # BCP-47, first detected
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # [A14]


class Message(Base, TenantMixin, TimestampMixin):
    __tablename__ = "message"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # customer|ai|agent|system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The validated per-turn structured envelope (answer_complete, tags, detected_language, …).
    structured_out: Mapped[dict | None] = mapped_column(JSONB)
    client_msg_id: Mapped[str | None] = mapped_column(String(64), index=True)  # idempotency
