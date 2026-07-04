"""turn_metric — the per-turn analytics fact table (M8's contract; M2 writes it, audit [IMP-DAT-5]).

Analytics reads these typed columns (never message.structured_out). Cost is a per-model list so
gpt-4o-mini + any future aux model are auditable separately.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, TenantMixin, TimestampMixin, uuid_pk


class TurnMetric(Base, TenantMixin, TimestampMixin):
    __tablename__ = "turn_metric"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message.id")
    )
    detected_language: Mapped[str | None] = mapped_column(String(16))
    retrieval_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(String(32))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # Per-model token+cost breakdown, e.g. [{"model": "gpt-4o-mini", "prompt": 120, "completion": 40, "cost_usd": 0.0001}]
    cost: Mapped[list | None] = mapped_column(JSONB)
