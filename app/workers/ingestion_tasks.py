"""M9 owns the Celery task registration + queue routing; the ingestion DOMAIN logic
(parse → chunk → embed, idempotent per-batch checkpointing per [IMP-WRK-4]) is person-2's M3
(`knowledge_service`). These wrappers stay thin — no domain logic here. Routed to the `batch`
queue so a big upload can't starve the interactive queue ([IMP-DAT-3])."""

from __future__ import annotations

import logging

from app.infra.queue.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.workers.ingestion.ingest_source")
def ingest_source(source_id: str, tenant_id: str) -> dict:
    # TODO(person-2, M3): call knowledge_service.ingest_source(...) under with_tenant(tenant_id),
    # chunked into idempotent per-batch steps; flip source→ready only after all batches commit.
    log.warning("ingest_source(%s) invoked but M3 ingestion (person-2) is not implemented yet", source_id)
    return {"status": "not_implemented", "source_id": source_id}
