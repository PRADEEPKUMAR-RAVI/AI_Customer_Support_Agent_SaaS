"""M8 Analytics — live turn_metric queries (rls integration). Write metrics, assert aggregates."""

from __future__ import annotations

import uuid

import pytest

from app.domain.escalation.reasons import EscalationReason
from app.infra.db.session import with_tenant
from app.schemas.metrics import ModelCost, TurnMetricDTO
from app.services import analytics_service
from app.services.analytics_service import record_turn_metric
from tests.fixtures.kb_eval import make_tenant

pytestmark = pytest.mark.rls


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    from app.infra.db.engine import engine

    await engine.dispose()
    yield
    await engine.dispose()


def _dto(conv, *, lang, latency, escalated=False, reason=None, usd=0.001):
    return TurnMetricDTO(
        conversation_id=conv, detected_language=lang, latency_ms=latency,
        escalated=escalated, escalation_reason=reason,
        cost=[ModelCost(model="gpt-4o-mini", prompt_tokens=100, completion_tokens=20, cost_usd=usd)],
    )


async def _seed_metrics(tenant):
    conv_a, conv_b, conv_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with with_tenant(tenant) as session:
        await record_turn_metric(session, _dto(conv_a, lang="en", latency=100))
        await record_turn_metric(session, _dto(conv_a, lang="en", latency=200))
        await record_turn_metric(session, _dto(conv_b, lang="es", latency=300, escalated=True,
                                               reason=EscalationReason.NO_GROUNDING))
        await record_turn_metric(session, _dto(conv_c, lang="en", latency=500))


async def test_overview_aggregates():
    tenant = await make_tenant("m8-overview", industry="retail")
    await _seed_metrics(tenant)
    async with with_tenant(tenant) as session:
        ov = await analytics_service.overview(session)
    assert ov.volume == 3  # 3 distinct conversations
    assert ov.turns == 4
    assert ov.autonomous_resolution_rate == pytest.approx(2 / 3, abs=1e-3)  # 1 of 3 escalated
    assert ov.escalation_reasons == {"no_grounding": 1}
    assert ov.language_distribution == {"en": 3, "es": 1}  # by turn


async def test_latency_percentiles():
    tenant = await make_tenant("m8-latency", industry="retail")
    await _seed_metrics(tenant)
    async with with_tenant(tenant) as session:
        lat = await analytics_service.latency(session)
    assert lat.count == 4
    assert 200 <= lat.p50_ms <= 300  # interpolated median of [100,200,300,500]
    assert lat.p95_ms >= 400


async def test_cost_aggregates():
    tenant = await make_tenant("m8-cost", industry="retail")
    await _seed_metrics(tenant)
    async with with_tenant(tenant) as session:
        c = await analytics_service.cost(session)
    assert c.total_cost_usd == pytest.approx(0.004, abs=1e-6)  # 4 turns * 0.001
    assert c.cost_per_conversation == pytest.approx(0.004 / 3, abs=1e-6)
    assert c.total_prompt_tokens == 400 and c.total_completion_tokens == 80
    assert c.by_model["gpt-4o-mini"] == pytest.approx(0.004, abs=1e-6)


async def test_empty_window_returns_zeros_not_errors():
    tenant = await make_tenant("m8-empty", industry="retail")
    async with with_tenant(tenant) as session:
        ov = await analytics_service.overview(session)
        lat = await analytics_service.latency(session)
        c = await analytics_service.cost(session)
    assert ov.volume == 0 and ov.autonomous_resolution_rate == 0.0
    assert lat.count == 0 and lat.p50_ms is None
    assert c.total_cost_usd == 0.0 and c.cost_per_conversation == 0.0


async def test_tags_counts_from_ticket_tag():
    """§4.2.3: analytics now counts real ticket_tag rows (the AI-turn wiring persists them)."""
    from app.infra.db.models.conversation import Conversation
    from app.services import tag_service, ticket_service

    tenant = await make_tenant("m8-tags", industry="retail")
    async with with_tenant(tenant) as session:
        conv = Conversation(session_id="s-m8-tags")
        session.add(conv)
        await session.flush()
        ticket = await ticket_service.get_or_create_ticket(session, conversation_id=conv.id)
        await tag_service.propose_tag(session, ticket_id=ticket.id, name="order_status",
                                      allowed_tags=["order_status"])
        await tag_service.propose_tag(session, ticket_id=ticket.id, name="billing_issue",
                                      allowed_tags=["order_status"])
        # Idempotent: re-proposing the same tag must not double-count.
        await tag_service.propose_tag(session, ticket_id=ticket.id, name="order_status",
                                      allowed_tags=["order_status"])
    async with with_tenant(tenant) as session:
        t = await analytics_service.tags(session)
    assert t.tags == {"order_status": 1, "billing_issue": 1}
    assert t.note is None  # the stale "pending M5" note is gone


async def test_csat_score_from_turn_metric():
    """§5.6: thumbs up/down CSAT aggregated from turn_metric.csat."""
    import uuid as _uuid

    from app.infra.db.models.metrics import TurnMetric

    tenant = await make_tenant("m8-csat", industry="retail")
    conv = _uuid.uuid4()
    async with with_tenant(tenant) as session:
        for rating in ("up", "up", "down", None):  # None = unrated, excluded from the score
            session.add(TurnMetric(conversation_id=conv, csat=rating))
    async with with_tenant(tenant) as session:
        c = await analytics_service.csat(session)
    assert c.up == 2 and c.down == 1 and c.rated == 3
    assert c.score == pytest.approx(2 / 3, abs=1e-3)
