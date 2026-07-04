"""M3 — Knowledge/RAG retrieval (walking-skeleton slice).

`kb_retrieve` embeds the query, pulls per-tenant candidates via pgvector (RLS-scoped), reranks,
and applies the grounding gate (top-1 rerank >= threshold). Returns a GroundedResult or a signal
(NO_GROUNDING / KB_NOT_READY). M3's owner (person-2) later swaps in full hybrid + RRF + real
BGE-ONNX; the CONTRACT here is what M2 depends on and does not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select

from app.infra.db.models.knowledge import KbChunk, Source
from app.infra.embeddings.router import get_embedder

# Provisional dev default until the eval-derived threshold is calibrated ([IMP-DEL-5]).
PROVISIONAL_THRESHOLD = 0.15
CANDIDATE_N = 40

NO_GROUNDING = "NO_GROUNDING"
KB_NOT_READY = "KB_NOT_READY"


@dataclass
class GroundedResult:
    chunks: list[dict] = field(default_factory=list)   # {content, source_id, title, ...}
    citations: list[dict] = field(default_factory=list)
    top_score: float = 0.0


async def kb_retrieve(session, query: str, *, top_k: int = 5, threshold: float | None = None):
    threshold = PROVISIONAL_THRESHOLD if threshold is None else threshold

    # Readiness gate ([IMP-RAG-5]): distinguish "still learning" from "no relevant chunk".
    ready = await session.scalar(
        select(func.count()).select_from(Source).where(Source.status == "ready")
    )
    if not ready:
        return KB_NOT_READY

    embedder = get_embedder()
    qvec = (await embedder.embed([query]))[0]

    # Dense candidates via pgvector cosine distance (HNSW index; RLS scopes to this tenant).
    rows = (
        await session.execute(
            select(KbChunk).order_by(KbChunk.embedding.cosine_distance(qvec)).limit(CANDIDATE_N)
        )
    ).scalars().all()
    if not rows:
        return NO_GROUNDING

    # Rerank (cross-encoder; FakeReranker uses lexical overlap in dev).
    hits = await embedder.rerank(query, [r.content for r in rows], top_k)
    if not hits:
        return NO_GROUNDING

    # Grounding gate: top-1 rerank score must clear the threshold ([IMP-RAG-1]).
    if hits[0].score < threshold:
        return NO_GROUNDING

    chosen = [(rows[h.index], h.score) for h in hits]
    source_ids = {c.source_id for c, _ in chosen}
    titles = dict(
        (
            await session.execute(select(Source.id, Source.name).where(Source.id.in_(source_ids)))
        ).all()
    )
    chunks, citations = [], []
    for i, (c, score) in enumerate(chosen):
        title = titles.get(c.source_id, "source")
        chunks.append({"content": c.content, "source_id": str(c.source_id), "title": title, "score": score})
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
