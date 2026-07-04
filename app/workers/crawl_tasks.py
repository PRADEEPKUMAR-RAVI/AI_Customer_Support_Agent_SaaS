"""M9 task-registration wrapper for URL crawling. Domain logic (SSRF-guarded, same-domain,
robots, depth/page/byte caps per [IMP-SEC-5]/[A11]) is person-2's M3 crawler. Batch queue."""

from __future__ import annotations

import logging

from app.infra.queue.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.workers.crawl.crawl_source")
def crawl_source(source_id: str, tenant_id: str) -> dict:
    # TODO(person-2, M3): call the SSRF-guarded crawler in infra/crawler under with_tenant.
    log.warning("crawl_source(%s) invoked but M3 crawler (person-2) is not implemented yet", source_id)
    return {"status": "not_implemented", "source_id": source_id}
