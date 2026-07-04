"""The canonical per-turn metric contract (P1-owned, audit [IMP-DAT-5]).

This is the ONE typed shape the M2 engine emits and M8 analytics consumes — units, the
escalation-reason enum, and per-model cost are defined here once. `cost` is a LIST so
gpt-4o-mini and any future aux model are auditable separately. Written via the single
`record_turn_metric(session, dto)` entry point (services/analytics_service.py).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.domain.escalation.reasons import EscalationReason


class ModelCost(BaseModel):
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None


class TurnMetricDTO(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID | None = None
    detected_language: str | None = None
    retrieval_hits: int = 0
    tool_calls: int = 0
    escalated: bool = False
    escalation_reason: EscalationReason | None = None
    latency_ms: int | None = None
    cost: list[ModelCost] = Field(default_factory=list)
