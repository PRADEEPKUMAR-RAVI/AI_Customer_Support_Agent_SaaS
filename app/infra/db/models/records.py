"""M4 record storage + connector config (Records & Connectors).

``RecordDataset``/``RecordRow`` back the **Upload** source; ``Connector`` backs the live **DB/API**
sources. All tenant-scoped (RLS). ``RecordRow.data`` is the mapped ``{verify-field value + returned
schema fields (+ alias keys)}`` dict — the resolver returns it verbatim and the engine
(``record_service.lookup_record``) runs ``verify_record`` on it (verify never happens in the
resolver). Connector credentials are AES-GCM encrypted (AAD bound to tenant+connector) — never
stored in plaintext, never returned to the model or the widget.

Field mapping is a JSONB column on ``Connector`` (their column/response field -> schema field,
including the verify field) rather than a separate table — sufficient for the POC ``[T4]``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, TenantMixin, TimestampMixin, uuid_pk


class RecordDataset(Base, TenantMixin, TimestampMixin):
    """One uploaded dataset per (tenant, record_type). Metadata only; rows live in RecordRow."""

    __tablename__ = "record_dataset"
    __table_args__ = (
        UniqueConstraint("tenant_id", "record_type", name="uq_record_dataset_tenant_type"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RecordRow(Base, TenantMixin, TimestampMixin):
    """A single uploaded record. ``key`` is the (normalized) primary-key value; ``data`` is the
    mapped dict the resolver returns (verify field + returned fields + any alias keys)."""

    __tablename__ = "record_row"
    __table_args__ = (
        UniqueConstraint("tenant_id", "record_type", "key", name="uq_record_row_tenant_type_key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    record_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Connector(Base, TenantMixin, TimestampMixin):
    """A live DB/API source for one (tenant, record_type). ``encrypted_credentials`` holds the
    AES-GCM ciphertext (DB DSN or API auth secret); ``config`` holds non-secret bits (query
    template / base URL / method); ``field_map`` maps the source's fields -> schema fields.
    ``version`` is bumped on edit so the per-connector engine/client cache invalidates."""

    __tablename__ = "connector"
    __table_args__ = (
        UniqueConstraint("tenant_id", "record_type", name="uq_connector_tenant_type"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(8), nullable=False)  # "db" | "api"
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    field_map: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
