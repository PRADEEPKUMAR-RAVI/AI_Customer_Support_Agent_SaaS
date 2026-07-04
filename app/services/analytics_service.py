"""M8 — Analytics.

person-2 owns this module (rollups + the GET /analytics/* dashboards). The ONE function here
now is the P1-authored write contract the M2 engine depends on: `record_turn_metric(session,
dto)` — the single typed entry point that persists a per-turn metric. person-2 keeps this
signature and builds the read/query side (live `percentile_cont` queries per [T5]; the
`metric_rollup` table is deferred until volume demands it).
"""

from __future__ import annotations

from app.infra.db.models.metrics import TurnMetric
from app.schemas.metrics import TurnMetricDTO


async def record_turn_metric(session, dto: TurnMetricDTO) -> None:
    """The single write entry point for per-turn metrics. M2 calls only this."""
    session.add(
        TurnMetric(
            conversation_id=dto.conversation_id,
            message_id=dto.message_id,
            detected_language=dto.detected_language,
            retrieval_hits=dto.retrieval_hits,
            tool_calls=dto.tool_calls,
            escalated=dto.escalated,
            escalation_reason=dto.escalation_reason.value if dto.escalation_reason else None,
            latency_ms=dto.latency_ms,
            cost=[c.model_dump() for c in dto.cost],
        )
    )
