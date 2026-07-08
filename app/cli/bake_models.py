"""One-time model prefetch ("bake") — download the self-hosted embed + rerank ONNX weights into
``EMBED_CACHE_DIR`` (the mounted ``modelcache`` volume) so seeds/queries never pay the multi-GB
download lazily on first use. Idempotent: fastembed skips models already present in the cache.

Kept OUT of the Docker build (baking multi-GB weights into every image build is slow + fragile);
run it once against the running stack instead — the volume then persists across rebuilds/restarts:

    docker compose run --rm api python -m app.cli.bake_models

Re-run only when the configured embed/rerank model ids change.
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.infra.embeddings.bge_onnx_client import BgeOnnxClient


async def _bake() -> None:
    s = get_settings()
    print(
        f"Prefetching embed={s.embed_model!r} + rerank={s.rerank_model!r} (dim={s.embed_dim}) "
        f"into cache_dir={s.embed_cache_dir or '(fastembed default)'} — this is a one-time "
        f"~3-4GB download; subsequent seeds/queries reuse the cached weights.",
        flush=True,
    )
    client = BgeOnnxClient(
        embed_model=s.embed_model,
        rerank_model=s.rerank_model,
        dim=s.embed_dim,
        cache_dir=s.embed_cache_dir,
    )
    await client.warmup()  # downloads + loads both the embedder and the reranker
    print("Done — models cached in the persistent volume; seeds/queries are now instant.", flush=True)


def main() -> None:
    asyncio.run(_bake())


if __name__ == "__main__":
    main()
