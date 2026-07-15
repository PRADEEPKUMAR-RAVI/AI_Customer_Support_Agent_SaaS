"""M3 — Knowledge/RAG: ingestion write-path + grounded retrieval.

Two halves:
  * ``ingest_source`` / ``run_ingest`` — parse a source's bytes, chunk (parent/child), embed the
    children, store dense vectors + sparse tsvectors, and drive the Source FSM
    (queued -> ingesting -> ready | failed).
  * ``kb_retrieve`` — the M2-facing contract: hybrid (dense + sparse) -> RRF -> rerank ->
    grounding gate, returning ``GroundedResult | NO_GROUNDING | KB_NOT_READY``. The signature and
    return shape are frozen (M2 depends on them); only the body evolves.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, text as sql_text

from app.core.config import TenantDefaults, get_settings
from app.core.latency import atimed
from app.domain.knowledge.chunking import chunk_document
from app.infra.db.models.knowledge import FileBlob, KbChunk, Source
from app.infra.db.session import with_tenant
from app.infra.embeddings.router import get_embedder
from app.infra.parsers import get_parser

_ERROR_MAX_CHARS = 1000


class IngestError(Exception):
    """A business-level ingest failure (unsupported/empty/missing content). Terminal in
    Phase 1 — the source is marked ``failed`` with this message, no blanket retry."""


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()  # 64 hex fits String(64)


async def _load_segments(session, source, source_id):
    """Produce the list of text segments to chunk. Files/paste parse the stored bytes (PDF ->
    one segment per page); a URL source is crawled (one segment per page, carrying source_url)."""
    if source.kind == "url":
        from app.infra.crawler import crawl_url  # lazy — httpx/bs4 only needed for URL sources

        if not source.source_url:
            raise IngestError("url source has no source_url")
        return await crawl_url(source.source_url)

    blob = await session.get(FileBlob, source_id)
    if blob is None:
        raise IngestError("no content stored for source")
    return get_parser(source.kind, blob.filename, blob.content_type).parse(blob.data)


async def _build_version(session, source, source_id: uuid.UUID, version: int) -> int:
    """Parse → chunk → embed → write one generation of parent/child rows tagged ``version`` and
    build their tsvectors. Does NOT touch ``status``/``serving_version`` or any other generation —
    the caller owns the FSM and the serving-pointer swap. Returns the embedded child count.

    Parents are stored with a NULL embedding (expanded into answer context at retrieval time); only
    children are embedded + get a tsvector, so retrieval's ``embedding IS NOT NULL`` filter keeps
    parents out of the candidate pool. Raises ``IngestError`` on an empty document.
    """
    segments = await _load_segments(session, source, source_id)  # list[ParseResult], per page

    settings = get_settings()
    embedder = get_embedder()
    embedder_id = "fake" if settings.use_fake_embeddings else settings.embed_model
    dim = settings.embed_dim

    # (child content, parent id, page_number, source_url) — page/url carried from the segment.
    to_embed: list[tuple[str, uuid.UUID, int | None, str | None]] = []
    for segment in segments:
        for parent in chunk_document(segment.text):
            parent_row = KbChunk(
                source_id=source_id,
                version=version,
                parent_id=None,
                content=parent.content,
                content_hash=_hash(parent.content),
                embedding=None,  # parents are not embedded
                ts=None,
                embedder_id=embedder_id,
                dim=dim,
                page_number=segment.page_number,
                source_url=segment.source_url,
            )
            session.add(parent_row)
            await session.flush()  # obtain parent_row.id for the children
            for child in parent.children:
                to_embed.append((child.content, parent_row.id, segment.page_number, segment.source_url))

    if not to_embed:
        raise IngestError("empty document (no chunks produced)")

    vectors = await embedder.embed([content for content, *_ in to_embed])
    for (content, parent_id, page_number, source_url), vector in zip(to_embed, vectors):
        session.add(
            KbChunk(
                source_id=source_id,
                version=version,
                parent_id=parent_id,
                content=content,
                content_hash=_hash(content),
                embedding=vector,
                ts=None,  # set in the bulk UPDATE below
                embedder_id=embedder_id,
                dim=dim,
                page_number=page_number,
                source_url=source_url,
            )
        )
    await session.flush()

    # Sparse arm: build the tsvector with the 'simple' config (NOT 'english') so unknown/CJK/
    # mixed text isn't wrongly stemmed. Retrieval MUST use plainto_tsquery('simple', ...) too.
    await session.execute(
        sql_text(
            "UPDATE kb_chunk SET ts = to_tsvector('simple', content) "
            "WHERE source_id = :sid AND version = :v AND embedding IS NOT NULL"
        ),
        {"sid": str(source_id), "v": version},
    )
    return len(to_embed)


async def ingest_source(session, *, source_id: uuid.UUID) -> None:
    """Initial ingest within an already tenant-scoped session. Raises on failure; the caller
    (``run_ingest``) records the ``failed`` status on a fresh session (this txn may roll back).

    Builds the source's current serving generation (``serving_version`` — 0 for a first ingest).
    Reingest of an already-``ready`` source goes through ``reingest_source`` (delete-last), never
    this path, so this may safely drop-and-rebuild its own generation.
    """
    source = await session.get(Source, source_id)
    if source is None:
        raise IngestError(f"source {source_id} not found")

    source.status = "ingesting"
    await session.flush()  # let a poller observe progress before the (possibly long) embed

    # Idempotent rebuild: drop any chunks from a prior (failed/redelivered) attempt of THIS
    # generation. It is not `ready`, so nothing is serving them — safe, and makes acks_late safe.
    await session.execute(
        delete(KbChunk).where(
            KbChunk.source_id == source_id, KbChunk.version == source.serving_version
        )
    )

    count = await _build_version(session, source, source_id, source.serving_version)
    source.status = "ready"
    source.chunk_count = count
    source.error = None


async def run_ingest(*, source_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Executor for both the Celery task and the inline path. Owns its own tenant session so a
    failure is recorded even after the working transaction rolls back."""
    try:
        async with with_tenant(tenant_id) as session:
            await ingest_source(session, source_id=source_id)
    except Exception as exc:  # noqa: BLE001 — terminal: record failed status and stop
        await _mark_failed(source_id=source_id, tenant_id=tenant_id, error=str(exc))


async def _mark_failed(*, source_id: uuid.UUID, tenant_id: uuid.UUID, error: str) -> None:
    async with with_tenant(tenant_id) as session:
        source = await session.get(Source, source_id)
        if source is not None:
            source.status = "failed"
            source.error = error[:_ERROR_MAX_CHARS]


async def reingest_source(*, source_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Delete-last reingest ([IMP-RAG-8], Watch-out #4). Build the NEXT generation while the
    current one keeps serving, flip ``serving_version`` in one transaction, then delete the old
    generation LAST. Any failure before the flip leaves the old generation live (``ready`` again,
    with the error recorded) — a failed reingest never strips a source of its answers.

    Owns its own tenant sessions (one per phase) so the flip is atomic and independent of the build.
    """
    try:
        # Phase A — mark reingesting + clear any orphaned non-serving generations from a prior run.
        async with with_tenant(tenant_id) as session:
            source = await session.get(Source, source_id)
            if source is None:
                raise IngestError(f"source {source_id} not found")
            v_old = source.serving_version
            v_new = v_old + 1
            source.status = "reingesting"  # retrieval still serves v_old (keys on serving_version)
            source.error = None
            await session.execute(
                delete(KbChunk).where(
                    KbChunk.source_id == source_id, KbChunk.version != v_old
                )
            )

        # Phase B — build the new generation. The old one keeps answering throughout.
        async with with_tenant(tenant_id) as session:
            source = await session.get(Source, source_id)
            count = await _build_version(session, source, source_id, v_new)

        # Phase C — atomic serving-pointer flip: from here retrieval answers from v_new.
        async with with_tenant(tenant_id) as session:
            source = await session.get(Source, source_id)
            source.serving_version = v_new
            source.status = "ready"
            source.chunk_count = count
            source.error = None

        # Phase D — delete the OLD generation last (nothing serves it anymore).
        async with with_tenant(tenant_id) as session:
            await session.execute(
                delete(KbChunk).where(
                    KbChunk.source_id == source_id, KbChunk.version != v_new
                )
            )
    except Exception as exc:  # noqa: BLE001 — keep the old generation live; record the error
        await _reingest_failed(source_id=source_id, tenant_id=tenant_id, error=str(exc))


async def _reingest_failed(*, source_id: uuid.UUID, tenant_id: uuid.UUID, error: str) -> None:
    """A reingest failed before the flip. Restore ``ready`` on the still-live old generation and
    drop any half-built newer generation. The serving pointer never moved, so retrieval is intact."""
    async with with_tenant(tenant_id) as session:
        source = await session.get(Source, source_id)
        if source is None:
            return
        source.status = "ready"
        source.error = error[:_ERROR_MAX_CHARS]
        await session.execute(
            delete(KbChunk).where(
                KbChunk.source_id == source_id, KbChunk.version > source.serving_version
            )
        )


async def delete_source(session, *, source_id: uuid.UUID) -> None:
    """Remove a source and everything derived from it — chunks (vectors gone immediately) + the
    stored file bytes + the Source row. Caller owns the transaction + tenant context."""
    await session.execute(delete(KbChunk).where(KbChunk.source_id == source_id))
    await session.execute(delete(FileBlob).where(FileBlob.id == source_id))
    source = await session.get(Source, source_id)
    if source is not None:
        await session.delete(source)

# Provisional dev default used ONLY when the tenant's eval-derived threshold is not yet
# calibrated ([IMP-DEL-5]). agent_settings.relevance_threshold overrides it once set.
#
# Calibration (top-1 rerank score, both providers on a common 0..1 scale):
#   * FakeReranker (lexical overlap) -> on-topic ~0.75, off-topic 0.0.
#   * Real BAAI/bge-reranker-base -> the ONNX cross-encoder emits an unbounded LOGIT, which
#     BgeOnnxClient.rerank squashes through a sigmoid to 0..1. Measured: on-topic ~0.45-0.99
#     (a bare-relevant query can be as low as ~0.45), off-topic ~0.001. (NB: the raw logit for a
#     genuinely relevant hit can sit just below 0 — thresholding the raw logit would wrongly
#     reject real answers, which is why the client normalises with sigmoid.)
# 0.15 sits in the gap for BOTH providers with comfortable margin. A tenant may raise its
# relevance_threshold toward ~0.5 for stricter grounding.
PROVISIONAL_THRESHOLD = 0.15

NO_GROUNDING = "NO_GROUNDING"
KB_NOT_READY = "KB_NOT_READY"


@dataclass
class GroundedResult:
    chunks: list[dict] = field(default_factory=list)   # {content, source_id, title, ...}
    citations: list[dict] = field(default_factory=list)
    top_score: float = 0.0


async def kb_retrieve(
    session,
    query: str,
    *,
    candidates: int | None = None,  # N — pre-rerank pool (contract param, was hardcoded)
    top_k: int | None = None,
    threshold: float | None = None,  # tenant's relevance_threshold; None → provisional default
):
    """Contract (M2-facing): kb_retrieve(query, [tenant via RLS session], N, top_k, threshold)
    → GroundedResult{parent-expanded chunks, citations} | NO_GROUNDING | KB_NOT_READY."""
    candidates = candidates or TenantDefaults.HYBRID_CANDIDATES_N  # 40
    top_k = top_k or TenantDefaults.RERANK_TOP_K  # 5
    threshold = PROVISIONAL_THRESHOLD if threshold is None else threshold

    rrf_k = TenantDefaults.RRF_K  # 60

    # Readiness gate ([IMP-RAG-5]): distinguish "still learning" from "no relevant chunk". A
    # `reingesting` source has a live serving generation (delete-last, [IMP-RAG-8]), so it counts.
    servable = ("ready", "reingesting")
    ready = await session.scalar(
        select(func.count()).select_from(Source).where(Source.status.in_(servable))
    )
    if not ready:
        return KB_NOT_READY

    embedder = get_embedder()
    async with atimed("kb.embed"):  # first turn also pays the embed model cold-load (see embed.model_load)
        qvec = (await embedder.embed([query]))[0]

    # Both arms retrieve only child chunks (embedding IS NOT NULL — parents are never embedded)
    # from the source's CURRENT serving generation (version == serving_version), so a mid-ingest or
    # mid-reingest generation can't leak. RLS scopes to tenant.
    base = select(KbChunk).join(Source, KbChunk.source_id == Source.id).where(
        Source.status.in_(servable),
        KbChunk.embedding.isnot(None),
        KbChunk.version == Source.serving_version,
    )

    # Dense arm — pgvector cosine distance over the HNSW index.
    dense_rows = (
        await session.execute(base.order_by(KbChunk.embedding.cosine_distance(qvec)).limit(candidates))
    ).scalars().all()

    # Sparse arm — Postgres FTS/BM25. 'simple' config MUST match the ingest-side tsvector.
    tsq = func.plainto_tsquery("simple", query)
    sparse_rows = (
        await session.execute(
            base.where(KbChunk.ts.op("@@")(tsq)).order_by(func.ts_rank(KbChunk.ts, tsq).desc()).limit(candidates)
        )
    ).scalars().all()

    # Reciprocal Rank Fusion: fuse on RANK (dense distances and BM25 scores aren't comparable,
    # ranks are). score = Σ 1/(k + rank); dedup by chunk id ([IMP-RAG-1]).
    fused: dict[uuid.UUID, float] = {}
    row_by_id: dict[uuid.UUID, KbChunk] = {}
    for arm in (dense_rows, sparse_rows):
        for rank, row in enumerate(arm, start=1):
            fused[row.id] = fused.get(row.id, 0.0) + 1.0 / (rrf_k + rank)
            row_by_id.setdefault(row.id, row)
    if not fused:
        return NO_GROUNDING

    fused_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:candidates]
    cand_rows = [row_by_id[cid] for cid in fused_ids]

    # Rerank the fused pool (cross-encoder; FakeReranker = lexical overlap in dev). h.index
    # indexes cand_rows, not the per-arm lists. First turn pays the ~1GB rerank model cold-load
    # (see rerank.model_load) — the dominant first-query cost.
    async with atimed("kb.rerank", docs=len(cand_rows)):
        hits = await embedder.rerank(query, [r.content for r in cand_rows], top_k)
    if not hits or hits[0].score < threshold:  # grounding gate: top-1 must clear threshold
        return NO_GROUNDING
    chosen = [(cand_rows[h.index], h.score) for h in hits]

    # Parent expansion: return the ~2k-token parent as answer context; the citation still points
    # at the matched child (source/page/url). Batched lookup of the needed parents.
    parent_ids = {c.parent_id for c, _ in chosen if c.parent_id is not None}
    parent_content: dict[uuid.UUID, str] = {}
    if parent_ids:
        parent_content = dict(
            (
                await session.execute(
                    select(KbChunk.id, KbChunk.content).where(KbChunk.id.in_(parent_ids))
                )
            ).all()
        )

    source_ids = {c.source_id for c, _ in chosen}
    titles = dict(
        (
            await session.execute(select(Source.id, Source.name).where(Source.id.in_(source_ids)))
        ).all()
    )

    chunks, citations = [], []
    for i, (c, score) in enumerate(chosen):
        title = titles.get(c.source_id, "source")
        content = parent_content.get(c.parent_id, c.content) if c.parent_id else c.content
        chunks.append(
            {"content": content, "source_id": str(c.source_id), "title": title, "score": score}
        )
        citations.append(
            {
                "index": i,
                "source_id": str(c.source_id),
                "title": title,
                "page_number": c.page_number,
                "source_url": c.source_url,
            }
        )
    return GroundedResult(chunks=chunks, citations=citations, top_score=hits[0].score)


async def suggested_reply(session, query: str, *, threshold: float | None = None) -> dict | None:
    """Grounding-gated suggested reply for the escalation summary (Phase 3, [IMP-ESC-6]).

    A suggestion is offered ONLY when retrieval clears the same grounding gate as a customer
    answer — never an ungrounded guess. Returns ``{text, citations}`` or ``None``. The escalation
    summary (M2/M6) consumes this; if it's ``None`` the workspace shows a fixed 'no suggestion' label."""
    result = await kb_retrieve(session, query, threshold=threshold)
    if not isinstance(result, GroundedResult):
        return None
    return {"text": result.chunks[0]["content"], "citations": result.citations}
