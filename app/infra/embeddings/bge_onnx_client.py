"""Real self-hosted BGE embed + rerank via ONNX Runtime (default real adapter).

Uses ``fastembed`` (ONNX Runtime, CPU-friendly, INT8-quantised, no torch) so there is no
vendor key and no cloud call. Imported lazily so dev/CI on fakes never needs the extra dep.
Install with the ``onnx`` extra: ``pip install -e '.[onnx]'``.

Latency note (audit): ingest embedding is background; rerank is the one hot-path model —
keep it quantised, and rerank fewer candidates if p95 is high.
"""

from __future__ import annotations

from app.infra.embeddings.base import EmbeddingPort, RerankHit


class BgeOnnxClient(EmbeddingPort):
    def __init__(self, *, embed_model: str, rerank_model: str, dim: int) -> None:
        self.dim = dim
        self._embed_model = embed_model
        self._rerank_model = rerank_model
        self._embedder = None
        self._reranker = None

    def _get_embedder(self):
        if self._embedder is None:
            from fastembed import TextEmbedding  # lazy

            self._embedder = TextEmbedding(model_name=self._embed_model)
        return self._embedder

    def _get_reranker(self):
        if self._reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder  # lazy

            self._reranker = TextCrossEncoder(model_name=self._rerank_model)
        return self._reranker

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # fastembed is sync/generator-based; fine for background ingest workers.
        return [list(map(float, v)) for v in self._get_embedder().embed(texts)]

    async def rerank(self, query: str, docs: list[str], top_k: int) -> list[RerankHit]:
        scores = list(self._get_reranker().rerank(query, docs))
        hits = [RerankHit(index=i, score=float(s)) for i, s in enumerate(scores)]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]
