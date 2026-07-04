"""M3 ingest -> hybrid retrieve integration test (marked ``rls``; needs live pgvector).

Proves the walking-skeleton loop end-to-end on FakeEmbedder: ingest -> ready with parent/child
rows shaped correctly, on-topic query grounds+cites, off-topic refuses, empty tenant is
KB_NOT_READY, and retrieval is tenant-isolated. Run: ``RUN_RLS_TESTS=1`` with the compose
Postgres (``cs_app`` role) + ``INGEST_INLINE=true``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

import app.services.knowledge_service as ks
from app.core.config import TenantDefaults
from app.infra.db.models.knowledge import FileBlob, KbChunk, Source
from app.infra.db.session import with_tenant
from app.services.knowledge_service import (
    KB_NOT_READY,
    NO_GROUNDING,
    GroundedResult,
    kb_retrieve,
    reingest_source,
)
from tests.fixtures.kb_eval import ingest_corpus, ingest_paste, make_tenant

pytestmark = pytest.mark.rls

_LONG_DOC = " ".join(f"clause{i}" for i in range(1200))  # one parent, multiple children


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    from app.infra.db.engine import engine

    await engine.dispose()
    yield
    await engine.dispose()


async def test_ingest_marks_ready_with_correct_parent_child_shape():
    tenant = await make_tenant("kb-shape")
    source_id = await ingest_paste(tenant, "long", _LONG_DOC)

    async with with_tenant(tenant) as session:
        source = await session.get(Source, source_id)
        assert source.status == "ready"
        assert source.chunk_count > 1  # 1200 words -> multiple children
        assert source.error is None

        # Parents: parent_id IS NULL, embedding NULL, ts NULL.
        parents = (
            await session.execute(select(KbChunk).where(KbChunk.parent_id.is_(None)))
        ).scalars().all()
        assert parents and all(p.embedding is None and p.ts is None for p in parents)

        # Children: parent_id set, embedding + ts present.
        children = (
            await session.execute(select(KbChunk).where(KbChunk.parent_id.isnot(None)))
        ).scalars().all()
        assert len(children) == source.chunk_count
        assert all(c.embedding is not None and c.ts is not None for c in children)


async def test_on_topic_query_is_grounded_and_cited_with_parent_expansion():
    tenant = await make_tenant("kb-answer")
    await ingest_paste(tenant, "long", _LONG_DOC)

    async with with_tenant(tenant) as session:
        result = await kb_retrieve(session, "clause5 clause6 clause7")
        assert isinstance(result, GroundedResult)
        assert result.citations, "must cite >=1 chunk"
        assert result.top_score >= 0.0
        # Parent expansion: returned content is the ~1200-word parent, larger than any child.
        top_words = len(result.chunks[0]["content"].split())
        assert top_words > TenantDefaults.CHILD_CHUNK_MAX_TOKENS


async def test_off_topic_query_returns_no_grounding():
    tenant = await make_tenant("kb-offtopic")
    await ingest_corpus(tenant)
    async with with_tenant(tenant) as session:
        assert await kb_retrieve(session, "quantum entanglement subatomic particles") == NO_GROUNDING


async def test_empty_tenant_returns_kb_not_ready():
    tenant = await make_tenant("kb-empty")
    async with with_tenant(tenant) as session:
        assert await kb_retrieve(session, "anything at all") == KB_NOT_READY


async def test_sparse_arm_grounds_a_rare_exact_token_query():
    # A rare exact term unique to one Spanish doc should ground via the FTS/BM25 arm.
    tenant = await make_tenant("kb-sparse")
    await ingest_corpus(tenant)
    async with with_tenant(tenant) as session:
        result = await kb_retrieve(session, "devolver productos sin usar treinta dias")
        assert isinstance(result, GroundedResult)
        assert result.citations


async def test_reingest_swaps_serving_generation_and_deletes_old():
    # Delete-last reingest ([IMP-RAG-8]): after a successful reingest the serving pointer moves to
    # the new generation, only the new chunks remain, and retrieval answers from the new content.
    tenant = await make_tenant("kb-reingest")
    sid = await ingest_paste(tenant, "policy", "alpha widgets ship in exactly two days")

    async with with_tenant(tenant) as session:  # swap the stored bytes, then reingest
        blob = await session.get(FileBlob, sid)
        blob.data = b"beta gadgets ship in exactly five days"

    await reingest_source(source_id=sid, tenant_id=tenant)

    async with with_tenant(tenant) as session:
        source = await session.get(Source, sid)
        assert source.status == "ready"
        assert source.serving_version == 1  # pointer flipped to the new generation
        versions = (await session.execute(select(KbChunk.version).distinct())).scalars().all()
        assert set(versions) == {1}  # old generation deleted LAST — none left behind

        result = await kb_retrieve(session, "beta gadgets five days")
        assert isinstance(result, GroundedResult)
        assert any("beta" in c["content"] for c in result.chunks)
        assert all("alpha" not in c["content"] for c in result.chunks)  # old content gone


async def test_failed_reingest_keeps_old_generation_live(monkeypatch):
    # The non-negotiable of delete-last: a reingest that fails mid-build must leave the OLD version
    # serving (status back to ready, pointer unmoved, error recorded), never strip the source.
    tenant = await make_tenant("kb-reingest-fail")
    sid = await ingest_paste(tenant, "policy", "alpha widgets ship in exactly two days")

    async def _boom(*args, **kwargs):
        raise ks.IngestError("boom during embed")

    monkeypatch.setattr(ks, "_build_version", _boom)
    await reingest_source(source_id=sid, tenant_id=tenant)  # swallows, restores old generation

    async with with_tenant(tenant) as session:
        source = await session.get(Source, sid)
        assert source.status == "ready"          # NOT failed — old version stays live
        assert source.serving_version == 0        # pointer never moved
        assert source.error == "boom during embed"
        versions = (await session.execute(select(KbChunk.version).distinct())).scalars().all()
        assert set(versions) == {0}               # no orphaned half-built generation

        result = await kb_retrieve(session, "alpha widgets two days")  # still grounded on old
        assert isinstance(result, GroundedResult)
        assert any("alpha" in c["content"] for c in result.chunks)


async def test_retrieval_is_tenant_isolated():
    # Two tenants ingest identical content; a query under B must never surface A's chunks.
    tenant_a = await make_tenant("kb-iso-a")
    tenant_b = await make_tenant("kb-iso-b")
    await ingest_paste(tenant_a, "returns", "return unused items refund within thirty days")
    await ingest_paste(tenant_b, "returns", "return unused items refund within thirty days")

    async with with_tenant(tenant_b) as session:
        b_source_ids = {
            str(sid)
            for sid in (await session.execute(select(Source.id))).scalars().all()
        }
        result = await kb_retrieve(session, "return unused items refund")
        assert isinstance(result, GroundedResult)
        returned = {c["source_id"] for c in result.chunks}
        assert returned and returned <= b_source_ids  # only B's sources, never A's

        # Sanity: B sees exactly one source (its own), not A's colliding one.
        count = await session.scalar(select(func.count()).select_from(Source))
        assert count == 1
