"""M9 scheduled sweeps — ticketing/escalation timers [IMP-WRK-3], wired by person-3 into
person-1's Celery app. Query-driven + idempotent CAS per ticket (never a per-ticket
``eta``/``countdown`` delay), so a missed Beat tick self-corrects on the next one and nothing
double-fires.

First task module in ``app/workers/`` — ``celery_app.py`` autodiscovers this package, so a
worker/beat process picks it up with no further wiring. Runs across ALL active tenants: a
Celery task has no request-scoped tenant context, so each tenant's sweep opens its own
``with_tenant()`` transaction — never a single cross-tenant scan.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.config import TenantDefaults
from app.infra.db.engine import SessionLocal
from app.infra.db.models.tenant import AgentSettings, Tenant
from app.infra.db.session import with_tenant
from app.infra.queue.celery_app import celery_app
from app.services.ticket_service import (
    sweep_idle_ai_handling_to_resolved,
    sweep_idle_resolved_to_closed,
)

# Well under any realistic idle_seconds threshold (default 10 minutes) — a frequent tick just
# means the sweep is prompt, not that it does more work: each run only touches tickets that are
# ACTUALLY past their cutoff.
_SWEEP_INTERVAL_SECONDS = 30.0


async def _sweep_tenant(tenant_id) -> None:
    async with with_tenant(tenant_id) as session:
        settings_row = (await session.execute(select(AgentSettings))).scalar_one_or_none()
        config = settings_row.config if settings_row else {}
        resolve_after = config.get(
            "resolve_after_idle_seconds", TenantDefaults.RESOLVE_AFTER_IDLE_SECONDS
        )
        close_after = config.get(
            "close_after_idle_seconds", TenantDefaults.CLOSE_AFTER_IDLE_SECONDS
        )
        await sweep_idle_ai_handling_to_resolved(session, idle_seconds=resolve_after)
        await sweep_idle_resolved_to_closed(session, idle_seconds=close_after)


async def _sweep_all_tenants() -> None:
    async with SessionLocal() as session:
        tenant_ids = (
            await session.execute(select(Tenant.id).where(Tenant.status == "active"))
        ).scalars().all()
    for tenant_id in tenant_ids:
        await _sweep_tenant(tenant_id)


@celery_app.task(name="app.workers.scheduled.sweep_ticket_timers")
def sweep_ticket_timers() -> None:
    asyncio.run(_sweep_all_tenants())


celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "sweep-ticket-timers": {
        "task": "app.workers.scheduled.sweep_ticket_timers",
        "schedule": _SWEEP_INTERVAL_SECONDS,
    },
}
