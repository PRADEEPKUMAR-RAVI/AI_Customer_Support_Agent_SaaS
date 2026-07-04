"""M5 tag classification (curated + admin-approved growth). ``tag_def.status`` is the SINGLE
authoritative approval state [IMP-TKT-6]; ``ticket_tag.status`` is a denormalized copy taken at
tagging time, kept in sync when a def is approved (backfilled in the same transaction) so
listing a ticket's tags never needs a join to know what's approved."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, TenantMixin, TimestampMixin, uuid_pk


class TagDef(Base, TenantMixin, TimestampMixin):
    __tablename__ = "tag_def"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tag_def_tenant_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # approved|pending


class TicketTag(Base, TenantMixin, TimestampMixin):
    __tablename__ = "ticket_tag"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ticket_id", "tag_def_id", name="uq_ticket_tag_once"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket.id"), nullable=False, index=True
    )
    tag_def_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tag_def.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # approved|pending
