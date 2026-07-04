"""M9 task-registration wrapper for embedding batches. Domain logic (idempotent upsert of
kb_chunk by (source_id, content_hash), embed calls OUTSIDE any DB transaction per [IMP-WRK-2/4])
is person-2's M3. Batch queue."""

from __future__ import annotations

import logging

from app.infra.queue.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.workers.embedding.embed_batch")
def embed_batch(source_id: str, tenant_id: str, batch: int) -> dict:
    # TODO(person-2, M3): embed one checkpointed batch; skip already-embedded chunks (idempotent).
    log.warning("embed_batch(%s#%s) invoked but M3 embedding (person-2) is not implemented yet", source_id, batch)
    return {"status": "not_implemented", "source_id": source_id, "batch": batch}
