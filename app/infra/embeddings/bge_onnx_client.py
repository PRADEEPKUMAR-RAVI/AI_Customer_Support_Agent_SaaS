"""Real self-hosted embed + rerank via ONNX Runtime (default real adapter).

Uses ``fastembed`` (ONNX Runtime, CPU-friendly, quantised, no torch) so there's no vendor key and
no cloud call. fastembed doesn't ship BGE-M3, so the POC uses the closest self-hosted, 1024-dim,
multilingual, commercial-safe pair: ``intfloat/multilingual-e5-large`` (embed) +
``BAAI/bge-reranker-base`` (rerank). Imported lazily so dev/CI on fakes never needs the extra dep.
Install with the ``onnx`` extra: ``pip install -e '.[onnx]'``.

fastembed is synchronous; both calls are offloaded to a worker thread so they never block the
event loop — important for ``rerank``, which runs in the retrieval hot path.
"""

from __future__ import annotations

import math
import threading

import anyio

from app.core.latency import timed
from app.infra.embeddings.base import EmbeddingPort, RerankHit


class BgeOnnxClient(EmbeddingPort):
    def __init__(
        self, *, embed_model: str, rerank_model: str, dim: int, cache_dir: str | None = None
    ) -> None:
        self.dim = dim
        self._embed_model = embed_model
        self._rerank_model = rerank_model
        self._cache_dir = cache_dir  # persistent path -> baked into the Docker image layer
        self._embedder = None
        self._reranker = None
        # Double-checked-locking guards: embed()/rerank() run in worker threads (anyio.to_thread),
        # so a first customer turn racing the startup warmup could otherwise trigger TWO concurrent
        # model loads (the reranker is ~1GB). threading.Lock — the contended path is off the loop.
        self._embed_lock = threading.Lock()
        self._rerank_lock = threading.Lock()

    def _get_embedder(self):
        if self._embedder is None:
            with self._embed_lock:
                if self._embedder is None:
                    from fastembed import TextEmbedding  # lazy

                    # First call only: pays the ONNX model download + graph init (cold-load).
                    with timed("embed.model_load", model=self._embed_model):
                        self._embedder = TextEmbedding(
                            model_name=self._embed_model, cache_dir=self._cache_dir
                        )
        return self._embedder

    def _get_reranker(self):
        if self._reranker is None:
            with self._rerank_lock:
                if self._reranker is None:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder  # lazy

                    # First call only: the ~1GB cross-encoder load — the single largest first-query
                    # cost, isolated here so it shows up once and never again.
                    with timed("rerank.model_load", model=self._rerank_model):
                        self._reranker = TextCrossEncoder(
                            model_name=self._rerank_model, cache_dir=self._cache_dir
                        )
        return self._reranker

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _run() -> list[list[float]]:
            return [list(map(float, v)) for v in self._get_embedder().embed(texts)]

        return await anyio.to_thread.run_sync(_run)

    async def rerank(self, query: str, docs: list[str], top_k: int) -> list[RerankHit]:
        def _run() -> list[float]:
            # fastembed CrossEncoder.rerank(query, docs) -> one RAW LOGIT per doc, in docs order.
            # bge-reranker-base logits are unbounded (empirically ~ -9 off-topic … +6 on-topic, and
            # a genuinely relevant hit can still sit slightly BELOW 0, e.g. -0.2). The grounding gate
            # thresholds on a [0,1] score (the FakeReranker's scale), so squash the logit through a
            # sigmoid: this keeps the relative order (sigmoid is monotonic) but puts real scores on
            # the SAME 0..1 scale as the fake — on-topic ≈ 0.45–0.99, off-topic ≈ 0.001 — so one
            # tenant relevance_threshold (default 0.15) works identically for both providers.
            return [1.0 / (1.0 + math.exp(-float(s))) for s in self._get_reranker().rerank(query, docs)]

        scores = await anyio.to_thread.run_sync(_run)
        hits = [RerankHit(index=i, score=s) for i, s in enumerate(scores)]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    async def warmup(self) -> None:
        """Trigger model download + graph init off the hot path (cold p95 mitigation)."""
        await self.embed(["warmup"])
        await self.rerank("warmup", ["warmup"], 1)
