"""FakeEmbedder + FakeReranker — deterministic, offline (dev/CI default, no vendor keys).

The embedder maps text -> a stable unit vector derived from a hash, so the same text always
embeds identically (retrieval is reproducible). The reranker scores by lexical token overlap
so results are meaningful AND deterministic in tests.
"""

from __future__ import annotations

import hashlib
import math

from app.infra.embeddings.base import EmbeddingPort, RerankHit


class FakeEmbedder(EmbeddingPort):
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        # Expand a digest into `dim` floats deterministically, then L2-normalise.
        vals: list[float] = []
        counter = 0
        while len(vals) < self.dim:
            h = hashlib.sha256(f"{text}|{counter}".encode()).digest()
            for i in range(0, len(h), 2):
                if len(vals) >= self.dim:
                    break
                vals.append((int.from_bytes(h[i : i + 2], "big") / 65535.0) * 2 - 1)
            counter += 1
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        return [v / norm for v in vals]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def rerank(self, query: str, docs: list[str], top_k: int) -> list[RerankHit]:
        q = set(query.lower().split())
        hits: list[RerankHit] = []
        for i, d in enumerate(docs):
            dt = set(d.lower().split())
            overlap = len(q & dt)
            score = overlap / (len(q) or 1)
            hits.append(RerankHit(index=i, score=round(score, 6)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]


# Alias — the reranker is deterministic scoring, exposed on the same fake for simplicity.
FakeReranker = FakeEmbedder
