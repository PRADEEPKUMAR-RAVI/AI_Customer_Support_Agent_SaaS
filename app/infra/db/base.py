"""Declarative base + shared mixins. Every tenant-scoped table carries ``tenant_id`` and is
protected by RLS (the policy + FORCE RLS are authored by hand in the Alembic migration)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantMixin:
    """Marks a table as tenant-scoped. The RLS policy in the migration keys off this column;
    every such table also gets ``ENABLE`` + ``FORCE ROW LEVEL SECURITY``.

    ``tenant_id`` auto-fills from the active tenant GUC (``current_setting('app.tenant_id')``)
    so inserts can't forget it and the RLS ``WITH CHECK`` always matches. With no tenant
    context the cast fails / is NULL → the insert is rejected (fail-closed)."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        index=True,
        nullable=False,
        server_default=text("current_setting('app.tenant_id', true)::uuid"),
    )


# The list of tenant-scoped tables, filled in as models import. The migration + the RLS leak
# test read this so a new table can't silently ship without an RLS policy [IMP-DAT-2].
TENANT_SCOPED_TABLES: set[str] = set()
