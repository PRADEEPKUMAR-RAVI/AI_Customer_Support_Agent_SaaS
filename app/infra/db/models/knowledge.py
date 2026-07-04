"""Knowledge / RAG tables (M3) + tenant-scoped file bytes (bytea, [IMP-SEC-2]).

``kb_chunk`` carries the dense vector (pgvector) AND the sparse tsvector, plus the citation
metadata ([A13]) and the embedder pin (embedder_id + dim) so a model change is a full
re-ingest, never an in-place swap.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.infra.db.base import Base, TenantMixin, TimestampMixin, uuid_pk

_EMBED_DIM = get_settings().embed_dim  # 1024 for BGE-M3


class Source(Base, TenantMixin, TimestampMixin):
    __tablename__ = "source"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # file|paste|url
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")  # queued|ingesting|ready|failed
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_url: Mapped[str | None] = mapped_column(String(2000))  # for URL sources


class KbChunk(Base, TenantMixin, TimestampMixin):
    __tablename__ = "kb_chunk"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # idempotent embed
    embedding: Mapped[list[float]] = mapped_column(Vector(_EMBED_DIM))
    ts: Mapped[str | None] = mapped_column(TSVECTOR)  # sparse BM25 arm
    language: Mapped[str | None] = mapped_column(String(16))  # [IMP-RAG-2] regconfig hint
    embedder_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=_EMBED_DIM)
    page_number: Mapped[int | None] = mapped_column(Integer)  # [A13] file citations
    source_url: Mapped[str | None] = mapped_column(String(2000))  # [A13] URL citations


class FileBlob(Base, TenantMixin, TimestampMixin):
    """Uploaded file bytes as tenant-scoped ``bytea`` (RLS-native; not a Large Object)."""

    __tablename__ = "file_blob"

    id: Mapped[uuid.UUID] = uuid_pk()
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
