"""Transactional outbox + email dedupe log + the non-RLS platform audit log (M9 + M10)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, TenantMixin, TimestampMixin, uuid_pk


class Outbox(Base, TenantMixin, TimestampMixin):
    """A row is written in the SAME transaction as the state change that produced the event.
    The M9 relay drains ``pending`` rows with ``FOR UPDATE SKIP LOCKED`` [IMP-WRK-1]."""

    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = uuid_pk()
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending|sending|sent|failed|dead
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(200))


class EmailLog(Base, TenantMixin, TimestampMixin):
    """Durable send-dedupe. ``INSERT ... ON CONFLICT DO NOTHING`` before sending, so an
    at-least-once relay never sends the same (tenant, dedupe_key) twice [IMP-WRK-1]."""

    __tablename__ = "email_log"
    __table_args__ = (UniqueConstraint("tenant_id", "dedupe_key", name="uq_email_log_dedupe"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent")


class PlatformAuditLog(Base, TimestampMixin):
    """Cross-tenant, append-only audit of every RLS-bypass action (M10). NOT tenant-scoped and
    NOT under RLS — it records actions ACROSS tenants ([IMP-SEC-9])."""

    __tablename__ = "platform_audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
