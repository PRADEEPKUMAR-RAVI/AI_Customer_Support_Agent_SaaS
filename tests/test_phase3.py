"""Phase 3 — live-record re-fetch, grounding-gated suggested reply, turn_metric round-trip.

Marked ``rls`` (live Postgres). Live re-fetch is the internal staff read (no customer verify);
suggested_reply must obey the grounding gate; turn_metric write/read confirms the M8 read contract.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.security import encrypt_credential
from app.domain.records.schemas import Industry
from app.infra.db.models.records import Connector
from app.infra.db.session import with_tenant
from app.services.knowledge_service import suggested_reply
from app.services.record_service import refetch_linked_record, replace_dataset
from tests.fixtures.kb_eval import ingest_corpus, ingest_paste, make_tenant

pytestmark = pytest.mark.rls


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    from app.infra.db.engine import engine

    await engine.dispose()
    yield
    await engine.dispose()


# --- 3A: live re-fetch -----------------------------------------------------------------------

async def test_refetch_returns_current_record_without_verify():
    tenant = await make_tenant("p3-refetch", industry="retail")
    async with with_tenant(tenant) as session:
        await replace_dataset(session, record_type="order", rows=[
            {"key": "1001", "data": {"order_id": "1001", "email": "a@x.test", "status": "delivered",
                                     "eta": "2026-07-01", "tracking_ref": "TRK-1001"}},
        ])
    async with with_tenant(tenant) as session:
        result = await refetch_linked_record(
            session, tenant_id=tenant, industry=Industry.RETAIL, record_type="order", key="1001"
        )
    assert result.available is True
    assert result.record["status"] == "delivered"
    assert "email" not in result.record  # returned fields only, verify value never included


async def test_refetch_connector_error_is_live_unavailable():
    tenant = await make_tenant("p3-unavail", industry="retail")
    async with with_tenant(tenant) as session:
        connector = Connector(record_type="order", source_type="db", version=1,
                              encrypted_credentials="", config={"query_template": "SELECT 1"}, field_map={})
        session.add(connector)
        await session.flush()
        connector.encrypted_credentials = encrypt_credential(
            "postgresql+asyncpg://u:p@localhost:5432/x",  # localhost -> SSRF-blocked
            tenant_id=str(tenant), connector_id=str(connector.id),
        )
    async with with_tenant(tenant) as session:
        result = await refetch_linked_record(
            session, tenant_id=tenant, industry=Industry.RETAIL, record_type="order", key="1001"
        )
    assert result.available is False  # "live data unavailable — retry"


async def test_refetch_missing_record_is_available_but_none():
    tenant = await make_tenant("p3-gone", industry="retail")
    async with with_tenant(tenant) as session:
        await replace_dataset(session, record_type="order", rows=[])  # empty dataset
    async with with_tenant(tenant) as session:
        result = await refetch_linked_record(
            session, tenant_id=tenant, industry=Industry.RETAIL, record_type="order", key="9999"
        )
    assert result.available is True and result.record is None


# --- 3C: grounding-gated suggested reply -----------------------------------------------------

async def test_suggested_reply_grounded_on_topic():
    tenant = await make_tenant("p3-suggest", industry="retail")
    await ingest_paste(tenant, "returns", "Our return policy allows returns of unused items within 30 days for a full refund.")
    async with with_tenant(tenant) as session:
        out = await suggested_reply(session, "return unused items refund")
    assert out is not None
    assert "refund" in out["text"].lower()
    assert out["citations"]


async def test_suggested_reply_none_off_topic():
    tenant = await make_tenant("p3-suggest-off", industry="retail")
    await ingest_corpus(tenant)
    async with with_tenant(tenant) as session:
        assert await suggested_reply(session, "quantum entanglement subatomic particles") is None


async def test_suggested_reply_none_when_kb_empty():
    tenant = await make_tenant("p3-suggest-empty", industry="retail")
    async with with_tenant(tenant) as session:
        assert await suggested_reply(session, "anything") is None  # KB_NOT_READY -> no suggestion


# --- 3B: turn_metric write/read round-trip (P1 contract, P2 reads it in M8) -------------------

async def test_turn_metric_round_trips():
    from sqlalchemy import select

    from app.domain.escalation.reasons import EscalationReason
    from app.infra.db.models.metrics import TurnMetric
    from app.schemas.metrics import ModelCost, TurnMetricDTO
    from app.services.analytics_service import record_turn_metric

    tenant = await make_tenant("p3-metric", industry="retail")
    conversation_id = uuid.uuid4()
    async with with_tenant(tenant) as session:
        await record_turn_metric(session, TurnMetricDTO(
            conversation_id=conversation_id, detected_language="es", retrieval_hits=3,
            tool_calls=1, escalated=True, escalation_reason=EscalationReason.NO_GROUNDING,
            latency_ms=420, cost=[ModelCost(model="gpt-4o-mini", prompt_tokens=100, completion_tokens=20, cost_usd=0.001)],
        ))
    async with with_tenant(tenant) as session:
        row = (await session.execute(
            select(TurnMetric).where(TurnMetric.conversation_id == conversation_id)
        )).scalar_one()
        assert row.detected_language == "es"
        assert row.retrieval_hits == 3 and row.escalated is True
        assert row.escalation_reason == "no_grounding"
        assert row.cost[0]["model"] == "gpt-4o-mini"
