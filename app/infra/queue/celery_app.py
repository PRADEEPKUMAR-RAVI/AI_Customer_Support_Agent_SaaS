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
    # Task modules the worker must import to register tasks (extend as workers land).
    include=["app.workers.ingestion"],
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
    # Import task modules on worker/beat startup (avoids a celery_app <-> tasks import cycle).
    # person-3's `scheduled` module self-appends its own `sweep-ticket-timers` beat entry on
    # import, so it isn't listed in beat_schedule here.
    # NOTE: person-2's real ingestion tasks register via the Celery(include=[...]) above
    # (app.workers.ingestion). The old P1 `ingestion_tasks` stub (a not_implemented placeholder)
    # is intentionally dropped here — superseded, and keeping it registered a dead task name.
    imports=(
        "app.workers.notification_tasks",
        "app.workers.scheduled",
        "app.workers.crawl_tasks",
        "app.workers.embedding_tasks",
    ),
    # Single beat process schedules these (query-driven + idempotent, so a missed tick self-heals).
    beat_schedule={
        "drain-outbox": {"task": "app.workers.notification.drain_outbox", "schedule": 3.0},
    },
    timezone="UTC",
)
