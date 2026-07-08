"""FastAPI application factory. The OpenAPI it produces is the contract the FE typed client
is generated from (``app.cli.export_openapi``)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.middleware import RequestIdMiddleware
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging

log = logging.getLogger(__name__)


async def _warm_embeddings() -> None:
    """Load the real embed + rerank ONNX models off the request path so the FIRST customer turn
    never pays the cold load (the reranker is ~1GB). No-op on fakes — get_embedder() there is a
    zero-cost FakeEmbedder. Failure is non-fatal: turns just cold-load on first use."""
    from app.infra.embeddings.router import get_embedder

    try:
        log.info("warming embedder + reranker at startup...")
        await get_embedder().warmup()
        log.info("embedder + reranker warm; grounded turns are now fast.")
    except Exception:  # noqa: BLE001
        log.exception("embedder warmup failed; first grounded turn will cold-load")


async def _warm_llm() -> None:
    """Establish the LLM provider connection (DNS + TLS + SDK client init) off the request path, so
    the FIRST customer turn isn't a cold multi-second round-trip (measured ~3-18s cold vs ~1s warm).
    No-op cost on FakeLLM. Failure is non-fatal: the first real turn just cold-connects."""
    from app.infra.llm.model_router import get_llm

    try:
        log.info("warming LLM connection at startup...")
        await get_llm().complete([{"role": "user", "content": "ping"}], temperature=0)
        log.info("LLM connection warm; the first customer turn is now fast.")
    except Exception:  # noqa: BLE001
        log.exception("LLM warmup failed; the first turn will cold-connect")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = get_settings()
    # Background so health/readiness isn't blocked; the connection/models warm while the app
    # already accepts traffic. Both are no-ops on fakes.
    warm_tasks = []
    if not settings.use_fake_embeddings:
        warm_tasks.append(asyncio.create_task(_warm_embeddings()))
    if not settings.use_fake_llm:
        warm_tasks.append(asyncio.create_task(_warm_llm()))
    yield
    for t in warm_tasks:
        if not t.done():
            t.cancel()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title="AI Customer Support Agent API",
        version="0.1.0",
        description="Multi-tenant AI customer-support agent — Phase-0 foundation.",
        lifespan=_lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,  # refresh cookie
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
