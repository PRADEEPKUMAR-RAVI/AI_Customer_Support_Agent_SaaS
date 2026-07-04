"""M8 — Analytics.

person-2 owns this module (rollups + the GET /analytics/* dashboards). The ONE function here
now is the P1-authored write contract the M2 engine depends on: `record_turn_metric(session,
dto)` — the single typed entry point that persists a per-turn metric. person-2 keeps this
signature and builds the read/query side (live `percentile_cont` queries per [T5]; the
`metric_rollup` table is deferred until volume demands it).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.infra.db.models.metrics import TurnMetric
from app.schemas.analytics import AnalyticsOverview, CostStats, LatencyStats, TagStats
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


# --- read side ([T5]: live queries over an indexed turn_metric; no rollup table) -----------

def _window(since: datetime | None, until: datetime | None) -> list:
    conds = []
    if since is not None:
        conds.append(TurnMetric.created_at >= since)
    if until is not None:
        conds.append(TurnMetric.created_at <= until)
    return conds


async def overview(session, *, since=None, until=None) -> AnalyticsOverview:
    w = _window(since, until)
    volume = await session.scalar(
        select(func.count(func.distinct(TurnMetric.conversation_id))).where(*w)
    ) or 0
    turns = await session.scalar(select(func.count()).select_from(TurnMetric).where(*w)) or 0
    escalated_convs = await session.scalar(
        select(func.count(func.distinct(TurnMetric.conversation_id))).where(
            TurnMetric.escalated.is_(True), *w
        )
    ) or 0
    autonomous = (volume - escalated_convs) / volume if volume else 0.0

    esc_rows = (
        await session.execute(
            select(TurnMetric.escalation_reason, func.count())
            .where(TurnMetric.escalated.is_(True), *w)
            .group_by(TurnMetric.escalation_reason)
        )
    ).all()
    lang_rows = (
        await session.execute(
            select(TurnMetric.detected_language, func.count())
            .where(TurnMetric.detected_language.isnot(None), *w)
            .group_by(TurnMetric.detected_language)
        )
    ).all()

    return AnalyticsOverview(
        volume=volume,
        turns=turns,
        autonomous_resolution_rate=round(autonomous, 4),
        escalation_reasons={(r or "unknown"): c for r, c in esc_rows},
        language_distribution={lang: c for lang, c in lang_rows},
    )


async def latency(session, *, since=None, until=None) -> LatencyStats:
    w = _window(since, until)
    p50 = func.percentile_cont(0.5).within_group(TurnMetric.latency_ms.asc())
    p95 = func.percentile_cont(0.95).within_group(TurnMetric.latency_ms.asc())
    p50v, p95v, count = (
        await session.execute(
            select(p50, p95, func.count()).where(TurnMetric.latency_ms.isnot(None), *w)
        )
    ).one()
    return LatencyStats(
        count=count or 0,
        p50_ms=float(p50v) if p50v is not None else None,
        p95_ms=float(p95v) if p95v is not None else None,
    )


async def cost(session, *, since=None, until=None) -> CostStats:
    w = _window(since, until)
    rows = (
        await session.execute(select(TurnMetric.conversation_id, TurnMetric.cost).where(*w))
    ).all()
    total = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    by_model: dict[str, float] = {}
    conversations: set = set()
    for conversation_id, cost_list in rows:
        conversations.add(conversation_id)
        for c in cost_list or []:
            usd = c.get("cost_usd") or 0.0
            total += usd
            prompt_tokens += c.get("prompt_tokens") or 0
            completion_tokens += c.get("completion_tokens") or 0
            model = c.get("model", "?")
            by_model[model] = round(by_model.get(model, 0.0) + usd, 6)
    per_conversation = total / len(conversations) if conversations else 0.0
    return CostStats(
        total_cost_usd=round(total, 6),
        cost_per_conversation=round(per_conversation, 6),
        total_prompt_tokens=prompt_tokens,
        total_completion_tokens=completion_tokens,
        by_model=by_model,
    )


async def tags(session, *, since=None, until=None) -> TagStats:
    # Real tag counts need M5's ticket_tag (P3). Empty until that table lands.
    return TagStats(tags={}, note="Tag analytics pending M5 (ticket_tag).")
