"""M3 ingestion task (batch queue).

Celery's worker is synchronous, so the task wraps the async ``run_ingest`` executor in
``asyncio.run`` (a fresh event loop per task; ``run_ingest`` owns its own ``with_tenant`` session
and records a terminal ``failed`` status on business errors). The ``app.workers.ingestion.*``
name routes this to the ``batch`` queue. ``acks_late`` is set globally; ingest is a source-scoped
rebuild, so a redelivery is idempotent.
"""

from __future__ import annotations

import asyncio
import uuid

from app.infra.queue.celery_app import celery_app
from app.services.knowledge_service import reingest_source, run_ingest


@celery_app.task(name="app.workers.ingestion.ingest_source_task")
def ingest_source_task(source_id: str, tenant_id: str) -> None:
    asyncio.run(run_ingest(source_id=uuid.UUID(source_id), tenant_id=uuid.UUID(tenant_id)))


@celery_app.task(name="app.workers.ingestion.reingest_source_task")
def reingest_source_task(source_id: str, tenant_id: str) -> None:
    """Delete-last reingest ([IMP-RAG-8]): keeps the old generation live until the new one is built
    and the serving pointer is flipped. A redelivery is idempotent (Phase A clears stale versions)."""
    asyncio.run(reingest_source(source_id=uuid.UUID(source_id), tenant_id=uuid.UUID(tenant_id)))
