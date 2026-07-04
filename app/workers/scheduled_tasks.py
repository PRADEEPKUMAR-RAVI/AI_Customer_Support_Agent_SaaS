"""M9 — query-driven scheduled sweeps (audit [IMP-WRK-3]).

Idle-resolve (`ai_handling → resolved`) and idle-close (`resolved → closed`) as the SYSTEM
actor. Query-driven (`WHERE <timestamp> < now() - interval`), guarded by `FOR UPDATE SKIP LOCKED`
AND the CAS transition primitive — so a late customer message and this sweep can't both win, and
missed beat ticks self-correct. Reopen is event-driven (M2 on inbound message), not swept.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import TenantDefaults
from app.domain.ticketing.states import Actor, TicketState
from app.infra.db.engine import SessionLocal
from app.infra.db.models.tenant import AgentSettings, Tenant
from app.infra.db.models.ticket import Ticket
from app.infra.db.session import with_tenant
from app.infra.queue.celery_app import celery_app
from app.services.ticket_service import transition
from app.workers._run import run_async


async def _sweep_tenant(tid) -> dict:
    now = datetime.now(timezone.utc)
    resolved = closed = 0
    async with with_tenant(tid) as s:
        cfg = (await s.execute(select(AgentSettings))).scalar_one_or_none()
        cfg = cfg.config if cfg else {}
        resolve_after = int(cfg.get("resolve_after_idle_seconds", TenantDefaults.RESOLVE_AFTER_IDLE_SECONDS))
        close_after = int(cfg.get("close_after_idle_seconds", TenantDefaults.CLOSE_AFTER_IDLE_SECONDS))

        # ai_handling idle -> resolved
        for t in (
            await s.execute(
                select(Ticket)
                .where(Ticket.state == TicketState.AI_HANDLING.value,
                       Ticket.last_customer_msg_at < now - timedelta(seconds=resolve_after))
                .with_for_update(skip_locked=True)
            )
        ).scalars().all():
            if await transition(s, ticket=t, to_state=TicketState.RESOLVED, actor=Actor.SYSTEM):
                resolved += 1

        # resolved idle -> closed
        for t in (
            await s.execute(
                select(Ticket)
                .where(Ticket.state == TicketState.RESOLVED.value,
                       Ticket.resolved_at < now - timedelta(seconds=close_after))
                .with_for_update(skip_locked=True)
            )
        ).scalars().all():
            if await transition(s, ticket=t, to_state=TicketState.CLOSED, actor=Actor.SYSTEM):
                closed += 1
    return {"resolved": resolved, "closed": closed}


async def _sweep_all() -> dict:
    async with SessionLocal() as s:
        tenant_ids = (await s.execute(select(Tenant.id).where(Tenant.status == "active"))).scalars().all()
    totals = {"resolved": 0, "closed": 0}
    for tid in tenant_ids:
        r = await _sweep_tenant(tid)
        totals["resolved"] += r["resolved"]
        totals["closed"] += r["closed"]
    return totals


@celery_app.task(name="app.workers.scheduled.sweep_idle_tickets")
def sweep_idle_tickets() -> dict:
    return run_async(_sweep_all())
