"""Resolves the active ``EmbeddingPort`` from settings (fake | bge_onnx | cohere)."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.infra.embeddings.base import EmbeddingPort


@lru_cache
def get_embedder() -> EmbeddingPort:
    s = get_settings()
    if s.use_fake_embeddings:
        from app.infra.embeddings.fake import FakeEmbedder

        return FakeEmbedder(dim=s.embed_dim)
    if s.embeddings_provider == "bge_onnx":
        from app.infra.embeddings.bge_onnx_client import BgeOnnxClient

        return BgeOnnxClient(
            embed_model=s.embed_model,
            rerank_model=s.rerank_model,
            dim=s.embed_dim,
            cache_dir=s.embed_cache_dir,
        )
    raise NotImplementedError(
        "Cohere adapter is an optional post-Phase-0 swap; default is self-hosted bge_onnx."
    )
