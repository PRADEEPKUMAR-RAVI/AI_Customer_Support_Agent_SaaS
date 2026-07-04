"""Ticket + TicketEvent (M5). One ticket per conversation; state changes only via the
guarded CAS in ``domain.ticketing.transitions``."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, TenantMixin, TimestampMixin, uuid_pk


class Ticket(Base, TenantMixin, TimestampMixin):
    __tablename__ = "ticket"
    # [C2/IMP-TKT-4] exactly one ticket per conversation; creation is get-or-create.
    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_id", name="uq_ticket_tenant_conversation"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="normal")  # [C4]
    language: Mapped[str | None] = mapped_column(String(16))  # denormalised for filtering
    # Single nullable pointer, set only after a verified lookup (never a copy of fields).
    linked_record_type: Mapped[str | None] = mapped_column(String(32))
    linked_record_key: Mapped[str | None] = mapped_column(String(128))
    # After-hours follow-up address ([A15]) — kept distinct from any verified identity email.
    contact_email: Mapped[str | None] = mapped_column(String(320))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # claiming agent
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # reopen anchor
    last_customer_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TicketEvent(Base, TenantMixin, TimestampMixin):
    """Append-only audit of every transition (tenant-scoped; tenant_id auto-fills from GUC)."""

    __tablename__ = "ticket_event"

    id: Mapped[uuid.UUID] = uuid_pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket.id"), nullable=False, index=True
    )
    from_state: Mapped[str] = mapped_column(String(16), nullable=False)
    to_state: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)  # ai|agent|system|customer
