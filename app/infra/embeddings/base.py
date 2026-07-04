"""EmbeddingPort — swappable embed + rerank seam.

Default adapter is self-hosted BGE via ONNX (BGE-M3 embed + bge-reranker-v2-m3 rerank);
Cohere is an optional managed swap. ``dim`` must match the ``kb_chunk.embedding`` column
(1024 for BGE-M3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class RerankHit:
    index: int  # index into the input docs list
    score: float


@runtime_checkable
class EmbeddingPort(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def rerank(self, query: str, docs: list[str], top_k: int) -> list[RerankHit]: ...
