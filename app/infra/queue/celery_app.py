"""Celery app with two queues from day one (audit [IMP-DAT-3]).

  * ``interactive`` — outbox/email sends + the idle/SLA/reopen scheduled sweeps (time-critical).
  * ``batch``       — ingestion / crawl / embedding (bulk), so one tenant's upload can't
                      starve everyone's escalation emails.

Reliability settings [IMP-WRK-2]: acks_late + reject_on_worker_lost + prefetch=1 so a worker
crash redelivers (tasks are written to be idempotent). Run one beat (or celery-redbeat).
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "cs_agent",
    broker=_settings.redis_url,
    backend=None,  # fire-and-forget; results not needed (avoids Redis memory growth)
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    task_default_queue="interactive",
    task_routes={
        "app.workers.ingestion.*": {"queue": "batch"},
        "app.workers.crawl.*": {"queue": "batch"},
        "app.workers.embedding.*": {"queue": "batch"},
        "app.workers.notification.*": {"queue": "interactive"},
        "app.workers.scheduled.*": {"queue": "interactive"},
    },
    timezone="UTC",
    # Task modules imported when a worker/beat process starts (not at this module's own import
    # time — `imports` is lazy, so a task module that itself imports `celery_app` never creates
    # a circular import). Add each new app/workers/*.py module here as it's built.
    imports=("app.workers.scheduled",),
)
